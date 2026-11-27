#include "bus_native_common.hpp"

#include <algorithm>
#include <cfenv>
#include <unordered_map>
#include <vector>

namespace bus_native {

struct Match {
    double epoch;
    double s;
    double cross_track;
    int segment;
    int observation;
};

struct CandRaw {
    double d;
    double s;
    int seg;
};

struct ShapeModel {
    double kx = 0.0;
    double ky = 0.0;
    double total_len = 0.0;
    int n_segs = 0;

    std::vector<double> x1, y1, dx, dy, safe_lens_sq, seg_lens, cum_starts;
    std::vector<double> unit_dx, unit_dy;
    std::vector<double> min_x, max_x, min_y, max_y;

    void build(int n_pts, const double* lats, const double* lons, const double* cums) {
        n_segs = std::max(0, n_pts - 1);
        double lat_sum = 0.0;
        for (int i = 0; i < n_pts; ++i) lat_sum += lats[i];
        double mean_lat = (n_pts > 0) ? (lat_sum / n_pts) : 0.0;
        kx = METERS_PER_DEG_LON_EQ * std::cos(mean_lat * PI / 180.0);
        ky = METERS_PER_DEG_LAT;
        total_len = (n_pts > 0) ? cums[n_pts - 1] : 0.0;

        x1.resize(n_segs); y1.resize(n_segs); dx.resize(n_segs); dy.resize(n_segs);
        safe_lens_sq.resize(n_segs); seg_lens.resize(n_segs); cum_starts.resize(n_segs);
        unit_dx.resize(n_segs); unit_dy.resize(n_segs);
        min_x.resize(n_segs); max_x.resize(n_segs); min_y.resize(n_segs); max_y.resize(n_segs);

        for (int i = 0; i < n_segs; ++i) {
            double sx1 = lons[i] * kx, sy1 = lats[i] * ky;
            double sx2 = lons[i + 1] * kx, sy2 = lats[i + 1] * ky;
            double sdx = sx2 - sx1, sdy = sy2 - sy1;
            double lsq = sdx * sdx + sdy * sdy;
            double slen = std::sqrt(lsq);
            bool valid = slen > 1e-9;
            double safe_l = valid ? slen : 1.0;

            x1[i] = sx1; y1[i] = sy1; dx[i] = sdx; dy[i] = sdy;
            safe_lens_sq[i] = std::max(lsq, 1e-6);
            seg_lens[i] = slen; cum_starts[i] = cums[i];
            unit_dx[i] = valid ? (sdx / safe_l) : 0.0;
            unit_dy[i] = valid ? (sdy / safe_l) : 0.0;
            min_x[i] = std::min(sx1, sx2); max_x[i] = std::max(sx1, sx2);
            min_y[i] = std::min(sy1, sy2); max_y[i] = std::max(sy1, sy2);
        }
    }

    std::vector<Match> candidates(double epoch, double lat, double lng, int index, int max_cands) const {
        double px = lng * kx, py = lat * ky;
        double pad = MAX_CORRIDOR_CT_M + 1e-4;
        std::vector<CandRaw> raw;
        raw.reserve(16);
        for (int i = 0; i < n_segs; ++i) {
            if (px < min_x[i] - pad || px > max_x[i] + pad || py < min_y[i] - pad || py > max_y[i] + pad) {
                continue;
            }
            double u = ((px - x1[i]) * dx[i] + (py - y1[i]) * dy[i]) / safe_lens_sq[i];
            if (u < 0.0) u = 0.0; else if (u > 1.0) u = 1.0;
            double d = std::hypot(px - x1[i] - u * dx[i], py - y1[i] - u * dy[i]);
            if (d <= MAX_CORRIDOR_CT_M) {
                raw.push_back({d, cum_starts[i] + u * seg_lens[i], i});
            }
        }
        if (raw.empty()) return {};
        std::stable_sort(raw.begin(), raw.end(), [](const CandRaw& a, const CandRaw& b) { return a.d < b.d; });
        std::vector<Match> out;
        out.reserve(max_cands);
        for (const auto& c : raw) {
            bool dup = false;
            for (const auto& p : out) {
                if (std::abs(c.s - p.s) < 10.0) { dup = true; break; }
            }
            if (dup) continue;
            out.push_back({epoch, round1(c.s), round1(c.d), c.seg, index});
            if (static_cast<int>(out.size()) >= max_cands) break;
        }
        return out;
    }
};

class RouteHMM {
public:
    const ShapeModel& shape;
    double sigma = 15.0;
    int max_candidates = 10;
    int window = 24;
    double horizon = 300.0;
    bool allow_terminal_wrap = true;
    double backward_window_sec = 60.0;
    double backward_switch_margin = 2.0;

