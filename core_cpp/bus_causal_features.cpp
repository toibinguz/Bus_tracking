#include "bus_native_common.hpp"

#include <algorithm>
#include <cstring>
#include <unordered_map>
#include <utility>
#include <vector>

namespace bus_native {

struct PathPoint {
    double epoch;
    double s;
};

struct VehReplayState {
    std::vector<PathPoint> best_path;
    int64_t journey = 0;
    double started = 0.0;
    bool has_started = false;
    double last_epoch = -INF;
    double last_s = 0.0;
    int32_t last_dir = -1;
    double prev_s_obs = 0.0;
    double prev_ep_obs = -INF;
    int64_t prev_journey = -1;
};

struct CrossingInfo {
    double epoch;
    double before_epoch;
    double after_epoch;
    double known_at;
};

struct IncidentIntervalCpp {
    double s_min;
    double s_max;
    double delay_sec;
    double crawled_epoch;
    double expires_epoch;
};

struct SpeedRes {
    bool valid = false;
    double kmh = 0.0;
    double seconds = 0.0;
    double start_s = 0.0;
    double end_s = 0.0;
};

struct RawExample {
    float feats[40];
    int32_t veh_idx;
    int64_t journey;
    int64_t target_idx;
    int32_t dir_int;
    double as_of;
    double hist_sec;
};

struct CausalFeatureBuffer {
    int32_t error_code = 0;  // 0=ok, 1=out_of_order_or_overlap
    int64_t count_observations = 0;
    int64_t count_matched = 0;
    int64_t count_forecast_attempts = 0;
    int64_t count_feature_rejected = 0;
    int64_t count_no_crossing = 0;
    int64_t count_invalid_eta = 0;
    int64_t count_label_crosses_split = 0;
    int64_t count_labeled_train = 0;
    int64_t count_labeled_validation = 0;
    int64_t count_labeled_test = 0;

    std::vector<float> features;  // rows * 40 row-major
    std::vector<int32_t> veh_idx;
    std::vector<int64_t> journey;
    std::vector<int64_t> target_order;
    std::vector<int32_t> split;  // 0=train, 1=validation, 2=test
    std::vector<double> as_of;
    std::vector<double> eta_seconds;
    std::vector<double> bracket_before;
    std::vector<double> bracket_after;
    std::vector<double> crossing_epoch;
    std::vector<double> history_seconds;
};

struct SlotPrefix {
    std::vector<int> pref_none, pref_t0, pref_t3;
    std::vector<double> pref_p50, pref_p10, pref_p90, pref_mean, pref_var;
};

static SpeedRes compute_speed(const VehReplayState& st, double seconds) {
    SpeedRes res;
    const auto& pts = st.best_path;
    int n = static_cast<int>(pts.size());
    if (n < 2 || !st.has_started) return res;
    const auto& end_pt = pts.back();
    int start_idx = 0;
    if (end_pt.epoch - st.started < seconds) {
        start_idx = 0;
    } else {
        double best_diff = INF;
        for (int i = 0; i < n - 1; ++i) {
            double diff = std::abs(end_pt.epoch - pts[i].epoch - seconds);
            if (diff < best_diff) {
                best_diff = diff;
                start_idx = i;
            }
        }
        if (std::abs(end_pt.epoch - pts[start_idx].epoch - seconds) > SPEED_WINDOW_TOLERANCE_SEC) {
            return res;
        }
    }
    const auto& start_pt = pts[start_idx];
    double duration = end_pt.epoch - start_pt.epoch;
    if (duration < MIN_SPEED_WINDOW_SEC) return res;

    double min_s = start_pt.s, max_s = start_pt.s;
    for (int i = start_idx + 1; i < n; ++i) {
        if (pts[i].epoch - pts[i - 1].epoch > SPEED_MAX_GAP_SEC) return res;
        if (pts[i].s < min_s) min_s = pts[i].s;
        if (pts[i].s > max_s) max_s = pts[i].s;
    }
    double distance = end_pt.s - start_pt.s;
    if (std::abs(distance) <= STATIONARY_TOLERANCE_M && (max_s - min_s) <= STATIONARY_TOLERANCE_M) {
        distance = 0.0;
    }
    if (distance < 0.0) return res;
    double kmh = 3.6 * distance / duration;
    if (kmh > GPS_MAX_SPEED_KMPH) return res;

    res.valid = true;
    res.kmh = kmh;
    res.seconds = duration;
    res.start_s = start_pt.s;
    res.end_s = end_pt.s;
    return res;
}

}  // namespace bus_native

