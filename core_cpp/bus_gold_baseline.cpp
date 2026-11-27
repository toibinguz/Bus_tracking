#include "bus_native_common.hpp"

#include <algorithm>
#include <cfenv>
#include <vector>

namespace bus_native {

struct TripPing {
    double epoch;
    double s;
    int64_t day_num;
};

static double np_percentile(const std::vector<double>& sorted_v, double pct) {
    int n = static_cast<int>(sorted_v.size());
    if (n == 0) return 0.0;
    if (n == 1) return sorted_v[0];
    double pos = (pct / 100.0) * (n - 1);
    int lo = static_cast<int>(std::floor(pos));
    int hi = static_cast<int>(std::ceil(pos));
    double frac = pos - lo;
    return sorted_v[lo] + frac * (sorted_v[hi] - sorted_v[lo]);
}

}  // namespace bus_native

extern "C" {

BUS_API void cpp_build_route_baseline(
    double shape_len_go, int n_st_go, const double* st_s_go_full,
    double shape_len_re, int n_st_re, const double* st_s_re_full,
    int64_t fit_end_day, int64_t train_end_day,
    int n_pings, const int32_t* vehicle_ids, const int32_t* dir_ints,
    const double* epochs, const double* s_vals,
    int32_t* out_n_cells,
    int32_t* out_dir, int32_t* out_k_seg, int32_t* out_day_type, int32_t* out_hr_slot,
    int32_t* out_n_eff, int32_t* out_tier,
    double* out_seg_dist, double* out_p10, double* out_p50, double* out_p90,
    double* out_mean, double* out_std
) {
    using namespace bus_native;
    std::fesetround(FE_TONEAREST);

    std::vector<double> act_s[2];
    const double* raw_ptr[2] = {st_s_go_full, st_s_re_full};
    int raw_n[2] = {n_st_go, n_st_re};
    double shape_len[2] = {shape_len_go, shape_len_re};
    for (int d = 0; d < 2; ++d) {
        if (raw_n[d] >= 4) act_s[d].assign(raw_ptr[d] + 1, raw_ptr[d] + raw_n[d] - 1);
        else if (raw_n[d] > 0) act_s[d].assign(raw_ptr[d], raw_ptr[d] + raw_n[d]);
    }

    int n_seg[2] = {
        std::max(0, static_cast<int>(act_s[0].size()) - 1),
        std::max(0, static_cast<int>(act_s[1].size()) - 1),
    };

    using VecD = std::vector<double>;
    std::vector<std::vector<std::vector<VecD>>> slot_samples[2];
    std::vector<std::vector<VecD>> daytype_samples[2];
    std::vector<VecD> seg_all_samples[2];
    double route_dist_sum[2] = {0.0, 0.0};
    double route_time_sum[2] = {0.0, 0.0};
    for (int d = 0; d < 2; ++d) {
        slot_samples[d].assign(n_seg[d], std::vector<std::vector<VecD>>(3, std::vector<VecD>(17)));
        daytype_samples[d].assign(n_seg[d], std::vector<VecD>(3));
        seg_all_samples[d].assign(n_seg[d], VecD{});
    }

    auto process_trip = [&](const std::vector<TripPing>& tr, int d, int n_st_act, const std::vector<double>& st_s) {
        if (static_cast<int>(tr.size()) < 2 || n_st_act < 2) return;
        int start_idx = 0, end_idx = static_cast<int>(tr.size()) - 1;
        double s_first = tr.front().s, s_last = tr.back().s;
        while (start_idx + 1 < static_cast<int>(tr.size()) && (tr[start_idx + 1].s - s_first) <= TERMINAL_STAT_TOL_M) ++start_idx;
        while (end_idx > start_idx && (s_last - tr[end_idx - 1].s) <= TERMINAL_STAT_TOL_M) --end_idx;
        int len_trim = end_idx - start_idx + 1;
        if (len_trim < MIN_PINGS_PER_TRIP) return;
        if ((tr[end_idx].s - tr[start_idx].s) < MIN_TRIP_DISTANCE_M) return;

        bool is_train = tr[start_idx].day_num <= train_end_day;
        bool is_fit = tr[end_idx].day_num <= fit_end_day;
        if (!is_train || !is_fit) return;

        std::vector<double> s_mono(len_trim);
        s_mono[0] = tr[start_idx].s;
        for (int i = 1; i < len_trim; ++i) s_mono[i] = std::max(s_mono[i - 1], tr[start_idx + i].s);
        double s_start = s_mono.front(), s_end = s_mono.back();

        std::vector<bool> has_arr(n_st_act, false);
        std::vector<double> arr_ep(n_st_act, 0.0);
        int p_idx = 0;
        for (int k_st = 0; k_st < n_st_act; ++k_st) {
            double s_st = st_s[k_st];
            if (s_st < s_start || s_st > s_end) continue;
            while (p_idx + 1 < len_trim && s_mono[p_idx + 1] < s_st) ++p_idx;
            if (p_idx + 1 >= len_trim) break;
            double s0 = s_mono[p_idx], s1 = s_mono[p_idx + 1];
            double t0 = tr[start_idx + p_idx].epoch, t1 = tr[start_idx + p_idx + 1].epoch;
            double dt = t1 - t0, ds = s1 - s0;
            double prev_st_s = (k_st > 0) ? st_s[k_st - 1] : s_st;
            double next_st_s = (k_st + 1 < n_st_act) ? st_s[k_st + 1] : s_st;
            double local_seg = std::max(s_st - prev_st_s, next_st_s - s_st);
            double max_ds = std::max(BRACKET_MAX_DS_M, BRACKET_SEG_LEN_FACTOR * local_seg);
            if (dt > 0.0 && dt <= BRACKET_MAX_DT_SEC && ds >= 0.0 && ds <= max_ds) {
                has_arr[k_st] = true;
                arr_ep[k_st] = (ds > 1e-3) ? (t0 + ((s_st - s0) / ds) * dt) : t0;
            }
        }

        for (int k = 0; k < n_st_act - 1; ++k) {
            double seg_dist = st_s[k + 1] - st_s[k];
            if (seg_dist <= 1.0) continue;
            if (!has_arr[k] || !has_arr[k + 1]) continue;
            double tt = arr_ep[k + 1] - arr_ep[k];
            if (tt <= 0.0) continue;
            double spd = (seg_dist / tt) * 3.6;
            if (spd < SEG_MIN_SPD_KMPH || spd > SEG_MAX_SPD_KMPH) continue;
            int day_t = 0, hr_s = 5;
            hanoi_daytype_hour(arr_ep[k], day_t, hr_s);
            slot_samples[d][k][day_t][hr_s - 5].push_back(tt);
            daytype_samples[d][k][day_t].push_back(tt);
            seg_all_samples[d][k].push_back(tt);
            route_dist_sum[d] += seg_dist;
            route_time_sum[d] += tt;
        }
    };

    int i = 0;
    while (i < n_pings) {
        int32_t vid = vehicle_ids[i], d = dir_ints[i];
        int j = i;
        while (j < n_pings && vehicle_ids[j] == vid && dir_ints[j] == d) ++j;

        if ((d == 0 || d == 1) && n_seg[d] >= 1) {
            int w_beg = i;
            while (w_beg < j) {
                int bucket = 2;
                int64_t dn0 = hanoi_day_num(epochs[w_beg]);
                if (dn0 <= fit_end_day) bucket = 0; else if (dn0 <= train_end_day) bucket = 1;
                int w_end = w_beg + 1;
                while (w_end < j) {
                    int64_t dn = hanoi_day_num(epochs[w_end]);
                    int b = (dn <= fit_end_day) ? 0 : (dn <= train_end_day ? 1 : 2);
                    if (b != bucket) break;
                    ++w_end;
                }
                if (bucket == 0) {
                    std::vector<TripPing> curr;
                    double max_s = -1.0;
                    for (int p = w_beg; p < w_end; ++p) {
                        int64_t dn = hanoi_day_num(epochs[p]);
                        TripPing tp{epochs[p], s_vals[p], dn};
                        if (curr.empty()) { curr.push_back(tp); max_s = tp.s; continue; }
                        double dt = tp.epoch - curr.back().epoch;
                        double ds = tp.s - curr.back().s;
                        bool term_rst = (shape_len[d] > 1000.0 && curr.back().s >= shape_len[d] - TERMINAL_RESET_ZONE_M &&
                                         tp.s <= TERMINAL_RESET_ZONE_M && tp.s < curr.back().s - MAX_BACKWARD_JITTER_M);
                        bool bridge = (dt > STALE_DT_MAX_SEC && dt <= MAX_BRIDGEABLE_GAP_SEC && ds > MIN_DETOUR_DISP_M &&
                                       (ds / dt) * 3.6 >= MIN_DETOUR_SPD_KMPH && (ds / dt) * 3.6 <= MAX_DETOUR_SPD_KMPH);
                        bool brk = (dt > STALE_DT_MAX_SEC && !bridge) || ds < -MAX_BACKWARD_JITTER_M ||
                                   tp.s < (max_s - MAX_BACKWARD_RESET_M) || term_rst;
                        if (brk) {
                            process_trip(curr, d, static_cast<int>(act_s[d].size()), act_s[d]);
                            curr.clear(); curr.push_back(tp); max_s = tp.s;
                        } else {
                            curr.push_back(tp);
                            if (tp.s > max_s) max_s = tp.s;
                        }
                    }
                    if (!curr.empty()) process_trip(curr, d, static_cast<int>(act_s[d].size()), act_s[d]);
                }
                w_beg = w_end;
            }
        }
        i = j;
    }

    int out_idx = 0;
    for (int d = 0; d < 2; ++d) {
        if (n_seg[d] < 1) continue;
        double route_avg_mps = (route_time_sum[d] > 0.0) ? (route_dist_sum[d] / route_time_sum[d]) : (DEFAULT_URBAN_BUS_SPD_KMPH / 3.6);
        for (int k = 0; k < n_seg[d]; ++k) {
            double seg_dist = round1(std::max(15.0, act_s[d][k + 1] - act_s[d][k]));
            for (int day_type = 0; day_type < 3; ++day_type) {
                int tier0_thresh = (day_type == 0) ? 10 : 5;
                for (int hr = 5; hr <= 21; ++hr) {
                    int h_idx = hr - 5;
                    const auto& direct = slot_samples[d][k][day_type][h_idx];
                    int n_direct = static_cast<int>(direct.size());
                    std::vector<double> eff;
                    if ((day_type == 1 || day_type == 2) && n_direct < 8) {
                        for (int ha = hr - 1; ha <= hr + 1; ++ha) {
                            if (ha >= 5 && ha <= 21) {
                                const auto& v = slot_samples[d][k][day_type][ha - 5];
                                eff.insert(eff.end(), v.begin(), v.end());
                            }
                        }
                    } else {
                        eff = direct;
                    }
                    int n_eff = static_cast<int>(eff.size());
                    int q_tier = 3;
                    std::vector<double> used;
                    if (n_eff >= tier0_thresh) {
                        q_tier = 0; used = std::move(eff);
                    } else if (n_eff >= 3) {
                        q_tier = 1; used = std::move(eff);
                    } else {
                        std::vector<double> neigh;
                        for (int ha = hr - 1; ha <= hr + 1; ++ha) {
                            if (ha >= 5 && ha <= 21) {
                                const auto& v = slot_samples[d][k][day_type][ha - 5];
                                neigh.insert(neigh.end(), v.begin(), v.end());
                            }
                        }
                        if (static_cast<int>(neigh.size()) >= 3) {
                            q_tier = 2; used = std::move(neigh);
                        } else if (static_cast<int>(daytype_samples[d][k][day_type].size()) >= 3) {
                            q_tier = 2; used = daytype_samples[d][k][day_type];
                        } else if (!seg_all_samples[d][k].empty()) {
                            q_tier = 2; used = seg_all_samples[d][k];
                        } else {
                            q_tier = 3;
                        }
                    }

                    double p10, p50, p90, mean_v, std_v;
                    if (!used.empty()) {
                        std::sort(used.begin(), used.end());
                        p10 = np_percentile(used, 10.0);
                        p50 = np_percentile(used, 50.0);
                        p90 = np_percentile(used, 90.0);
                        double sum = 0.0;
                        for (double v : used) sum += v;
                        mean_v = sum / used.size();
                        if (used.size() > 1) {
                            double sq = 0.0;
                            for (double v : used) { double diff = v - mean_v; sq += diff * diff; }
                            std_v = std::sqrt(sq / used.size());
                        } else {
                            std_v = round2(0.15 * mean_v);
                        }
                    } else {
                        p50 = seg_dist / std::max(1.0, route_avg_mps);
                        p10 = p50 * 0.75;
                        p90 = p50 * 1.35;
                        mean_v = p50;
                        std_v = p50 * 0.20;
                    }

                    out_dir[out_idx] = d;
                    out_k_seg[out_idx] = k;
                    out_day_type[out_idx] = day_type;
                    out_hr_slot[out_idx] = hr;
                    out_n_eff[out_idx] = n_eff;
                    out_tier[out_idx] = q_tier;
                    out_seg_dist[out_idx] = seg_dist;
                    out_p10[out_idx] = round2(p10);
                    out_p50[out_idx] = round2(p50);
                    out_p90[out_idx] = round2(p90);
                    out_mean[out_idx] = round2(mean_v);
                    out_std[out_idx] = round2(std_v);
                    ++out_idx;
                }
            }
        }
    }
    *out_n_cells = out_idx;
}

}  // extern "C"