    std::vector<Match> states;
    std::vector<double> scores;
    std::vector<std::vector<Match>> paths;
    std::vector<Match> best_path;
    bool has_last = false;
    double last_epoch = 0.0, last_lat = 0.0, last_lng = 0.0;
    bool awaiting_direction = false;
    double blocked_at = 0.0;
    bool has_reversal = false;
    double rev_epoch = 0.0, rev_s = 0.0, rev_lat = 0.0, rev_lng = 0.0;
    int rev_count = 0;

    RouteHMM(const ShapeModel& sh, double h, bool wrap, double bw_win, double bw_margin)
        : shape(sh), horizon(h), allow_terminal_wrap(wrap),
          backward_window_sec(bw_win), backward_switch_margin(bw_margin) {}

    bool update(double epoch, double lat, double lng, int index, Match& out_m) {
        if (awaiting_direction) {
            if (epoch - blocked_at <= STALE_DT_MAX_SEC) return false;
            awaiting_direction = false;
        }
        if (has_last && epoch <= last_epoch) {
            if (best_path.empty()) return false;
            out_m = best_path.back();
            return true;
        }
        auto new_cands = shape.candidates(epoch, lat, lng, index, max_candidates);
        if (new_cands.empty()) return false;

        double dt = has_last ? (epoch - last_epoch) : 0.0;
        double move = has_last ? std::hypot((lng - last_lng) * shape.kx, (lat - last_lat) * shape.ky) : 0.0;
        int n_new = static_cast<int>(new_cands.size());
        std::vector<double> emission(n_new, 0.0);
        if (!(has_last && lat == last_lat && lng == last_lng)) {
            for (int i = 0; i < n_new; ++i) {
                double r = new_cands[i].cross_track / sigma;
                emission[i] = -0.5 * r * r;
            }
        }
        if (has_last && dt <= 30.0 && move >= sigma) {
            double mx = (lng - last_lng) * shape.kx, my = (lat - last_lat) * shape.ky;
            for (int i = 0; i < n_new; ++i) {
                int seg = new_cands[i].segment;
                emission[i] -= 2.0 * (1.0 - (mx * shape.unit_dx[seg] + my * shape.unit_dy[seg]) / move);
            }
        }

        std::vector<double> new_scores(n_new, -INF);
        std::vector<std::vector<Match>> new_paths(n_new);
        bool was_init = false;
        if (states.empty() || dt > STALE_DT_MAX_SEC) {
            new_scores = emission;
            for (int i = 0; i < n_new; ++i) new_paths[i] = {new_cands[i]};
            was_init = true;
        } else {
            int n_old = static_cast<int>(states.size());
            bool any_valid = false;
            for (int j = 0; j < n_new; ++j) {
                const auto& b = new_cands[j];
                double best_opt = -INF;
                int best_p = -1;
                bool best_wrapped = false;
                for (int i = 0; i < n_old; ++i) {
                    const auto& a = states[i];
                    double ds = b.s - a.s;
                    double recent_floor = a.s;
                    if (backward_window_sec > 0.0 && !paths[i].empty()) {
                        double max_r = -INF;
                        bool found_r = false;
                        for (int k = static_cast<int>(paths[i].size()) - 1; k >= 0; --k) {
                            if (epoch - paths[i][k].epoch <= backward_window_sec) {
                                if (!found_r || paths[i][k].s > max_r) { max_r = paths[i][k].s; found_r = true; }
                            } else {
                                break;
                            }
                        }
                        if (found_r) recent_floor = max_r;
                    }
                    bool terminal = (allow_terminal_wrap && shape.total_len > 1000.0 &&
                                     a.s >= shape.total_len - TERMINAL_RESET_ZONE_M &&
                                     b.s <= TERMINAL_RESET_ZONE_M && b.s < a.s - MAX_BACKWARD_JITTER_M);
                    double dist = 0.0, pen = 0.0;
                    if (terminal) {
                        dist = shape.total_len - a.s + b.s;
                        pen = 4.0;
                    } else if (ds >= -MAX_BACKWARD_JITTER_M && b.s >= recent_floor - MAX_BACKWARD_JITTER_M) {
                        dist = std::max(0.0, ds);
                        pen = std::max(0.0, -ds) / sigma;
                    } else {
                        continue;
                    }
                    if (dist > dt * FRENET_MAX_SPEED_MPS + 3.0 * sigma) continue;
                    double opt = scores[i] - std::abs(dist - move) / sigma - pen;
                    if (opt > best_opt) { best_opt = opt; best_p = i; best_wrapped = terminal; }
                }
                if (best_p != -1 && std::isfinite(best_opt)) {
                    any_valid = true;
                    new_scores[j] = best_opt + emission[j];
                    if (best_wrapped) {
                        new_paths[j] = {b};
                    } else {
                        const auto& pp = paths[best_p];
                        int keep = std::min(static_cast<int>(pp.size()), window - 1);
                        new_paths[j].assign(pp.end() - keep, pp.end());
                        new_paths[j].push_back(b);
                        while (new_paths[j].size() > 2 && epoch - new_paths[j].front().epoch > horizon) {
                            new_paths[j].erase(new_paths[j].begin());
                        }
                    }
                }
            }
            if (!any_valid) {
                const auto& prior = best_path.back();
                bool near_term = std::min(prior.s, shape.total_len - prior.s) <= TERMINAL_RESET_ZONE_M;
                const auto* nearest = &new_cands[0];
                for (int k = 1; k < n_new; ++k) if (new_cands[k].cross_track < nearest->cross_track) nearest = &new_cands[k];
                if (near_term && nearest->s < prior.s - MAX_BACKWARD_JITTER_M && move >= 8.0) {
                    double mprev = has_reversal ? std::hypot((lng - rev_lng) * shape.kx, (lat - rev_lat) * shape.ky) : 0.0;
                    int cnt = 1;
                    if (has_reversal && epoch > rev_epoch && nearest->s <= rev_s + MAX_BACKWARD_JITTER_M && mprev >= 8.0) cnt = rev_count + 1;
                    else if (has_reversal) cnt = rev_count;
                    if (!has_reversal || mprev >= 8.0) {
                        has_reversal = true; rev_epoch = epoch; rev_s = nearest->s; rev_count = cnt; rev_lat = lat; rev_lng = lng;
                    }
                    if (cnt >= 2) {
                        states.clear(); scores.clear(); paths.clear(); best_path.clear(); has_last = false;
                        awaiting_direction = true; blocked_at = epoch;
                    }
                } else {
                    has_reversal = false;
                }
                return false;
            }
            has_reversal = false;
        }

        double prev_s = !best_path.empty() ? best_path.back().s : -1.0;
        bool had_prev = !best_path.empty();

        states.clear(); scores.clear(); paths.clear();
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
            if (scores[j] > best_sc) { best_sc = scores[j]; best_idx = j; }
        }
        if (backward_switch_margin > 0.0 && had_prev && has_last && dt <= STALE_DT_MAX_SEC &&
            !was_init && paths[best_idx].size() > 1 && states[best_idx].s < prev_s - MAX_BACKWARD_JITTER_M) {
            int fwd_best = -1;
            double fwd_sc = -INF;
            for (int j = 0; j < static_cast<int>(states.size()); ++j) {
                if (states[j].s >= prev_s - MAX_BACKWARD_JITTER_M && scores[j] > fwd_sc) {
                    fwd_sc = scores[j]; fwd_best = j;
                }
            }
            if (fwd_best != -1 && (scores[best_idx] - fwd_sc) < backward_switch_margin) {
                best_idx = fwd_best;
            }
        }
        best_path = paths[best_idx];
        has_last = true; last_epoch = epoch; last_lat = lat; last_lng = lng;
        out_m = best_path.back();
        return true;
    }
};

