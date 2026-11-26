#include <algorithm>
#include <cfenv>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

namespace {

constexpr double PI = 3.14159265358979323846;
constexpr double INF = std::numeric_limits<double>::infinity();

inline double round1(double v) {
    return std::nearbyint(v * 10.0) / 10.0;
}

struct Match {
    double epoch;
    double s;
    double cross_track;
    int segment;
    int observation;
};

struct ShapeConfig {
    double max_corridor_cross_track_m;
    double max_gps_backward_jitter_m;
    double frenet_max_speed_mps;
    double terminal_reset_zone_m;
    double stale_delta_t_max_sec;
    double sigma;
    int max_candidates;
    int window;
    double horizon;
};

struct ShapeModel {
    double kx = 0.0;
    double ky = 0.0;
    double total_len = 0.0;
    int n_segs = 0;

    std::vector<double> x1, y1, dx, dy, safe_lens_sq, seg_lens, cum_starts;
    std::vector<double> unit_dx, unit_dy;
    std::vector<double> min_x, max_x, min_y, max_y;

    void build(
        int n_pts,
        const double* lats,
        const double* lons,
        const double* cums,
        double meters_per_deg_lat,
        double meters_per_deg_lon_eq
    ) {
        n_segs = std::max(0, n_pts - 1);
        double lat_sum = 0.0;
        for (int i = 0; i < n_pts; ++i) {
            lat_sum += lats[i];
        }
        double mean_lat = (n_pts > 0) ? (lat_sum / n_pts) : 0.0;
        kx = meters_per_deg_lon_eq * std::cos(mean_lat * PI / 180.0);
        ky = meters_per_deg_lat;
        total_len = (n_pts > 0) ? cums[n_pts - 1] : 0.0;

        x1.resize(n_segs);
        y1.resize(n_segs);
        dx.resize(n_segs);
        dy.resize(n_segs);
        safe_lens_sq.resize(n_segs);
        seg_lens.resize(n_segs);
        cum_starts.resize(n_segs);
        unit_dx.resize(n_segs);
        unit_dy.resize(n_segs);
        min_x.resize(n_segs);
        max_x.resize(n_segs);
        min_y.resize(n_segs);
        max_y.resize(n_segs);

        for (int i = 0; i < n_segs; ++i) {
            double sx1 = lons[i] * kx;
            double sy1 = lats[i] * ky;
            double sx2 = lons[i + 1] * kx;
            double sy2 = lats[i + 1] * ky;
            double sdx = sx2 - sx1;
            double sdy = sy2 - sy1;
            double lsq = sdx * sdx + sdy * sdy;
            double slen = std::sqrt(lsq);
            bool valid = slen > 1e-9;
            double safe_l = valid ? slen : 1.0;

            x1[i] = sx1;
            y1[i] = sy1;
            dx[i] = sdx;
            dy[i] = sdy;
            safe_lens_sq[i] = std::max(lsq, 1e-6);
            seg_lens[i] = slen;
            cum_starts[i] = cums[i];
            unit_dx[i] = valid ? (sdx / safe_l) : 0.0;
            unit_dy[i] = valid ? (sdy / safe_l) : 0.0;
            min_x[i] = std::min(sx1, sx2);
            max_x[i] = std::max(sx1, sx2);
            min_y[i] = std::min(sy1, sy2);
            max_y[i] = std::max(sy1, sy2);
        }
    }
};

struct CandRaw {
    double d;
    double s;
    int seg;
};

class RouteHMM {
public:
    const ShapeModel& shape;
    ShapeConfig cfg;

    std::vector<Match> states;
    std::vector<double> scores;
    std::vector<std::vector<Match>> paths;
    std::vector<Match> best_path;

    bool has_last = false;
    double last_epoch = 0.0;
    double last_lat = 0.0;
    double last_lng = 0.0;

    bool awaiting_direction = false;
    double blocked_at = 0.0;

    bool has_reversal = false;
    double rev_epoch = 0.0;
    double rev_s = 0.0;
    int rev_count = 0;
    double rev_lat = 0.0;
    double rev_lng = 0.0;

    RouteHMM(const ShapeModel& sh, const ShapeConfig& c) : shape(sh), cfg(c) {}

    std::vector<Match> candidates(double epoch, double lat, double lng, int index) const {
        double px = lng * shape.kx;
        double py = lat * shape.ky;
        double pad = cfg.max_corridor_cross_track_m + 1e-4;

        std::vector<CandRaw> raw;
        raw.reserve(16);
        for (int i = 0; i < shape.n_segs; ++i) {
            if (px < shape.min_x[i] - pad || px > shape.max_x[i] + pad ||
                py < shape.min_y[i] - pad || py > shape.max_y[i] + pad) {
                continue;
            }
            double dot = (px - shape.x1[i]) * shape.dx[i] + (py - shape.y1[i]) * shape.dy[i];
            double u = dot / shape.safe_lens_sq[i];
            if (u < 0.0) u = 0.0;
            else if (u > 1.0) u = 1.0;

            double rx = px - shape.x1[i] - u * shape.dx[i];
            double ry = py - shape.y1[i] - u * shape.dy[i];
            double d = std::hypot(rx, ry);
            if (d <= cfg.max_corridor_cross_track_m) {
                double s = shape.cum_starts[i] + u * shape.seg_lens[i];
                raw.push_back({d, s, i});
            }
        }
        if (raw.empty()) return {};

        std::stable_sort(raw.begin(), raw.end(), [](const CandRaw& a, const CandRaw& b) {
            return a.d < b.d;
        });

        std::vector<Match> out;
        out.reserve(cfg.max_candidates);
        for (const auto& c : raw) {
            bool near_dup = false;
            for (const auto& p : out) {
                if (std::abs(c.s - p.s) < 10.0) {
                    near_dup = true;
                    break;
                }
            }
            if (near_dup) continue;
            out.push_back({epoch, round1(c.s), round1(c.d), c.seg, index});
            if (static_cast<int>(out.size()) >= cfg.max_candidates) break;
        }
        return out;
    }

