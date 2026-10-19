---
name: bus-eta-prediction
description: Methodology, mathematical formulation, and end-to-end pipeline for predicting Bus Estimated Time of Arrival (ETA) at downstream stations using historical transit statistics, spatial features, and gradient boosting (LightGBM/XGBoost).
---

# Bus Estimated Time of Arrival (ETA) Prediction Framework

## 1. Problem Formulation

Given a bus $v$ on route $r$ observed at time $t_0$ at position $(lat_0, lon_0)$ with speed $s_0$:
Predict the arrival time $T_{arr}(v, s_k)$ or travel duration $\Delta t(v, s_k) = T_{arr} - t_0$ to reach downstream target stop $s_k$.

```
Stop S_0 ─── [Bus V (t0, lat0, lon0, s0)] ─── Stop S_1 ─────── Stop S_k (Destination)
                        └─── Predict Δt = T_arrival - t0 ───┘
```

---

## 2. Multi-tier Model Evolution

To ensure academic rigor and avoid premature over-fitting, models must be built and evaluated progressively:

### Tier 1: Historical Mean Baseline (T0)
- Calculates mean transit duration $\bar{T}(s_i, s_{i+1}, h, d)$ between consecutive stops $s_i \to s_{i+1}$ grouped by:
  - Hour of day $h \in [5, 22]$
  - Day of week $d \in [\text{Mon}, \dots, \text{Sun}]$
- Total ETA to stop $s_k$:
  $$\text{ETA}_{\text{baseline}} = \sum_{j=i}^{k-1} \bar{T}(s_j, s_{j+1}, h, d) \times \left(1 - \frac{\text{dist\_traveled}}{\text{segment\_length}}\right)$$

### Tier 2: Kinematic Traffic-Aware Baseline (T1)
- Blends current instantaneous speed $s_0$ with historical corridor speed $v_{\text{hist}}$:
  $$v_{\text{eff}} = \alpha s_0 + (1 - \alpha) v_{\text{hist}}$$
  $$\text{ETA}_{\text{kinematic}} = \frac{\text{Remaining Distance}}{v_{\text{eff}}} + \sum (\text{Average Dwell Time at Intermediate Stops})$$

### Tier 3: Gradient Boosted Trees (LightGBM / XGBoost - T2)
- Feature vector $\mathbf{x}$:
  1. **Spatial Features**: Remaining distance to target stop ($m$), number of intermediate stops, segment length ($m$), road curvature/sinuosity.
  2. **Kinematic Features**: Current speed ($km/h$), 3-minute moving average speed, acceleration.
  3. **Temporal Features**: Hour of day (sin/cos encoding), day of week, peak vs off-peak indicator.
  4. **Corridor State**: Current congestion index of route segment from TomTom incidents or upstream buses.
- Objective: Minimize Mean Squared Error (MSE) or Huber Loss (robust to GPS outliers).

---

## 3. Academic Evaluation Metrics

All models must report 3 core metrics calculated on an out-of-time test split (e.g. Train on 17/10, Test on 18/10, or 80/20 time-series split):

1. **Mean Absolute Error (MAE)**:
   $$\text{MAE} = \frac{1}{N} \sum_{i=1}^N |\hat{y}_i - y_i| \quad (\text{Target: } < 60 \text{ seconds})$$
2. **Root Mean Squared Error (RMSE)**:
   $$\text{RMSE} = \sqrt{\frac{1}{N} \sum_{i=1}^N (\hat{y}_i - y_i)^2}$$
3. **Mean Absolute Percentage Error (MAPE)**:
   $$\text{MAPE} = \frac{100\%}{N} \sum_{i=1}^N \left| \frac{\hat{y}_i - y_i}{y_i} \right| \quad (\text{Target: } < 15\%)$$

---

## 4. Evaluation Slicing Protocol

Never report a single global metric. Metrics must be partitioned by:
- **Corridor Type**: Arterial Core (Tuyến 02, 32) vs Outer Ring vs BRT.
- **Time Window**: Morning Peak (07:00 - 08:30) vs Evening Peak (17:00 - 18:30) vs Midday Off-peak.
- **Horizon Distance**: Short-range ($< 1$ km) vs Medium-range (1 - 3 km) vs Long-range ($> 3$ km).