struct JointState {
    int dir;
    Match m;
    double p;
};

class JointBidirectionalHMM {
public:
    const ShapeModel* shapes[2];
    double lengths[2];
    double sigma = 15.0;
    int max_per_dir = 6;
    int window = 32;
    double horizon = 300.0;
    double backward_window_sec = 60.0;
    double backward_switch_margin = 2.0;

    std::vector<JointState> states;
    std::vector<double> scores;
    std::vector<std::vector<JointState>> paths;
    std::vector<JointState> best_path;
    bool has_last = false;
    double last_epoch = 0.0, last_lat = 0.0, last_lng = 0.0;
    int consec_dead = 0;
    int obs_idx = 0;

    int post_gap_dir = -1;
    bool has_pg_s0[2] = {false, false};
    double pg_s0[2] = {0.0, 0.0};
    int pg_consec[2] = {0, 0};

    JointBidirectionalHMM(const ShapeModel* s_go, const ShapeModel* s_re) {
        shapes[0] = s_go; shapes[1] = s_re;
        lengths[0] = std::max(1.0, s_go->total_len);
        lengths[1] = std::max(1.0, s_re->total_len);
    }

    int update(double epoch, double lat, double lng, int& out_dir, double& out_s) {
        if (has_last && epoch <= last_epoch) {
            if (best_path.empty()) return 0;
            out_dir = best_path.back().dir; out_s = best_path.back().m.s;
            return 1;
        }
        int idx = obs_idx++;
        std::vector<JointState> new_cands;
        new_cands.reserve(12);
        for (int d = 0; d < 2; ++d) {
            for (const auto& m : shapes[d]->candidates(epoch, lat, lng, idx, max_per_dir)) {
                new_cands.push_back({d, m, m.s / lengths[d]});
            }
        }
        if (new_cands.empty()) return 0;

        double dt = has_last ? (epoch - last_epoch) : 0.0;
        double move = has_last ? std::hypot((lng - last_lng) * shapes[0]->kx, (lat - last_lat) * shapes[0]->ky) : 0.0;
        int n_new = static_cast<int>(new_cands.size());
        std::vector<double> emission(n_new, 0.0);
        if (!(has_last && lat == last_lat && lng == last_lng)) {
            for (int i = 0; i < n_new; ++i) {
                double r = new_cands[i].m.cross_track / sigma;
                emission[i] = -0.5 * r * r;
            }
        }
        if (has_last && dt <= 30.0 && move >= sigma) {
            double mx = (lng - last_lng) * shapes[0]->kx, my = (lat - last_lat) * shapes[0]->ky;
            for (int i = 0; i < n_new; ++i) {
                int d = new_cands[i].dir;
                int seg = new_cands[i].m.segment;
                emission[i] -= 2.0 * (1.0 - (mx * shapes[d]->unit_dx[seg] + my * shapes[d]->unit_dy[seg]) / move);
            }
        }

        bool in_terminal_layover = (
            has_last && dt > STALE_DT_MAX_SEC && dt <= MAX_BRIDGEABLE_GAP_SEC && !best_path.empty() &&
            (best_path.back().p >= 0.90 || best_path.back().m.s >= lengths[best_path.back().dir] - TERMINAL_RESET_ZONE_M)
        );

        bool was_init = false;
        std::vector<double> new_scores(n_new, -INF);
        std::vector<std::vector<JointState>> new_paths(n_new);
        if (states.empty() || (dt > STALE_DT_MAX_SEC && !in_terminal_layover)) {
            post_gap_dir = -1;
            if (!best_path.empty() && has_last && dt > STALE_DT_MAX_SEC && dt <= MAX_BRIDGEABLE_GAP_SEC &&
                best_path.back().p >= 0.15 && best_path.back().p <= 0.85) {
                post_gap_dir = best_path.back().dir;
            }
            for (int d = 0; d < 2; ++d) { has_pg_s0[d] = false; pg_consec[d] = 0; }
            if (post_gap_dir != -1) {
                for (const auto& c : new_cands) {
                    if (!has_pg_s0[c.dir]) { has_pg_s0[c.dir] = true; pg_s0[c.dir] = c.m.s; pg_consec[c.dir] = 1; }
                }
            }
            for (int i = 0; i < n_new; ++i) {
                double p = new_cands[i].p;
                double prior = (p <= 0.08) ? 1.5 : ((p >= 0.92) ? -1.5 : 0.0);
                new_scores[i] = emission[i] + prior;
                new_paths[i] = {new_cands[i]};
            }
            was_init = true; consec_dead = 0;
        } else {
            bool any_valid = false;
            for (int j = 0; j < n_new; ++j) {
                const auto& b = new_cands[j];
                double best_opt = -INF;
                int best_p = -1;
                bool best_crossed = false;
                for (int i = 0; i < static_cast<int>(states.size()); ++i) {
                    const auto& a = states[i];
                    double opt = -INF;
                    bool crossed = false;
                    if (a.dir == b.dir) {
                        double ds = b.m.s - a.m.s;
                        double recent_floor = a.m.s;
                        if (backward_window_sec > 0.0 && !paths[i].empty()) {
                            double max_r = -INF; bool found_r = false;
                            for (int k = static_cast<int>(paths[i].size()) - 1; k >= 0; --k) {
                                if (paths[i][k].dir == a.dir && epoch - paths[i][k].m.epoch <= backward_window_sec) {
                                    if (!found_r || paths[i][k].m.s > max_r) { max_r = paths[i][k].m.s; found_r = true; }
                                } else break;
                            }
                            if (found_r) recent_floor = max_r;
                        }
                        if (ds < -MAX_BACKWARD_JITTER_M || b.m.s < recent_floor - MAX_BACKWARD_JITTER_M) continue;
                        double dist = std::max(0.0, ds);
                        if (dist > dt * FRENET_MAX_SPEED_MPS + 3.0 * sigma) continue;
                        double pen = std::max(0.0, -ds) / sigma;
                        opt = scores[i] - std::abs(dist - move) / sigma - pen;
                    } else {
                        bool a_fin = (a.p >= 0.90) || (a.m.s >= lengths[a.dir] - TERMINAL_RESET_ZONE_M);
                        bool b_st = ((b.p <= 0.10) || (b.m.s <= TERMINAL_RESET_ZONE_M)) && (b.p <= 0.12);
                        bool dep = (b.m.s >= 40.0) || (move >= 10.0);
                        if (!(a_fin && b_st && dep && dt <= MAX_BRIDGEABLE_GAP_SEC)) continue;
                        double dist = std::max(0.0, lengths[a.dir] - a.m.s) + b.m.s;
                        if (dist > dt * FRENET_MAX_SPEED_MPS + 200.0) continue;
                        opt = scores[i] - 4.5 - std::abs(dist - move) / (2.0 * sigma);
                        crossed = true;
                    }
                    if (opt > best_opt) { best_opt = opt; best_p = i; best_crossed = crossed; }
                }
                if (best_p != -1 && std::isfinite(best_opt)) {
                    any_valid = true;
                    new_scores[j] = best_opt + emission[j];
                    if (best_crossed) {
                        new_paths[j] = {b};
                    } else {
                        const auto& pp = paths[best_p];
                        int keep = std::min(static_cast<int>(pp.size()), window - 1);
                        new_paths[j].assign(pp.end() - keep, pp.end());
                        new_paths[j].push_back(b);
                        while (new_paths[j].size() > 2 && epoch - new_paths[j].front().m.epoch > horizon) {
                            new_paths[j].erase(new_paths[j].begin());
                        }
                    }
                }
            }
            if (!any_valid) {
                consec_dead += 1;
                if (consec_dead >= 3) {
                    post_gap_dir = !best_path.empty() ? best_path.back().dir : -1;
                    for (int d = 0; d < 2; ++d) { has_pg_s0[d] = false; pg_consec[d] = 0; }
                    for (const auto& c : new_cands) {
                        if (!has_pg_s0[c.dir]) { has_pg_s0[c.dir] = true; pg_s0[c.dir] = c.m.s; pg_consec[c.dir] = 1; }
                    }
                    states = new_cands;
                    double mx_em = *std::max_element(emission.begin(), emission.end());
                    scores.resize(n_new); paths.resize(n_new);
                    int best_i = 0; double best_s = -INF;
                    for (int k = 0; k < n_new; ++k) {
                        scores[k] = emission[k] - mx_em; paths[k] = {new_cands[k]};
                        if (post_gap_dir == -1 || new_cands[k].dir == post_gap_dir) {
                            if (scores[k] > best_s) { best_s = scores[k]; best_i = k; }
                        }
                    }
                    if (!std::isfinite(best_s)) {
                        for (int k = 0; k < n_new; ++k) if (scores[k] > best_s) { best_s = scores[k]; best_i = k; }
                    }
                    best_path = paths[best_i];
                    has_last = true; last_epoch = epoch; last_lat = lat; last_lng = lng;
                    consec_dead = 0;
                    out_dir = best_path.back().dir; out_s = best_path.back().m.s;
                    return 1;
                }
                return 0;
            }
            consec_dead = 0;
        }

        double max_sc = -INF;
        states.clear(); scores.clear(); paths.clear();
        for (int j = 0; j < n_new; ++j) {
            if (std::isfinite(new_scores[j])) {
                states.push_back(new_cands[j]);
                scores.push_back(new_scores[j]);
                paths.push_back(std::move(new_paths[j]));
                if (new_scores[j] > max_sc) max_sc = new_scores[j];
            }
        }
        int best = 0; double best_sc = -INF;
        for (int j = 0; j < static_cast<int>(scores.size()); ++j) {
            scores[j] -= max_sc;
            if (scores[j] > best_sc) { best_sc = scores[j]; best = j; }
        }

        if (post_gap_dir != -1) {
            int best_d_idx[2] = {-1, -1};
            double best_d_sc[2] = {-INF, -INF};
            for (int j = 0; j < static_cast<int>(states.size()); ++j) {
                int d = states[j].dir;
                if (scores[j] > best_d_sc[d]) { best_d_sc[d] = scores[j]; best_d_idx[d] = j; }
            }
            for (int d = 0; d < 2; ++d) {
                if (best_d_idx[d] != -1) {
                    if (!has_pg_s0[d]) { has_pg_s0[d] = true; pg_s0[d] = states[best_d_idx[d]].m.s; pg_consec[d] = 1; }
                    else if (!was_init) pg_consec[d] += 1;
                } else { has_pg_s0[d] = false; pg_consec[d] = 0; }
            }
            int opp = 1 - post_gap_dir;
            double opp_adv = (best_d_idx[opp] != -1 && has_pg_s0[opp]) ? (states[best_d_idx[opp]].m.s - pg_s0[opp]) : 0.0;
            double cur_adv = (best_d_idx[post_gap_dir] != -1 && has_pg_s0[post_gap_dir]) ? (states[best_d_idx[post_gap_dir]].m.s - pg_s0[post_gap_dir]) : 0.0;
            if (pg_consec[opp] >= 2 && opp_adv >= 90.0) post_gap_dir = -1;
            else if (cur_adv >= 90.0) post_gap_dir = -1;
            else if (best_d_idx[post_gap_dir] != -1) best = best_d_idx[post_gap_dir];
        }

        if (!best_path.empty() && has_last && !was_init) {
            const auto& pm = best_path.back();
            const auto& cm = states[best];
            if (cm.dir == pm.dir && paths[best].size() > 1 && cm.m.s < pm.m.s - MAX_BACKWARD_JITTER_M) {
                int fwd_b = -1; double fwd_s = -INF;
                for (int j = 0; j < static_cast<int>(states.size()); ++j) {
                    if (states[j].dir == pm.dir && states[j].m.s >= pm.m.s - MAX_BACKWARD_JITTER_M && scores[j] > fwd_s) {
                        fwd_s = scores[j]; fwd_b = j;
                    }
                }
                if (fwd_b != -1 && (scores[best] - fwd_s) < backward_switch_margin) best = fwd_b;
            }
        }

        best_path = paths[best];
        has_last = true; last_epoch = epoch; last_lat = lat; last_lng = lng;
        out_dir = best_path.back().dir; out_s = best_path.back().m.s;
        return 1;
    }
};

}  // namespace bus_native