    bool update(double epoch, double lat, double lng, int index, Match& out_match) {
        if (awaiting_direction) {
            if (epoch - blocked_at <= cfg.stale_delta_t_max_sec) {
                return false;
            }
            awaiting_direction = false;
        }
        if (has_last && epoch <= last_epoch) {
            if (best_path.empty()) return false;
            out_match = best_path.back();
            return true;
        }

        auto new_cands = candidates(epoch, lat, lng, index);
        if (new_cands.empty()) {
            return false;
        }

        double dt = has_last ? (epoch - last_epoch) : 0.0;
        double move = has_last
            ? std::hypot((lng - last_lng) * shape.kx, (lat - last_lat) * shape.ky)
            : 0.0;

        int n_new = static_cast<int>(new_cands.size());
        std::vector<double> emission(n_new);
        if (has_last && lat == last_lat && lng == last_lng) {
            std::fill(emission.begin(), emission.end(), 0.0);
        } else {
            for (int i = 0; i < n_new; ++i) {
                double ratio = new_cands[i].cross_track / cfg.sigma;
                emission[i] = -0.5 * ratio * ratio;
            }
        }
        if (has_last && dt <= 30.0 && move >= cfg.sigma) {
            double mx = (lng - last_lng) * shape.kx;
            double my = (lat - last_lat) * shape.ky;
            for (int i = 0; i < n_new; ++i) {
                int seg = new_cands[i].segment;
                double ux = shape.unit_dx[seg];
                double uy = shape.unit_dy[seg];
                emission[i] -= 2.0 * (1.0 - (mx * ux + my * uy) / move);
            }
        }

        std::vector<double> new_scores(n_new, -INF);
        std::vector<std::vector<Match>> new_paths(n_new);

        if (states.empty() || dt > cfg.stale_delta_t_max_sec) {
            new_scores = emission;
            for (int i = 0; i < n_new; ++i) {
                new_paths[i] = {new_cands[i]};
            }
        } else {
            int n_old = static_cast<int>(states.size());
            bool any_valid = false;
            for (int j = 0; j < n_new; ++j) {
                const auto& b = new_cands[j];
                double best_opt = -INF;
                int best_parent = 0;
                for (int i = 0; i < n_old; ++i) {
                    const auto& a = states[i];
                    double ds = b.s - a.s;
                    bool terminal = (
                        shape.total_len > 1000.0 &&
                        a.s >= shape.total_len - cfg.terminal_reset_zone_m &&
                        b.s <= cfg.terminal_reset_zone_m &&
                        b.s < a.s - cfg.max_gps_backward_jitter_m
                    );
                    double distance = 0.0;
                    double penalty = 0.0;
                    if (terminal) {
                        distance = shape.total_len - a.s + b.s;
                        penalty = 4.0;
                    } else if (ds >= -cfg.max_gps_backward_jitter_m) {
                        distance = std::max(0.0, ds);
                        penalty = std::max(0.0, -ds) / cfg.sigma;
                    } else {
                        continue;
                    }
                    if (distance > dt * cfg.frenet_max_speed_mps + 3.0 * cfg.sigma) {
                        continue;
                    }
                    double tr = -std::abs(distance - move) / cfg.sigma - penalty;
                    double opt = scores[i] + tr;
                    if (opt > best_opt) {
                        best_opt = opt;
                        best_parent = i;
                    }
                }
                if (std::isfinite(best_opt)) {
                    any_valid = true;
                    new_scores[j] = best_opt + emission[j];
                    const auto& a = states[best_parent];
                    bool wrapped = (
                        shape.total_len > 1000.0 &&
                        a.s >= shape.total_len - cfg.terminal_reset_zone_m &&
                        b.s <= cfg.terminal_reset_zone_m &&
                        b.s < a.s - cfg.max_gps_backward_jitter_m
                    );
                    if (wrapped) {
                        new_paths[j] = {b};
                    } else {
                        const auto& ppath = paths[best_parent];
                        int plen = static_cast<int>(ppath.size());
                        int keep = std::min(plen, cfg.window - 1);
                        new_paths[j].assign(ppath.end() - keep, ppath.end());
                        new_paths[j].push_back(b);
                        while (new_paths[j].size() > 2 &&
                               epoch - new_paths[j].front().epoch > cfg.horizon) {
                            new_paths[j].erase(new_paths[j].begin());
                        }
                    }
                }
            }

            if (!any_valid) {
                const auto& prior = best_path.back();
                bool near_terminal = std::min(prior.s, shape.total_len - prior.s) <= cfg.terminal_reset_zone_m;
                const auto* nearest = &new_cands[0];
                for (int k = 1; k < n_new; ++k) {
                    if (new_cands[k].cross_track < nearest->cross_track) {
                        nearest = &new_cands[k];
                    }
                }
                if (near_terminal && nearest->s < prior.s - cfg.max_gps_backward_jitter_m && move >= 8.0) {
                    double moved_from_prev = has_reversal
                        ? std::hypot((lng - rev_lng) * shape.kx, (lat - rev_lat) * shape.ky)
                        : 0.0;
                    int count = 1;
                    if (has_reversal && epoch > rev_epoch &&
                        nearest->s <= rev_s + cfg.max_gps_backward_jitter_m &&
                        moved_from_prev >= 8.0) {
                        count = rev_count + 1;
                    } else if (has_reversal) {
                        count = rev_count;
                    }
                    if (!has_reversal || moved_from_prev >= 8.0) {
                        has_reversal = true;
                        rev_epoch = epoch;
                        rev_s = nearest->s;
                        rev_count = count;
                        rev_lat = lat;
                        rev_lng = lng;
                    }
                    if (count >= 2) {
                        states.clear();
                        scores.clear();
                        paths.clear();
                        best_path.clear();
                        has_last = false;
                        awaiting_direction = true;
                        blocked_at = epoch;
                    }
                } else {
                    has_reversal = false;
                }
                return false;
            }
            has_reversal = false;
        }

        states.clear();
        scores.clear();
        paths.clear();
        double max_sc = -INF;
        for (int j = 0; j < n_new; ++j) {
            if (std::isfinite(new_scores[j])) {
                states.push_back(new_cands[j]);
                scores.push_back(new_scores[j]);
                paths.push_back(std::move(new_paths[j]));
                if (new_scores[j] > max_sc) max_sc = new_scores[j];
            }
        }
        int best_idx = 0;
        double best_sc = -INF;
        for (int j = 0; j < static_cast<int>(scores.size()); ++j) {
            scores[j] -= max_sc;
            if (scores[j] > best_sc) {
                best_sc = scores[j];
                best_idx = j;
            }
        }
        best_path = paths[best_idx];
        has_last = true;
        last_epoch = epoch;
        last_lat = lat;
        last_lng = lng;

        out_match = best_path.back();
        return true;
    }
};

}  // namespace

