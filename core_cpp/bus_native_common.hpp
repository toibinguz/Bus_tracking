#pragma once

#include <cmath>
#include <cstdint>
#include <limits>

#ifdef _WIN32
#define BUS_API __declspec(dllexport)
#else
#define BUS_API __attribute__((visibility("default")))
#endif

namespace bus_native {

constexpr double PI = 3.14159265358979323846;
constexpr double INF = std::numeric_limits<double>::infinity();
constexpr float F_NAN = std::numeric_limits<float>::quiet_NaN();

// SSOT constants matching config/system_config.py
constexpr double METERS_PER_DEG_LON_EQ = 111320.0;
constexpr double METERS_PER_DEG_LAT = 110540.0;
constexpr double MAX_CORRIDOR_CT_M = 35.0;
constexpr double MAX_BACKWARD_JITTER_M = 20.0;
constexpr double GPS_MAX_SPEED_KMPH = 80.0;
constexpr double FRENET_MAX_SPEED_MPS = GPS_MAX_SPEED_KMPH / 3.6;
constexpr double TERMINAL_RESET_ZONE_M = 800.0;
constexpr double STALE_DT_MAX_SEC = 300.0;

constexpr double MAX_BRIDGEABLE_GAP_SEC = 1800.0;
constexpr double MIN_DETOUR_DISP_M = 100.0;
constexpr double MIN_DETOUR_SPD_KMPH = 2.0;
constexpr double MAX_DETOUR_SPD_KMPH = 60.0;
constexpr double MAX_BACKWARD_RESET_M = 200.0;
constexpr int MIN_PINGS_PER_TRIP = 5;
constexpr double MIN_TRIP_DISTANCE_M = 500.0;
constexpr double TERMINAL_STAT_TOL_M = 15.0;

constexpr double BRACKET_MAX_DT_SEC = 150.0;
constexpr double BRACKET_MAX_DS_M = 1000.0;
constexpr double BRACKET_SEG_LEN_FACTOR = 1.35;
constexpr double SEG_MIN_SPD_KMPH = 1.5;
constexpr double SEG_MAX_SPD_KMPH = 65.0;
constexpr double DEFAULT_URBAN_BUS_SPD_KMPH = 18.0;

// Causal feature extraction constants matching causal_eta.py & causal_eta_training.py
constexpr double TOMTOM_DEFAULT_TTL_SEC = 900.0;
constexpr float INCIDENT_SENTINEL_DIST_M = 25000.0f;
constexpr double MAX_POSITION_AGE_SEC = 90.0;
constexpr double MAX_FLEET_SKEW_SEC = 45.0;
constexpr double SPEED_MAX_GAP_SEC = 120.0;
constexpr double MIN_SPEED_WINDOW_SEC = 30.0;
constexpr double SPEED_WINDOW_TOLERANCE_SEC = 30.0;
constexpr double STATIONARY_TOLERANCE_M = 15.0;
constexpr double MAX_LABEL_BRACKET_SEC = 90.0;
constexpr double MAX_LABEL_BRACKET_M = 600.0;
constexpr double MIN_VALID_ETA_SEC = 5.0;
constexpr double MAX_VALID_ETA_SEC = 7200.0;

inline double round1(double v) { return std::nearbyint(v * 10.0) / 10.0; }
inline double round2(double v) { return std::nearbyint(v * 100.0) / 100.0; }

inline int64_t hanoi_day_num(double epoch) {
    int64_t t_local = static_cast<int64_t>(std::floor(epoch)) + 25200LL;
    int64_t q = t_local / 86400LL;
    if (t_local < 0 && (t_local % 86400LL) != 0) q -= 1;
    return q;
}

inline void hanoi_calendar(double epoch, int& day_type, int& weekday, int& hr_slot, int& minute) {
    int64_t t_local = static_cast<int64_t>(std::floor(epoch)) + 25200LL;
    int64_t day_num = t_local / 86400LL;
    if (t_local < 0 && (t_local % 86400LL) != 0) day_num -= 1;
    int64_t sec_in_day = t_local - day_num * 86400LL;
    weekday = static_cast<int>(((day_num + 3LL) % 7LL + 7LL) % 7LL);  // 0=Mon..6=Sun
    day_type = (weekday < 5) ? 0 : (weekday == 5 ? 1 : 2);
    int hr = static_cast<int>(sec_in_day / 3600LL);
    hr_slot = (hr < 5) ? 5 : ((hr > 21) ? 21 : hr);
    minute = static_cast<int>((sec_in_day % 3600LL) / 60LL);
}

inline void hanoi_daytype_hour(double epoch, int& day_type, int& hr_slot) {
    int wd = 0, minute = 0;
    hanoi_calendar(epoch, day_type, wd, hr_slot, minute);
}

}  // namespace bus_native