extern "C" {

BUS_API void* cpp_extract_route_causal_features(
    int32_t route_id_idx,
    // Per-direction static & baseline metadata (index 0=go, 1=re)
    const double* route_len_m_2,
    const double* route_base_speed_2,
    const double* route_spacing_2,
    const int32_t* n_stations_2,
    const int64_t* station_orders_flat,  // n_stations_2[0] + n_stations_2[1]
    const double* station_s_flat,
    const uint8_t* bm_valid_flat,        // 51 * n_seg[0] + 51 * n_seg[1]
    const double* bm_p10_flat,
    const double* bm_p50_flat,
    const double* bm_p90_flat,
    const double* bm_mean_flat,
    const double* bm_std_flat,
    const int32_t* bm_tier_flat,
    // TomTom intervals pre-sorted by crawled_epoch per direction
    const int32_t* n_incidents_2,
    const double* inc_s_min_flat,
    const double* inc_s_max_flat,
    const double* inc_delay_flat,
    const double* inc_crawled_flat,
    const double* inc_expires_flat,
    // Silver observations for the full route, pre-sorted by (epoch, dir_int, veh_idx)
    int32_t n_vehicles,
    int32_t n_obs,
    const double* obs_epoch,
    const int32_t* obs_dir,
    const int32_t* obs_veh_idx,
    const double* obs_s_bus,
    // Cutoffs & cadence
    double baseline_cutoff_epoch,
    double validation_epoch,
    double test_epoch,
    double cadence_sec,
    int32_t* out_rows
) {
    using namespace bus_native;

    auto* buf = new CausalFeatureBuffer();
    *out_rows = 0;

    if (route_id_idx < 0 || n_obs <= 0 || n_vehicles <= 0) {
        return buf;
    }

    int st_off[2] = {0, n_stations_2[0]};
    int n_seg[2] = {std::max(0, n_stations_2[0] - 1), std::max(0, n_stations_2[1] - 1)};
    int bm_dir_off[2] = {0, 51 * n_seg[0]};
    int inc_off[2] = {0, n_incidents_2[0]};

    bool dir_valid[2] = {false, false};
    std::vector<SlotPrefix> slot_pref[2];
    for (int d = 0; d < 2; ++d) {
        if (n_stations_2[d] < 2 || route_len_m_2[d] <= 0.0) continue;
        bool inc_ok = true;
        const double* ss = station_s_flat + st_off[d];
        for (int i = 1; i < n_stations_2[d]; ++i) {
            if (ss[i] <= ss[i - 1]) { inc_ok = false; break; }
        }
        if (!inc_ok) continue;
        dir_valid[d] = true;

        slot_pref[d].resize(51);
        for (int sl = 0; sl < 51; ++sl) {
            auto& sp = slot_pref[d][sl];
            int ns = n_seg[d];
            sp.pref_none.assign(ns + 1, 0);
            sp.pref_t0.assign(ns + 1, 0);
            sp.pref_t3.assign(ns + 1, 0);
            sp.pref_p50.assign(ns + 1, 0.0);
            sp.pref_p10.assign(ns + 1, 0.0);
            sp.pref_p90.assign(ns + 1, 0.0);
            sp.pref_mean.assign(ns + 1, 0.0);
            sp.pref_var.assign(ns + 1, 0.0);
            int base = bm_dir_off[d] + sl * ns;
            for (int k = 0; k < ns; ++k) {
                int idx = base + k;
                int nn = sp.pref_none[k], nt0 = sp.pref_t0[k], nt3 = sp.pref_t3[k];
                double sp50 = sp.pref_p50[k], sp10 = sp.pref_p10[k], sp90 = sp.pref_p90[k];
                double smean = sp.pref_mean[k], svar = sp.pref_var[k];
                if (!bm_valid_flat[idx]) {
                    nn += 1;
                } else {
                    if (bm_tier_flat[idx] == 0) nt0 += 1;
                    else if (bm_tier_flat[idx] == 3) nt3 += 1;
                    sp10 += bm_p10_flat[idx];
                    sp50 += bm_p50_flat[idx];
                    sp90 += bm_p90_flat[idx];
                    smean += bm_mean_flat[idx];
                    svar += bm_std_flat[idx] * bm_std_flat[idx];
                }
                sp.pref_none[k + 1] = nn;
                sp.pref_t0[k + 1] = nt0;
                sp.pref_t3[k + 1] = nt3;
                sp.pref_p50[k + 1] = sp50;
                sp.pref_p10[k + 1] = sp10;
                sp.pref_p90[k + 1] = sp90;
                sp.pref_mean[k + 1] = smean;
                sp.pref_var[k + 1] = svar;
            }
        }
    }

    if (!dir_valid[0] && !dir_valid[1]) {
        return buf;
    }

    std::vector<VehReplayState> v_states(n_vehicles);
    std::vector<double> fleet_member_epoch[2] = {
        std::vector<double>(n_vehicles, -INF),
        std::vector<double>(n_vehicles, -INF),
    };
    std::vector<int32_t> active_veh_ids;
    active_veh_ids.reserve(64);

    // Per (journey, station_idx) first crossing
    std::unordered_map<int64_t, CrossingInfo> crossings;
    crossings.reserve(static_cast<size_t>(n_obs / 4 + 64));

    std::vector<RawExample> examples;
    examples.reserve(static_cast<size_t>(n_obs));

    std::vector<IncidentIntervalCpp> active_inc[2];
    int inc_ptr[2] = {0, 0};

    int64_t journey_seq = 0;
    double next_forecast[2] = {0.0, 0.0};
    double last_time = -INF;

    int pos = 0;
    while (pos < n_obs) {
        double now = obs_epoch[pos];
        int32_t d = obs_dir[pos];
        if (now < baseline_cutoff_epoch || now < last_time) {
            buf->error_code = 1;
            return buf;
        }
        last_time = now;

        int batch_end = pos + 1;
        while (batch_end < n_obs && obs_epoch[batch_end] == now && obs_dir[batch_end] == d) ++batch_end;

        if (d != 0 && d != 1) {
            pos = batch_end;
            continue;
        }

        // Update fleet snapshot for (route, d) (even if shape/corridor missing, matches Python replay_silver)
        active_veh_ids.clear();
        for (int b = pos; b < batch_end; ++b) {
            int32_t v = obs_veh_idx[b];
            if (v >= 0 && v < n_vehicles) fleet_member_epoch[d][v] = now;
        }
        for (int32_t v = 0; v < n_vehicles; ++v) {
            if (fleet_member_epoch[d][v] > -INF && (now - fleet_member_epoch[d][v]) <= MAX_POSITION_AGE_SEC) {
                active_veh_ids.push_back(v);
            }
        }

        const int32_t n_st = n_stations_2[d];
        const int64_t* st_orders = station_orders_flat + st_off[d];
        const double* st_s = station_s_flat + st_off[d];
        const double rlen = route_len_m_2[d];

        for (int b = pos; b < batch_end; ++b) {
            int32_t v = obs_veh_idx[b];
            double s = obs_s_bus[b];
            buf->count_observations += 1;
            if (v < 0 || v >= n_vehicles || !std::isfinite(s) || rlen <= 0.0) continue;

            auto& vs = v_states[v];
            if (vs.last_epoch > -INF && now <= vs.last_epoch) continue;

            bool is_new = (vs.last_epoch <= -INF);
            bool dir_changed = (!is_new && vs.last_dir != d);
            bool reset_obs = dir_changed;
            if (!is_new && !dir_changed) {
                double dt = now - vs.last_epoch;
                bool terminal_wrap = (
                    rlen > 1000.0 &&
                    vs.last_s >= rlen - TERMINAL_RESET_ZONE_M &&
                    s <= TERMINAL_RESET_ZONE_M &&
                    s < vs.last_s - MAX_BACKWARD_JITTER_M
                );
                if (dt > STALE_DT_MAX_SEC || terminal_wrap || s < vs.last_s - MAX_BACKWARD_JITTER_M) {
                    reset_obs = true;
                }
            }
            if (is_new || reset_obs) {
                journey_seq += 1;
                vs.journey = journey_seq;
                vs.best_path.clear();
                vs.best_path.push_back({now, s});
                vs.started = now;
                vs.has_started = true;
            } else {
                vs.best_path.push_back({now, s});
                if (static_cast<int>(vs.best_path.size()) > 128) {
                    vs.best_path.erase(vs.best_path.begin(), vs.best_path.end() - 128);
                }
                while (vs.best_path.size() > 2 && now - vs.best_path.front().epoch > 360.0) {
                    vs.best_path.erase(vs.best_path.begin());
                }
            }
            vs.last_epoch = now;
            vs.last_s = s;
            vs.last_dir = d;
            buf->count_matched += 1;

            if (vs.prev_journey == vs.journey && n_st > 0) {
                double dt_c = now - vs.prev_ep_obs;
                double ds_c = s - vs.prev_s_obs;
                if (dt_c > 0.0 && dt_c <= MAX_LABEL_BRACKET_SEC && ds_c > 0.0 && ds_c <= MAX_LABEL_BRACKET_M) {
                    int k_lo = static_cast<int>(std::upper_bound(st_s, st_s + n_st, vs.prev_s_obs) - st_s);
                    int k_hi = static_cast<int>(std::upper_bound(st_s, st_s + n_st, s) - st_s);
                    for (int k_st = k_lo; k_st < k_hi; ++k_st) {
                        int64_t ckey = (vs.journey << 16) | static_cast<int64_t>(k_st);
                        if (crossings.find(ckey) == crossings.end()) {
                            double eta_cross = vs.prev_ep_obs + dt_c * (st_s[k_st] - vs.prev_s_obs) / ds_c;
                            crossings.emplace(ckey, CrossingInfo{eta_cross, vs.prev_ep_obs, now, now});
                        }
                    }
                }
            }
            vs.prev_journey = vs.journey;
            vs.prev_ep_obs = now;
            vs.prev_s_obs = s;
        }

        pos = batch_end;
        if (now < next_forecast[d]) continue;
        next_forecast[d] = now + cadence_sec;

        if (!dir_valid[d]) continue;

        // Advance TomTom active incident pointer for direction d
        int n_inc_d = n_incidents_2[d];
        int ioff = inc_off[d];
        while (inc_ptr[d] < n_inc_d && inc_crawled_flat[ioff + inc_ptr[d]] <= now) {
            int idx_i = ioff + inc_ptr[d];
            if (inc_delay_flat[idx_i] > 0.0 && inc_expires_flat[idx_i] >= now) {
                active_inc[d].push_back({
                    inc_s_min_flat[idx_i], inc_s_max_flat[idx_i], inc_delay_flat[idx_i],
                    inc_crawled_flat[idx_i], inc_expires_flat[idx_i],
                });
            }
            ++inc_ptr[d];
        }
        if (!active_inc[d].empty()) {
            size_t keep_w = 0;
            for (size_t k = 0; k < active_inc[d].size(); ++k) {
                if (active_inc[d][k].expires_epoch >= now) {
                    active_inc[d][keep_w++] = active_inc[d][k];
                }
            }
            active_inc[d].resize(keep_w);
        }

        int day_t = 0, weekday = 0, hr_slot = 5, minute = 0;
        hanoi_calendar(now, day_t, weekday, hr_slot, minute);
        int64_t t_local = static_cast<int64_t>(std::floor(now)) + 25200LL;
        int64_t sec_day = t_local - hanoi_day_num(now) * 86400LL;
        int raw_hr = static_cast<int>(sec_day / 3600LL);
        double angle = 2.0 * PI * (raw_hr + minute / 60.0) / 24.0;
        float sin_a = static_cast<float>(std::sin(angle));
        float cos_a = static_cast<float>(std::cos(angle));

        int slot_idx = day_t * 17 + (hr_slot - 5);
        int bm_base = bm_dir_off[d] + slot_idx * n_seg[d];
        const auto& sp = slot_pref[d][slot_idx];

        struct FleetUnit { int32_t veh_idx; double epoch; double s; };
        std::vector<FleetUnit> valid_fleet;
        valid_fleet.reserve(active_veh_ids.size());
        for (int32_t v : active_veh_ids) {
            const auto& vs = v_states[v];
            if (vs.last_epoch > -INF && vs.last_dir == d && vs.last_epoch <= now &&
                (now - vs.last_epoch) <= MAX_POSITION_AGE_SEC) {
                valid_fleet.push_back({v, vs.last_epoch, vs.last_s});
            }
        }
        int n_fleet_valid = static_cast<int>(valid_fleet.size());

        for (int32_t v : active_veh_ids) {
            buf->count_forecast_attempts += n_st;
            const auto& vs = v_states[v];
            if (vs.last_epoch <= -INF || vs.last_dir != d || vs.last_epoch > now ||
                (now - vs.last_epoch) > MAX_POSITION_AGE_SEC) {
                buf->count_feature_rejected += n_st;
                continue;
            }
            double s = vs.last_s;
            int current = static_cast<int>(std::upper_bound(st_s, st_s + n_st, s) - st_s) - 1;
            if (current < 0 || current >= n_seg[d] || !bm_valid_flat[bm_base + current]) {
                buf->count_feature_rejected += n_st;
                continue;
            }

            SpeedRes sp3 = compute_speed(vs, 180.0);
            SpeedRes sp5 = compute_speed(vs, 300.0);
            float f_sp3 = sp3.valid ? static_cast<float>(sp3.kmh) : F_NAN;
            float f_sp5 = sp5.valid ? static_cast<float>(sp5.kmh) : F_NAN;

            double lead_dist = INF, follow_dist = INF;
            int32_t lead_v = -1, follow_v = -1;
            int cand_count = 0;
            std::vector<double> ahead_s;
            ahead_s.reserve(n_fleet_valid);
            for (const auto& fu : valid_fleet) {
                if (std::abs(vs.last_epoch - fu.epoch) <= MAX_FLEET_SKEW_SEC) {
                    cand_count += 1;
                    if (fu.veh_idx != v) {
                        double dv = fu.s - s;
                        if (dv > 20.0) {
                            ahead_s.push_back(s + dv);
                            if (dv < lead_dist) { lead_dist = dv; lead_v = fu.veh_idx; }
                        } else if (dv < -20.0) {
                            double db = -dv;
                            if (db < follow_dist) { follow_dist = db; follow_v = fu.veh_idx; }
                        }
                    }
                }
            }
            bool fleet_complete = (cand_count == n_fleet_valid);
            if (fleet_complete) std::sort(ahead_s.begin(), ahead_s.end());

            float f_lead_dist = (lead_v >= 0) ? static_cast<float>(lead_dist) : F_NAN;
            float f_follow_dist = (follow_v >= 0) ? static_cast<float>(follow_dist) : F_NAN;
            float f_fleet_count = static_cast<float>(n_fleet_valid);

            SpeedRes lead_sp = (lead_v >= 0) ? compute_speed(v_states[lead_v], 180.0) : SpeedRes{};
            SpeedRes follow_sp = (follow_v >= 0) ? compute_speed(v_states[follow_v], 180.0) : SpeedRes{};
            float f_lead_kmh = lead_sp.valid ? static_cast<float>(lead_sp.kmh) : F_NAN;
            float f_follow_kmh = follow_sp.valid ? static_cast<float>(follow_sp.kmh) : F_NAN;

            float f_lead_ratio = F_NAN;
            if (lead_sp.valid && lead_sp.end_s > lead_sp.start_s &&
                lead_sp.start_s >= st_s[0] && lead_sp.end_s <= st_s[n_st - 1]) {
                double expected = 0.0;
                bool ok_lr = true;
                for (int si = 0; si < n_seg[d]; ++si) {
                    double left = st_s[si], right = st_s[si + 1];
                    double overlap = std::min(right, lead_sp.end_s) - std::max(left, lead_sp.start_s);
                    if (overlap <= 0.0) continue;
                    int bidx = bm_base + si;
                    if (!bm_valid_flat[bidx] || bm_tier_flat[bidx] == 3) { ok_lr = false; break; }
                    expected += bm_p50_flat[bidx] * overlap / (right - left);
                }
                if (ok_lr) f_lead_ratio = static_cast<float>(expected / lead_sp.seconds);
            }

            double hist_sec = sp5.valid ? sp5.seconds : 0.0;
            double dist_next = st_s[current + 1] - s;
            double first_w = dist_next / (st_s[current + 1] - st_s[current]);
            int c0_idx = bm_base + current;

            int64_t accepted_for_veh = 0;
            double running_max_p90 = 0.0;
            bool has_t3 = false;

            for (int target = current + 1; target < n_st; ++target) {
                if (sp.pref_none[target] - sp.pref_none[current] > 0) break;

                int prev_idx = bm_base + target - 1;
                if (bm_p90_flat[prev_idx] > running_max_p90) running_max_p90 = bm_p90_flat[prev_idx];
                if (bm_tier_flat[prev_idx] == 3) has_t3 = true;

                double p50 = first_w * bm_p50_flat[c0_idx] + (sp.pref_p50[target] - sp.pref_p50[current + 1]);
                double frac_t0 = static_cast<double>(sp.pref_t0[target] - sp.pref_t0[current]) / static_cast<double>(target - current);

                float f_p50 = static_cast<float>(p50);
                float f_mean = F_NAN, f_p10 = F_NAN, f_p90 = F_NAN, f_p90m10 = F_NAN;
                float f_rss_std = F_NAN, f_meanmp50 = F_NAN, f_max_seg_p90 = F_NAN;
                float f_t0_frac = static_cast<float>(frac_t0);
                if (!has_t3) {
                    double p10 = first_w * bm_p10_flat[c0_idx] + (sp.pref_p10[target] - sp.pref_p10[current + 1]);
                    double p90 = first_w * bm_p90_flat[c0_idx] + (sp.pref_p90[target] - sp.pref_p90[current + 1]);
                    double mean = first_w * bm_mean_flat[c0_idx] + (sp.pref_mean[target] - sp.pref_mean[current + 1]);
                    double var = (first_w * bm_std_flat[c0_idx]) * (first_w * bm_std_flat[c0_idx]) + (sp.pref_var[target] - sp.pref_var[current + 1]);
                    f_mean = static_cast<float>(mean);
                    f_p10 = static_cast<float>(p10);
                    f_p90 = static_cast<float>(p90);
                    f_p90m10 = static_cast<float>(p90 - p10);
                    f_rss_std = static_cast<float>(std::sqrt(var));
                    f_meanmp50 = static_cast<float>(mean - p50);
                    f_max_seg_p90 = static_cast<float>(running_max_p90);
                }

                double s_target = st_s[target];
                float f_ahead = F_NAN;
                if (fleet_complete) {
                    int n_ah = static_cast<int>(std::upper_bound(ahead_s.begin(), ahead_s.end(), s_target) - ahead_s.begin());
                    f_ahead = static_cast<float>(n_ah);
                }

                float f_inc_delay = 0.0f, f_inc_near = INCIDENT_SENTINEL_DIST_M, f_inc_jam = 0.0f, f_inc_age = F_NAN;
                if (!active_inc[d].empty() && s_target > s) {
                    double tot_delay = 0.0, jam_len = 0.0, near_d = INCIDENT_SENTINEL_DIST_M, w_age = 0.0;
                    for (const auto& iv : active_inc[d]) {
                        double ov_l = std::min(s_target, iv.s_max) - std::max(s, iv.s_min);
                        if (ov_l <= 0.0) continue;
                        double span_l = std::max(1e-6, iv.s_max - iv.s_min);
                        double frac = std::min(1.0, ov_l / span_l);
                        double d_part = iv.delay_sec * frac;
                        tot_delay += d_part;
                        jam_len += ov_l;
                        double d_near = std::max(0.0, iv.s_min - s);
                        if (d_near < near_d) near_d = d_near;
                        double age_s = std::min(TOMTOM_DEFAULT_TTL_SEC, std::max(0.0, now - iv.crawled_epoch));
                        w_age += d_part * age_s;
                    }
                    if (tot_delay > 0.0) {
                        f_inc_delay = static_cast<float>(tot_delay);
                        f_inc_near = static_cast<float>(near_d);
                        f_inc_jam = static_cast<float>(jam_len);
                        f_inc_age = static_cast<float>(w_age / tot_delay);
                    }
                }

                RawExample ex{};
                ex.feats[0] = static_cast<float>(route_id_idx);
                ex.feats[1] = static_cast<float>(d);
                ex.feats[2] = static_cast<float>(st_orders[current]);
                ex.feats[3] = static_cast<float>(st_orders[target]);
                ex.feats[4] = static_cast<float>(day_t);
                ex.feats[5] = static_cast<float>(weekday);
                ex.feats[6] = static_cast<float>(hr_slot);
                ex.feats[7] = sin_a;
                ex.feats[8] = cos_a;
                ex.feats[9] = static_cast<float>(s);
                ex.feats[10] = static_cast<float>(s_target);
                ex.feats[11] = static_cast<float>(s_target - s);
                ex.feats[12] = static_cast<float>(target - current);
                ex.feats[13] = static_cast<float>(s / rlen);
                ex.feats[14] = static_cast<float>(s_target / rlen);
                ex.feats[15] = static_cast<float>(dist_next);
                ex.feats[16] = f_sp3;
                ex.feats[17] = f_sp5;
                ex.feats[18] = f_p50;
                ex.feats[19] = f_mean;
                ex.feats[20] = f_p10;
                ex.feats[21] = f_p90;
                ex.feats[22] = f_p90m10;
                ex.feats[23] = f_rss_std;
                ex.feats[24] = f_meanmp50;
                ex.feats[25] = f_max_seg_p90;
                ex.feats[26] = f_t0_frac;
                ex.feats[27] = static_cast<float>(route_base_speed_2[d]);
                ex.feats[28] = static_cast<float>(route_spacing_2[d]);
                ex.feats[29] = f_lead_dist;
                ex.feats[30] = f_follow_dist;
                ex.feats[31] = f_fleet_count;
                ex.feats[32] = f_ahead;
                ex.feats[33] = f_lead_kmh;
                ex.feats[34] = f_follow_kmh;
                ex.feats[35] = f_lead_ratio;
                ex.feats[36] = f_inc_delay;
                ex.feats[37] = f_inc_near;
                ex.feats[38] = f_inc_jam;
                ex.feats[39] = f_inc_age;

                ex.veh_idx = v;
                ex.journey = vs.journey;
                ex.target_idx = static_cast<int64_t>(target);
                ex.dir_int = d;
                ex.as_of = now;
                ex.hist_sec = hist_sec;
                examples.push_back(ex);
                accepted_for_veh += 1;
            }
            buf->count_feature_rejected += (static_cast<int64_t>(n_st) - accepted_for_veh);
        }
    }

    auto split_of = [&](double t) -> int32_t {
        if (t < validation_epoch) return 0;
        if (t < test_epoch) return 1;
        return 2;
    };

    for (const auto& ex : examples) {
        int64_t ckey = (ex.journey << 16) | ex.target_idx;
        auto it = crossings.find(ckey);
        if (it == crossings.end()) {
            buf->count_no_crossing += 1;
            continue;
        }
        const auto& cr = it->second;
        double eta = cr.epoch - ex.as_of;
        if (eta < MIN_VALID_ETA_SEC || eta > MAX_VALID_ETA_SEC) {
            buf->count_invalid_eta += 1;
            continue;
        }
        int32_t sp_as_of = split_of(ex.as_of);
        int32_t sp_known = split_of(cr.known_at);
        if (sp_known != sp_as_of) {
            buf->count_label_crosses_split += 1;
            continue;
        }
        if (sp_as_of == 0) buf->count_labeled_train += 1;
        else if (sp_as_of == 1) buf->count_labeled_validation += 1;
        else buf->count_labeled_test += 1;

        buf->features.insert(buf->features.end(), ex.feats, ex.feats + 40);
        buf->veh_idx.push_back(ex.veh_idx);
        buf->journey.push_back(ex.journey);
        buf->target_order.push_back(station_orders_flat[st_off[ex.dir_int] + ex.target_idx]);
        buf->split.push_back(sp_as_of);
        buf->as_of.push_back(ex.as_of);
        buf->eta_seconds.push_back(eta);
        buf->bracket_before.push_back(cr.before_epoch);
        buf->bracket_after.push_back(cr.after_epoch);
        buf->crossing_epoch.push_back(cr.epoch);
        buf->history_seconds.push_back(ex.hist_sec);
    }

    *out_rows = static_cast<int32_t>(buf->eta_seconds.size());
    return buf;
}

BUS_API void cpp_get_causal_feature_counts(
    void* handle,
    int64_t* out_error_code,
    int64_t* out_counts
) {
    auto* buf = static_cast<bus_native::CausalFeatureBuffer*>(handle);
    if (!buf) return;
    *out_error_code = buf->error_code;
    out_counts[0] = buf->count_observations;
    out_counts[1] = buf->count_matched;
    out_counts[2] = buf->count_forecast_attempts;
    out_counts[3] = buf->count_feature_rejected;
    out_counts[4] = buf->count_no_crossing;
    out_counts[5] = buf->count_invalid_eta;
    out_counts[6] = buf->count_label_crosses_split;
    out_counts[7] = buf->count_labeled_train;
    out_counts[8] = buf->count_labeled_validation;
    out_counts[9] = buf->count_labeled_test;
}

BUS_API void cpp_copy_causal_features(
    void* handle,
    float* out_features_40,
    int32_t* out_veh_idx,
    int64_t* out_journey,
    int64_t* out_target,
    int32_t* out_split,
    double* out_as_of,
    double* out_eta,
    double* out_b_before,
    double* out_b_after,
    double* out_crossing,
    double* out_hist_sec
) {
    auto* buf = static_cast<bus_native::CausalFeatureBuffer*>(handle);
    if (!buf || buf->eta_seconds.empty()) return;
    size_t n = buf->eta_seconds.size();
    std::memcpy(out_features_40, buf->features.data(), n * 40 * sizeof(float));
    std::memcpy(out_veh_idx, buf->veh_idx.data(), n * sizeof(int32_t));
    std::memcpy(out_journey, buf->journey.data(), n * sizeof(int64_t));
    std::memcpy(out_target, buf->target_order.data(), n * sizeof(int64_t));
    std::memcpy(out_split, buf->split.data(), n * sizeof(int32_t));
    std::memcpy(out_as_of, buf->as_of.data(), n * sizeof(double));
    std::memcpy(out_eta, buf->eta_seconds.data(), n * sizeof(double));
    std::memcpy(out_b_before, buf->bracket_before.data(), n * sizeof(double));
    std::memcpy(out_b_after, buf->bracket_after.data(), n * sizeof(double));
    std::memcpy(out_crossing, buf->crossing_epoch.data(), n * sizeof(double));
    std::memcpy(out_hist_sec, buf->history_seconds.data(), n * sizeof(double));
}

BUS_API void cpp_free_causal_features(void* handle) {
    delete static_cast<bus_native::CausalFeatureBuffer*>(handle);
}

}  // extern "C"