extern "C" {

BUS_API void cpp_project_route_full(
    int n_go, const double* lat_go, const double* lon_go, const double* cum_go,
    int n_re, const double* lat_re, const double* lon_re, const double* cum_re,
    int n_st_dir, const int32_t* st_dir_ids, const int32_t* st_dir_vals,
    int n_pings,
    const int64_t* ping_ids, const int32_t* vehicle_ids, const double* epochs,
    const int32_t* raw_dirs, const double* lats, const double* lons, const int32_t* curr_st_ids,
    int32_t* out_count,
    int32_t* out_orig_idx, int32_t* out_dir, double* out_s, double* out_ct,
    int32_t* out_has_spd, double* out_spd
) {
    using namespace bus_native;
    (void)ping_ids;
    std::fesetround(FE_TONEAREST);
    ShapeModel shapes[2];
    bool has_shape[2] = {n_go >= 2, n_re >= 2};
    if (has_shape[0]) shapes[0].build(n_go, lat_go, lon_go, cum_go);
    if (has_shape[1]) shapes[1].build(n_re, lat_re, lon_re, cum_re);

    std::unordered_map<int32_t, int32_t> st_map;
    st_map.reserve(n_st_dir * 2 + 1);
    for (int i = 0; i < n_st_dir; ++i) st_map[st_dir_ids[i]] = st_dir_vals[i];

    int write_pos = 0;
    int i = 0;
    while (i < n_pings) {
        int32_t vid = vehicle_ids[i];
        int j = i;
        while (j < n_pings && vehicle_ids[j] == vid) ++j;

        struct Ev { int orig_idx; double ep; int dir; double lat; double lon; };
        std::vector<Ev> clean;
        clean.reserve(j - i);
        double last_ep = -INF;
        bool has_ep = false;
        for (int k = i; k < j; ++k) {
            double ep = epochs[k];
            if (has_ep && ep == last_ep) continue;
            has_ep = true; last_ep = ep;
            int dir = -1;
            int32_t st_id = curr_st_ids[k];
            if (st_id != 0) {
                auto it = st_map.find(st_id);
                if (it != st_map.end()) dir = it->second;
            }
            if (dir == -1 && (raw_dirs[k] == 0 || raw_dirs[k] == 1)) dir = raw_dirs[k];
            if (dir != 0 && dir != 1) continue;
            clean.push_back({k, ep, dir, lats[k], lons[k]});
        }

        struct AccEv { int orig_idx; double ep; int dir; double s; double ct; };
        std::vector<AccEv> accepted;
        accepted.reserve(clean.size());
        int r_beg = 0;
        while (r_beg < static_cast<int>(clean.size())) {
            int d = clean[r_beg].dir;
            int r_end = r_beg + 1;
            while (r_end < static_cast<int>(clean.size()) && clean[r_end].dir == d) ++r_end;
            if (has_shape[d]) {
                RouteHMM hmm(shapes[d], 300.0, true, 60.0, 2.0);
                double prev_run_ep = -INF;
                bool has_prev_run = false;
                for (int r = r_beg; r < r_end; ++r) {
                    if (has_prev_run && clean[r].ep <= prev_run_ep) continue;
                    prev_run_ep = clean[r].ep; has_prev_run = true;
                    Match m{};
                    if (hmm.update(clean[r].ep, clean[r].lat, clean[r].lon, r - r_beg, m)) {
                        if (m.cross_track <= MAX_CORRIDOR_CT_M) {
                            accepted.push_back({clean[r].orig_idx, clean[r].ep, d, m.s, m.cross_track});
                        }
                    }
                }
            }
            r_beg = r_end;
        }

        if (!accepted.empty()) {
            std::stable_sort(accepted.begin(), accepted.end(), [](const AccEv& a, const AccEv& b) {
                return a.ep < b.ep;
            });
            for (int a = 0; a < static_cast<int>(accepted.size()); ++a) {
                const auto& cur = accepted[a];
                out_orig_idx[write_pos] = cur.orig_idx;
                out_dir[write_pos] = cur.dir;
                out_s[write_pos] = cur.s;
                out_ct[write_pos] = cur.ct;
                out_has_spd[write_pos] = 0;
                out_spd[write_pos] = 0.0;
                if (a > 0) {
                    const auto& prev = accepted[a - 1];
                    double dt = cur.ep - prev.ep;
                    double ds = round1(cur.s - prev.s);
                    if (dt > 0.0 && dt <= STALE_DT_MAX_SEC && cur.dir == prev.dir && ds >= -MAX_BACKWARD_JITTER_M) {
                        double cspd = round2(std::max(0.0, ds) / dt * 3.6);
                        if (cspd <= GPS_MAX_SPEED_KMPH) {
                            out_has_spd[write_pos] = 1;
                            out_spd[write_pos] = cspd;
                        }
                    }
                }
                ++write_pos;
            }
        }
        i = j;
    }
    *out_count = write_pos;
}

BUS_API void cpp_run_joint_bidirectional_hmm(
    int n_go, const double* lat_go, const double* lon_go, const double* cum_go,
    int n_re, const double* lat_re, const double* lon_re, const double* cum_re,
    int n_runs, const int64_t* run_offsets,
    const double* epochs, const double* lats, const double* lons,
    int32_t* out_valid, int32_t* out_dir, double* out_s
) {
    using namespace bus_native;
    std::fesetround(FE_TONEAREST);
    ShapeModel sh_go, sh_re;
    sh_go.build(n_go, lat_go, lon_go, cum_go);
    sh_re.build(n_re, lat_re, lon_re, cum_re);

    for (int r = 0; r < n_runs; ++r) {
        JointBidirectionalHMM hmm(&sh_go, &sh_re);
        for (int64_t i = run_offsets[r]; i < run_offsets[r + 1]; ++i) {
            int d = 0; double s = 0.0;
            if (hmm.update(epochs[i], lats[i], lons[i], d, s)) {
                out_valid[i] = 1; out_dir[i] = d; out_s[i] = s;
            } else {
                out_valid[i] = 0; out_dir[i] = -1; out_s[i] = 0.0;
            }
        }
    }
}

}  // extern "C"
