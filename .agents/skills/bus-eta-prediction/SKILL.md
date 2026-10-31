---
name: bus-eta-prediction
description: Methodology, mathematical formulation, and end-to-end pipeline for predicting Bus Estimated Time of Arrival (ETA) at downstream stations using historical transit statistics, spatial features, and gradient boosting (LightGBM/XGBoost).
---

# Bus Estimated Time of Arrival (ETA) Prediction Framework

## 1. Problem Formulation

Given a bus $v$ on route $r$ observed at time $t_0$ at projected 1D position $s_{\text{bus}}$:
Predict the arrival time $T_{\text{arr}}(v, S_k)$ or travel duration $\Delta t(v, S_k) = T_{\text{arr}} - t_0$ to reach downstream target stop $S_k$ at meter $s_k$.

```
Stop S_0 ─── [Bus V (t0, s_bus)] ─── Stop S_1 ─────── Stop S_k (Destination)
                     └─── Predict Δt = T_arrival - t0 ───┘
```

---

## 2. Multi-tier Model Evolution (Empirical & Pragmatic)

To prevent premature complexity and avoid overfitting on noisy GPS pings, models evolve in strict order:

### Tier 1: Historical Segment Travel Time Matrix (T0 - Primary Gold Anchor)
- **Mathematical Principle**: Discretize route into station-to-station segments $S_k \to S_{k+1}$.
- **Measurement Method**: Linear Station Crossing Interpolation:
  $$\hat{t}(S_k) = t_A + (t_B - t_A) \cdot \frac{s_k - s_A}{s_B - s_A}$$
  $$\Delta T_{k \to k+1} = \hat{t}(S_{k+1}) - \hat{t}(S_k)$$
- **End-to-End Generalization**: Station transit time $\Delta T_{k \to k+1}$ naturally absorbs rolling time, stop dwell, and traffic light delays into an observable physical variable. Do not attempt unverified micro-decomposition.
- **Strict Route Isolation**: Each route is modeled 100% independently from its own empirical observations. No speculative cross-route corridor sharing.
- **Selective Ignorance on Sparsity**: If a segment has zero observation ($N = 0$), flag as unobserved / route fallback, never fabricate synthetic data.
- **Closed-Form Instant Inference ($< 0.1$ ms)**:
  $$\text{ETA}(v \to S_k) = T_{\text{partial}}(s_{\text{bus}} \to S_{i+1}) + \sum_{j=i+1}^{k-1} \mathbf{T}(r, d, j, w, h)$$

### Tier 2: Machine Learning Residual Correction (T1 - Future Real-time Fine Tuning)
- Machine Learning models (LightGBM / XGBoost) ONLY predict the **residual error** $\Delta t_{\text{ML}}$ against the historical matrix anchor:
  $$\text{ETA}_{\text{final}} = \text{ETA}_{\text{baseline}} + \Delta t_{\text{ML}}$$
- Inputs: Current derived velocity $\bar{v} = \Delta s / \Delta t$, lateral cross-track error $d_\perp$, headway to leading bus, temporal features.
- Never deploy black-box ML as a standalone end-to-end predictor without the Matrix anchor.

---

## 3. Academic Evaluation Metrics

All models must report 3 core metrics calculated on an out-of-time test split:

1. **Mean Absolute Error (MAE)**:
   $$\text{MAE} = \frac{1}{N} \sum_{i=1}^N |\hat{y}_i - y_i| \quad (\text{Target: } < 60 \text{ seconds})$$
2. **Root Mean Squared Error (RMSE)**:
   $$\text{RMSE} = \sqrt{\frac{1}{N} \sum_{i=1}^N (\hat{y}_i - y_i)^2}$$
3. **Mean Absolute Percentage Error (MAPE)**:
   $$\text{MAPE} = \frac{100\%}{N} \sum_{i=1}^N \left| \frac{\hat{y}_i - y_i}{y_i} \right| \quad (\text{Target: } < 15\%)$$

---

## 4. Evaluation Slicing Protocol

Metrics must be partitioned by:
- **Corridor Type**: Arterial Core vs Outer Ring vs BRT / Electric Express.
- **Time Window**: Morning Peak (06:30 - 09:00), Off-peak Day (09:00 - 16:30), Evening Peak (16:30 - 19:30), Night (19:30 - 22:00).
- **Day Type**: Weekday vs Weekend.
- **Horizon Distance**: Short-range ($< 1$ km) vs Medium-range (1 - 3 km) vs Long-range ($> 3$ km).