extern "C" {

__declspec(dllexport) void* cpp_create_shape(
    int n_pts,
    const double* lats,
    const double* lons,
    const double* cums,
    double meters_per_deg_lat,
    double meters_per_deg_lon_eq
) {
    auto* model = new ShapeModel();
    model->build(n_pts, lats, lons, cums, meters_per_deg_lat, meters_per_deg_lon_eq);
    return model;
}

__declspec(dllexport) void cpp_free_shape(void* handle) {
    delete static_cast<ShapeModel*>(handle);
}

__declspec(dllexport) void cpp_project_runs(
    void* shape_handle,
    int n_runs,
    const int64_t* run_offsets,
    const double* epochs,
    const double* lats,
    const double* lons,
    double max_corridor_cross_track_m,
    double max_gps_backward_jitter_m,
    double frenet_max_speed_mps,
    double terminal_reset_zone_m,
    double stale_delta_t_max_sec,
    double horizon,
    int32_t* out_matched,
    double* out_s,
    double* out_ct
) {
    std::fesetround(FE_TONEAREST);
    const auto* shape = static_cast<const ShapeModel*>(shape_handle);
    ShapeConfig cfg{
        max_corridor_cross_track_m,
        max_gps_backward_jitter_m,
        frenet_max_speed_mps,
        terminal_reset_zone_m,
        stale_delta_t_max_sec,
        15.0,
        10,
        24,
        horizon,
    };

    for (int r = 0; r < n_runs; ++r) {
        int64_t beg = run_offsets[r];
        int64_t end = run_offsets[r + 1];
        RouteHMM hmm(*shape, cfg);
        double prev_ep = -INF;
        bool has_prev = false;
        int obs_idx = 0;
        for (int64_t i = beg; i < end; ++i) {
            double ep = epochs[i];
            if (has_prev && ep <= prev_ep) {
                out_matched[i] = 0;
                out_s[i] = 0.0;
                out_ct[i] = 0.0;
                obs_idx += 1;
                continue;
            }
            prev_ep = ep;
            has_prev = true;
            Match m{};
            if (hmm.update(ep, lats[i], lons[i], obs_idx, m)) {
                out_matched[i] = 1;
                out_s[i] = m.s;
                out_ct[i] = m.cross_track;
            } else {
                out_matched[i] = 0;
                out_s[i] = 0.0;
                out_ct[i] = 0.0;
            }
            obs_idx += 1;
        }
    }
}

}  // extern "C"
