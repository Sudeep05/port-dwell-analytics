"""
run_models.py — Modelling & Validation (Pipeline Stages 3–4)

Runs multi-algorithm clustering (K-Means, Hierarchical) for dwell segmentation
and time-series forecasting for yard throughput prediction. Produces validation
metrics and selects best models.

Usage:
    python scripts/run_models.py \
        --container-features data/dwell_features.csv \
        --block-features data/block_daily_features.csv \
        --num-segments 4 \
        --forecast-horizon 14 \
        --random-seed 42 \
        --output-dir data/model_outputs

Outputs (in output-dir):
    - cluster_results.json
    - forecast_results.json
    - validation_metrics.json
    - charts/ directory with PNG visualizations
"""

import argparse
import json
import os
import warnings
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import silhouette_score, calinski_harabasz_score
from sklearn.preprocessing import StandardScaler
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Part A: Dwell Behaviour Clustering
# ---------------------------------------------------------------------------

def prepare_clustering_features(df):
    """Select and prepare features for clustering.
    
    IMPORTANT: Cluster on DWELL BEHAVIOR features only (dwell_hours, storage_cost,
    teu_equivalent, weight). Do NOT include one-hot encoded categoricals — they
    dominate the feature space and cause K-Means to split by container type instead
    of dwell behavior. Categoricals are used for PROFILING clusters after assignment,
    not for forming them. This follows the same approach as RFM segmentation.
    """
    # Only use containers with valid dwell
    df_valid = df[df["dwell_hours"].notna()].copy()

    # Dwell behavior features ONLY — no categoricals
    feature_cols = ["dwell_hours", "teu_equivalent"]

    # Add storage cost if available
    if "storage_cost_usd" in df_valid.columns and df_valid["storage_cost_usd"].notna().any():
        feature_cols.append("storage_cost_usd")
        df_valid["storage_cost_usd"] = df_valid["storage_cost_usd"].fillna(0)

    # Add weight if available (heavier containers may have different dwell patterns)
    if "weight_tons" in df_valid.columns and df_valid["weight_tons"].notna().any():
        feature_cols.append("weight_tons")

    # Log-transform skewed features (dwell and cost are heavily right-skewed)
    for col in ["dwell_hours", "storage_cost_usd"]:
        if col in feature_cols and col in df_valid.columns:
            skew = df_valid[col].skew()
            if abs(skew) > 2:
                df_valid[f"{col}_log"] = np.log1p(df_valid[col])
                feature_cols = [f"{col}_log" if c == col else c for c in feature_cols]

    # Extract feature matrix — ONLY numeric dwell-behavior features
    X = df_valid[feature_cols].fillna(0).values

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    return X_scaled, df_valid, feature_cols, scaler


def run_clustering(X_scaled, k_range):
    """Run K-Means and Hierarchical clustering for a range of k values.
    
    For datasets > 15,000 rows, Hierarchical clustering runs on a stratified
    sample of 10,000 to avoid O(n²) memory explosion. K-Means runs on full data.
    """
    results = []
    n_samples = X_scaled.shape[0]
    
    # Sample for Hierarchical if dataset is large
    HIER_MAX = 10000
    if n_samples > HIER_MAX:
        rng = np.random.RandomState(42)
        sample_idx = rng.choice(n_samples, size=HIER_MAX, replace=False)
        X_hier = X_scaled[sample_idx]
        print(f"    (Hierarchical will use {HIER_MAX:,} sample — "
              f"full {n_samples:,} is too large for O(n²) linkage)")
    else:
        X_hier = X_scaled
        sample_idx = None

    for k in k_range:
        print(f"    Running k={k}...", end=" ", flush=True)
        
        # K-Means — runs on FULL dataset (scales linearly)
        km = KMeans(n_clusters=k, init="k-means++", n_init=10,
                    max_iter=300, random_state=42)
        km_labels = km.fit_predict(X_scaled)
        
        # Silhouette on sample for speed (exact on full is O(n²))
        SIL_SAMPLE = 10000
        if n_samples > SIL_SAMPLE:
            sil_idx = np.random.RandomState(42).choice(n_samples, SIL_SAMPLE, replace=False)
            km_sil = silhouette_score(X_scaled[sil_idx], km_labels[sil_idx])
            km_ch = calinski_harabasz_score(X_scaled[sil_idx], km_labels[sil_idx])
        else:
            km_sil = silhouette_score(X_scaled, km_labels)
            km_ch = calinski_harabasz_score(X_scaled, km_labels)

        results.append({
            "algorithm": "KMeans",
            "k": k,
            "silhouette_score": round(km_sil, 4),
            "calinski_harabasz": round(km_ch, 2),
            "inertia": round(km.inertia_, 2),
            "labels": km_labels.tolist(),
            "centroids": km.cluster_centers_.tolist(),
        })

        # Hierarchical (Ward) — runs on sample if large
        hc = AgglomerativeClustering(n_clusters=k, linkage="ward")
        hc_labels_sample = hc.fit_predict(X_hier)
        hc_sil = silhouette_score(X_hier, hc_labels_sample)
        hc_ch = calinski_harabasz_score(X_hier, hc_labels_sample)
        
        # If we sampled, we need full-dataset labels for potential selection.
        # Assign full dataset using nearest-centroid from the sample clusters.
        if sample_idx is not None:
            from sklearn.neighbors import NearestCentroid
            nc = NearestCentroid()
            nc.fit(X_hier, hc_labels_sample)
            hc_labels_full = nc.predict(X_scaled)
        else:
            hc_labels_full = hc_labels_sample

        results.append({
            "algorithm": "Hierarchical",
            "k": k,
            "silhouette_score": round(hc_sil, 4),
            "calinski_harabasz": round(hc_ch, 2),
            "inertia": None,
            "labels": hc_labels_full.tolist(),
            "centroids": None,
        })
        
        print(f"KM sil={km_sil:.3f}, HC sil={hc_sil:.3f}", flush=True)

    return results


def select_best_clustering(results, df_valid):
    """Select best (algorithm, k) by silhouette score with sanity checks.
    
    We test k=2 through k=10 for complete elbow/silhouette curves, but only
    SELECT from k<=8 for interpretability. A report with 9-10 segments produces
    duplicate archetypes (K-Means splits the same dwell band by 20ft vs 40ft)
    that confuse stakeholders. If k=9 or k=10 has significantly higher silhouette
    (>0.05), we note it in the output but still prefer k<=8.
    """
    MAX_K_SELECTABLE = 8
    
    # Sort by silhouette descending, but only consider k <= MAX_K_SELECTABLE
    selectable = [r for r in results if r["k"] <= MAX_K_SELECTABLE]
    ranked = sorted(selectable, key=lambda r: r["silhouette_score"], reverse=True)
    
    # Check if higher k had significantly better silhouette (for logging)
    all_ranked = sorted(results, key=lambda r: r["silhouette_score"], reverse=True)
    if all_ranked[0]["k"] > MAX_K_SELECTABLE and ranked:
        gap = all_ranked[0]["silhouette_score"] - ranked[0]["silhouette_score"]
        if gap > 0.01:
            print(f"    Note: k={all_ranked[0]['k']} had silhouette {all_ranked[0]['silhouette_score']:.4f} "
                  f"(+{gap:.4f} vs best k<={MAX_K_SELECTABLE}), but capped at k<={MAX_K_SELECTABLE} for interpretability.")

    for candidate in ranked:
        labels = np.array(candidate["labels"])
        n_total = len(labels)

        # Sanity check: no segment < 3% or > 55%
        # (relaxed: the 'normal' dwell segment is naturally the largest)
        counts = np.bincount(labels)
        pcts = counts / n_total * 100
        if pcts.min() < 3 or pcts.max() > 55:
            candidate["_rejected"] = (
                f"Segment sizes: {pcts.round(1).tolist()}% — "
                f"min<3% or max>55%")
            continue

        candidate["_selected"] = True
        return candidate

    # --- Interpretability fallback ---
    # If no config passes strict checks, prefer FEWER segments (k=4 or k=5)
    # for interpretability over k=7 with marginal silhouette gain.
    # A report with 3-4 distinct archetypes is more useful than 7 similar ones.
    for candidate in ranked:
        labels = np.array(candidate["labels"])
        counts = np.bincount(labels)
        pcts = counts / len(labels) * 100
        if pcts.min() >= 2 and pcts.max() <= 65 and candidate["k"] <= 5:
            candidate["_selected"] = True
            candidate["_warning"] = (f"Strict sanity failed for all configs. "
                                     f"Selected k={candidate['k']} for interpretability.")
            return candidate

    # Last resort: pick k=4 from whichever algorithm has higher silhouette
    k4_candidates = [r for r in ranked if r["k"] == 4]
    if k4_candidates:
        best = k4_candidates[0]
        best["_selected"] = True
        best["_warning"] = "Forced k=4 for interpretability; silhouette may be suboptimal."
        return best

    # Absolute fallback
    best = ranked[0]
    best["_selected"] = True
    best["_warning"] = "No configuration passed sanity checks; using highest silhouette"
    return best


def generate_clustering_charts(results, X_scaled, best, output_dir):
    """Generate elbow plot, silhouette comparison, dendrogram, and centroid comparison."""
    charts_dir = os.path.join(output_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    # --- Elbow Plot ---
    km_results = [r for r in results if r["algorithm"] == "KMeans"]
    ks = [r["k"] for r in km_results]
    inertias = [r["inertia"] for r in km_results]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(ks, inertias, "o-", linewidth=2, markersize=8, color="#1D9E75")
    ax.set_xlabel("Number of Clusters (k)", fontsize=12)
    ax.set_ylabel("Inertia (Within-Cluster SS)", fontsize=12)
    ax.set_title("Elbow Plot for Optimal Cluster Count", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, "elbow_plot.png"), dpi=300)
    plt.close()

    # --- Silhouette Comparison ---
    fig, ax = plt.subplots(figsize=(8, 5))
    for algo in ["KMeans", "Hierarchical"]:
        algo_results = [r for r in results if r["algorithm"] == algo]
        ax.plot([r["k"] for r in algo_results],
                [r["silhouette_score"] for r in algo_results],
                "o-", linewidth=2, markersize=8, label=algo)
    ax.set_xlabel("Number of Clusters (k)", fontsize=12)
    ax.set_ylabel("Silhouette Score", fontsize=12)
    ax.set_title("Silhouette Score: K-Means vs Hierarchical", fontsize=14,
                 fontweight="bold")
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0.25, color="red", linestyle="--", alpha=0.5, label="Min threshold")
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, "silhouette_comparison.png"), dpi=300)
    plt.close()

    # --- Dendrogram (Hierarchical Tree) ---
    # Shows how clusters merge and validates the chosen k
    print("    Generating dendrogram...")
    try:
        from scipy.cluster.hierarchy import linkage, dendrogram

        # Use the same sample as hierarchical clustering
        n_samples = X_scaled.shape[0]
        DENDRO_SAMPLE = 5000  # Smaller sample for clean dendrogram
        if n_samples > DENDRO_SAMPLE:
            rng = np.random.RandomState(42)
            d_idx = rng.choice(n_samples, size=DENDRO_SAMPLE, replace=False)
            X_dendro = X_scaled[d_idx]
        else:
            X_dendro = X_scaled

        Z = linkage(X_dendro, method="ward")
        best_k = best["k"]

        fig, ax = plt.subplots(figsize=(12, 5))
        dendrogram(Z, truncate_mode="lastp", p=30, leaf_rotation=90,
                   leaf_font_size=9, show_leaf_counts=True, ax=ax,
                   color_threshold=Z[-(best_k - 1), 2],
                   above_threshold_color="#888")
        ax.axhline(y=Z[-(best_k - 1), 2], color="#E24B4A", linestyle="--",
                   linewidth=1.5, label=f"Cut at k={best_k}")
        ax.set_xlabel("Cluster Size", fontsize=12)
        ax.set_ylabel("Ward Distance", fontsize=12)
        ax.set_title("Hierarchical Clustering Dendrogram", fontsize=14, fontweight="bold")
        ax.legend(fontsize=10)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, "dendrogram.png"), dpi=300)
        plt.close()
    except Exception as e:
        print(f"    (Dendrogram skipped: {e})")

    # --- Cluster Centroid Comparison (what makes each segment different) ---
    # This is the "feature importance" equivalent for unsupervised learning.
    # Shows normalized centroid values per cluster — if a bar is tall on dwell
    # but short on TEU, that segment is defined by long dwell, not container size.
    print("    Generating centroid comparison...")
    if best.get("centroids") is not None:
        try:
            centroids = np.array(best["centroids"])
            n_clusters, n_features = centroids.shape

            # Get feature names (cleaned up for display)
            feature_names = []
            for r in results:
                if r.get("_feature_cols"):
                    feature_names = r["_feature_cols"]
                    break
            if not feature_names:
                feature_names = [f"Feature {i+1}" for i in range(n_features)]
            display_names = [n.replace("_log", " (log)").replace("_", " ").title()
                            for n in feature_names]

            fig, ax = plt.subplots(figsize=(10, 6))
            x = np.arange(n_features)
            width = 0.8 / n_clusters
            colors = plt.cm.Set2(np.linspace(0, 1, n_clusters))

            for i in range(n_clusters):
                offset = (i - n_clusters / 2 + 0.5) * width
                bars = ax.bar(x + offset, centroids[i], width, color=colors[i],
                             edgecolor="white", linewidth=0.5,
                             label=f"Segment {i}")

            ax.set_xlabel("Feature", fontsize=12)
            ax.set_ylabel("Standardized Centroid Value", fontsize=12)
            ax.set_title("What Makes Each Segment Different? (Cluster Centroids)",
                        fontsize=14, fontweight="bold")
            ax.set_xticks(x)
            ax.set_xticklabels(display_names, rotation=20, ha="right", fontsize=10)
            ax.legend(fontsize=9, loc="upper right")
            ax.axhline(y=0, color="#333", linewidth=0.8, linestyle="-")
            ax.grid(True, alpha=0.2, axis="y")
            plt.tight_layout()
            plt.savefig(os.path.join(charts_dir, "centroid_comparison.png"), dpi=300)
            plt.close()
        except Exception as e:
            print(f"    (Centroid comparison skipped: {e})")

    print(f"    Charts saved to {charts_dir}/")


# ---------------------------------------------------------------------------
# Part B: Yard Throughput Forecasting
# ---------------------------------------------------------------------------

def prepare_forecast_data(block_df):
    """Aggregate block-daily data to total terminal TEU per day."""
    block_df["date"] = pd.to_datetime(block_df["date"])
    daily = (block_df.groupby("date")["teu_occupied"]
             .sum().reset_index()
             .sort_values("date")
             .set_index("date"))

    # Fill missing dates
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_range).ffill()
    daily.index.name = "date"

    return daily


def forecast_exponential_smoothing(train, test, horizon, seasonal_period=7):
    """Simple exponential smoothing with trend and seasonality (Holt-Winters manual)."""
    from scipy.optimize import minimize

    y = train["teu_occupied"].values.astype(float)
    n = len(y)
    m = seasonal_period

    if n < 2 * m:
        # Not enough data for seasonal model — use simple exponential smoothing
        alpha = 0.3
        forecast = [y[0]]
        for t in range(1, n):
            forecast.append(alpha * y[t] + (1 - alpha) * forecast[-1])
        last_level = forecast[-1]
        future = [last_level] * (len(test) + horizon)
        return {
            "model": "SimpleExponentialSmoothing",
            "params": {"alpha": alpha},
            "train_fitted": forecast,
            "test_forecast": future[:len(test)],
            "future_forecast": future[:horizon],
        }

    # Holt-Winters Additive
    # Initialize
    level = np.mean(y[:m])
    trend = (np.mean(y[m:2*m]) - np.mean(y[:m])) / m
    seasonal = [y[i] - level for i in range(m)]

    alpha, beta, gamma = 0.2, 0.1, 0.1

    fitted = []
    for t in range(n):
        s_idx = t % m
        if t == 0:
            fitted.append(level + trend + seasonal[s_idx])
        else:
            prev_level = level
            level = alpha * (y[t] - seasonal[s_idx]) + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            seasonal[s_idx] = gamma * (y[t] - level) + (1 - gamma) * seasonal[s_idx]
            fitted.append(level + trend + seasonal[s_idx])

    # Forecast
    future_values = []
    for h in range(1, len(test) + horizon + 1):
        s_idx = (n + h - 1) % m
        future_values.append(level + h * trend + seasonal[s_idx])

    return {
        "model": "HoltWinters_Additive",
        "params": {"alpha": alpha, "beta": beta, "gamma": gamma,
                   "seasonal_period": m},
        "train_fitted": fitted,
        "test_forecast": future_values[:len(test)],
        "future_forecast": future_values[len(test):len(test) + horizon],
    }


def forecast_moving_average(train, test, horizon, window=7):
    """Seasonal moving average as ARIMA substitute when statsmodels unavailable."""
    y = train["teu_occupied"].values.astype(float)

    # Compute seasonal pattern (weekly)
    m = window
    seasonal = np.zeros(m)
    counts = np.zeros(m)
    for i, val in enumerate(y):
        seasonal[i % m] += val
        counts[i % m] += 1
    seasonal = seasonal / np.maximum(counts, 1)

    # Trend via rolling mean
    trend_window = min(14, len(y) // 2)
    trend = pd.Series(y).rolling(trend_window, min_periods=1).mean().values
    last_trend = trend[-1]
    trend_slope = (trend[-1] - trend[max(0, len(trend) - 14)]) / 14

    # Forecast
    all_forecast = []
    for h in range(len(test) + horizon):
        s_idx = (len(y) + h) % m
        pred = last_trend + h * trend_slope + (seasonal[s_idx] - np.mean(seasonal))
        all_forecast.append(max(0, pred))

    # Fitted values for training
    fitted = []
    for i in range(len(y)):
        s_idx = i % m
        t_val = trend[i]
        fitted.append(t_val + (seasonal[s_idx] - np.mean(seasonal)))

    return {
        "model": "SeasonalMovingAverage",
        "params": {"window": window, "trend_slope": round(trend_slope, 2)},
        "train_fitted": fitted,
        "test_forecast": all_forecast[:len(test)],
        "future_forecast": all_forecast[len(test):len(test) + horizon],
    }


def try_arima_forecast(train, test, horizon):
    """Attempt SARIMA if statsmodels is available."""
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing as SM_HW
        y = train["teu_occupied"].values.astype(float)

        model = SM_HW(y, trend="add", seasonal="add", seasonal_periods=7)
        fitted_model = model.fit(optimized=True, use_brute=True)
        forecast_values = fitted_model.forecast(len(test) + horizon)

        return {
            "model": "StatsModels_HoltWinters",
            "params": {
                "alpha": round(fitted_model.params.get("smoothing_level", 0), 4),
                "beta": round(fitted_model.params.get("smoothing_trend", 0), 4),
                "gamma": round(fitted_model.params.get("smoothing_seasonal", 0), 4),
            },
            "train_fitted": fitted_model.fittedvalues.tolist(),
            "test_forecast": forecast_values[:len(test)].tolist(),
            "future_forecast": forecast_values[len(test):len(test)+horizon].tolist(),
        }
    except ImportError:
        return None
    except Exception:
        return None


def compute_forecast_metrics(actual, predicted):
    """Compute MAPE, RMSE, MAE."""
    actual = np.array(actual, dtype=float)
    predicted = np.array(predicted, dtype=float)

    # Align lengths
    min_len = min(len(actual), len(predicted))
    actual = actual[:min_len]
    predicted = predicted[:min_len]

    # Remove zeros from MAPE calculation
    nonzero = actual != 0
    if nonzero.sum() > 0:
        mape = np.mean(np.abs((actual[nonzero] - predicted[nonzero])
                              / actual[nonzero])) * 100
    else:
        mape = np.nan

    rmse = np.sqrt(np.mean((actual - predicted) ** 2))
    mae = np.mean(np.abs(actual - predicted))

    return {
        "mape": round(mape, 2),
        "rmse": round(rmse, 2),
        "mae": round(mae, 2),
    }


def generate_forecast_chart(daily, train_end, test_actual, model1, model2,
                            best_model, horizon, output_dir):
    """Generate forecast chart showing train, test overlay, and future prediction.
    
    The chart has three visual zones:
    1. Training period (grey actual line)
    2. Test period (grey actual + colored predicted overlay — shows model fit)
    3. Future forecast (dashed line extending beyond data + confidence band)
    """
    charts_dir = os.path.join(output_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    best_fc = model1 if best_model == model1["model"] else model2

    fig, ax = plt.subplots(figsize=(12, 6))

    # --- Zone 1: Training period (actual data up to train_end) ---
    train_mask = daily.index <= train_end
    ax.plot(daily.index[train_mask], daily["teu_occupied"][train_mask],
            color="#333", linewidth=1, alpha=0.6, label="Actual (Train)")

    # --- Zone 2: Test period (actual + predicted overlay) ---
    test_dates = daily.index[daily.index > train_end][:len(test_actual)]
    if len(test_dates) > 0:
        # Actual test data
        ax.plot(test_dates, test_actual[:len(test_dates)],
                color="#333", linewidth=1, alpha=0.6)

        # Predicted test values (overlay — this is the key validation visual)
        test_predicted = best_fc["test_forecast"][:len(test_dates)]
        ax.plot(test_dates, test_predicted,
                color="#1D9E75", linewidth=2, alpha=0.9,
                label=f"Predicted — Test Period ({best_fc['model']})")

        # Train/test divider
        ax.axvline(x=train_end, color="#999", linestyle=":", alpha=0.6)
        ymax = daily["teu_occupied"].max() * 1.05
        ax.text(train_end, ymax * 0.97, "  Train │ Test →", fontsize=9,
                color="#999", va="top")

    # --- Zone 3: Future forecast (beyond the data) ---
    last_actual_date = test_dates[-1] if len(test_dates) > 0 else daily.index[-1]
    forecast_dates = pd.date_range(
        last_actual_date + pd.Timedelta(days=1),
        periods=horizon, freq="D"
    )

    fc_values = best_fc["future_forecast"][:horizon]
    ax.plot(forecast_dates, fc_values, color="#534AB7", linewidth=2,
            linestyle="--", label=f"Forecast — {horizon}-Day Ahead")

    # Confidence interval on future only
    fc_arr = np.array(fc_values)
    ax.fill_between(forecast_dates, fc_arr * 0.85, fc_arr * 1.15,
                    color="#534AB7", alpha=0.12, label="±15% CI")

    # Forecast start divider
    ax.axvline(x=last_actual_date, color="#534AB7", linestyle=":", alpha=0.4)

    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Total TEU in Yard", fontsize=12)
    ax.set_title(f"Yard Throughput Forecast — {horizon}-Day Horizon",
                 fontsize=14, fontweight="bold")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, "forecast_plot.png"), dpi=300)
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_segment_profiles(df_valid):
    """Build enriched segment profiles with categorical breakdowns."""
    profiles = []
    for seg in sorted(df_valid["cluster"].unique()):
        seg_data = df_valid[df_valid["cluster"] == seg]
        profile = {
            "cluster": int(seg),
            "count": int(len(seg_data)),
            "mean_dwell_days": round(seg_data["dwell_days"].mean(), 2),
            "median_dwell_days": round(seg_data["dwell_days"].median(), 2),
            "mean_teu": round(seg_data["teu_equivalent"].mean(), 2),
            "mean_storage_cost": round(seg_data["storage_cost_usd"].mean(), 2)
                if "storage_cost_usd" in seg_data.columns else 0,
        }
        # Dominant movement type
        if "movement_type" in seg_data.columns:
            mt = seg_data["movement_type"].value_counts()
            profile["dominant_movement"] = mt.index[0]
            profile["movement_pct"] = round(mt.iloc[0] / len(seg_data) * 100, 1)
        # Dominant container type
        if "container_type" in seg_data.columns:
            ct = seg_data["container_type"].value_counts()
            profile["dominant_container_type"] = ct.index[0]
            profile["container_type_pct"] = round(ct.iloc[0] / len(seg_data) * 100, 1)
        # Dominant flow path
        if "flow_path" in seg_data.columns:
            fp = seg_data["flow_path"].value_counts()
            profile["dominant_flow_path"] = fp.index[0]
        # Overstay rate within segment
        if "is_overstay" in seg_data.columns:
            profile["overstay_pct"] = round(seg_data["is_overstay"].mean() * 100, 1)
        profiles.append(profile)
    return profiles


def main():
    parser = argparse.ArgumentParser(
        description="Modelling & Validation (Stages 3–4)")
    parser.add_argument("--container-features", required=True)
    parser.add_argument("--block-features", required=True)
    parser.add_argument("--num-segments", type=int, default=4)
    parser.add_argument("--forecast-horizon", type=int, default=14)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--output-dir", default="data/model_outputs")
    args = parser.parse_args()

    np.random.seed(args.random_seed)
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, "charts"), exist_ok=True)

    print("=" * 60)
    print("STAGE 3: Modelling & Analysis")
    print("=" * 60)

    # ===== Part A: Clustering =====
    print("\n  Part A: Dwell Behaviour Clustering")
    print("  " + "-" * 40)

    df = pd.read_csv(args.container_features)
    X_scaled, df_valid, feature_cols, scaler = prepare_clustering_features(df)
    print(f"    Clustering features: {len(feature_cols)} dimensions, "
          f"{len(X_scaled)} containers")

    k_min = 2
    k_max = 10  # Always test full range so elbow/silhouette curves are complete
    k_range = range(k_min, k_max + 1)
    print(f"    Testing k = {list(k_range)}")

    cluster_results = run_clustering(X_scaled, k_range)
    # Attach feature names for centroid chart labelling
    for r in cluster_results:
        r["_feature_cols"] = feature_cols

    # Print comparison table
    print(f"\n    {'Algorithm':<15} {'k':<5} {'Silhouette':<12} {'C-H Index':<12} {'Inertia':<12}")
    print(f"    {'-'*56}")
    for r in cluster_results:
        inertia = f"{r['inertia']:.0f}" if r["inertia"] else "N/A"
        print(f"    {r['algorithm']:<15} {r['k']:<5} {r['silhouette_score']:<12.4f} "
              f"{r['calinski_harabasz']:<12.1f} {inertia:<12}")

    # ===== Stage 4: Validation & Selection =====
    print(f"\n{'='*60}")
    print("STAGE 4: Model/Result Validation")
    print("=" * 60)

    print("\n  Clustering validation:")
    best_cluster = select_best_clustering(cluster_results, df_valid)
    print(f"    Selected: {best_cluster['algorithm']} with k={best_cluster['k']}")
    print(f"    Silhouette: {best_cluster['silhouette_score']:.4f}")

    sil = best_cluster["silhouette_score"]
    if sil > 0.70:
        quality = "Strong structure"
    elif sil > 0.50:
        quality = "Reasonable structure"
    elif sil > 0.25:
        quality = "Weak but usable"
    else:
        quality = "⚠ No meaningful structure"
    print(f"    Interpretation: {quality}")

    if best_cluster.get("_warning"):
        print(f"    Warning: {best_cluster['_warning']}")

    # Segment profiles
    labels = np.array(best_cluster["labels"])
    df_valid = df_valid.copy()
    df_valid["cluster"] = labels

    print(f"\n    Segment profiles:")
    print(f"    {'Seg':<5} {'Count':<8} {'%':<7} {'Mean Dwell (d)':<16} {'Mean TEU':<10}")
    print(f"    {'-'*46}")
    for seg in sorted(df_valid["cluster"].unique()):
        seg_data = df_valid[df_valid["cluster"] == seg]
        count = len(seg_data)
        pct = count / len(df_valid) * 100
        mean_dwell = seg_data["dwell_days"].mean()
        mean_teu = seg_data["teu_equivalent"].mean()
        print(f"    {seg:<5} {count:<8} {pct:<7.1f} {mean_dwell:<16.1f} {mean_teu:<10.1f}")

    # Generate clustering charts
    generate_clustering_charts(cluster_results, X_scaled, best_cluster,
                               args.output_dir)

    # ===== Part B: Forecasting =====
    print(f"\n  Part B: Yard Throughput Forecasting")
    print("  " + "-" * 40)

    block_df = pd.read_csv(args.block_features)
    daily = prepare_forecast_data(block_df)
    print(f"    Time series: {len(daily)} daily observations")

    # Train/test split (80/20)
    split_idx = int(len(daily) * 0.8)
    train = daily.iloc[:split_idx]
    test = daily.iloc[split_idx:]
    print(f"    Train: {len(train)} days, Test: {len(test)} days")

    # Model 1: Holt-Winters (manual implementation)
    hw_result = forecast_exponential_smoothing(
        train, test, args.forecast_horizon)
    hw_metrics = compute_forecast_metrics(
        test["teu_occupied"].values, hw_result["test_forecast"])
    print(f"\n    {hw_result['model']}:")
    print(f"      MAPE: {hw_metrics['mape']:.1f}%  |  "
          f"RMSE: {hw_metrics['rmse']:.1f}  |  MAE: {hw_metrics['mae']:.1f}")

    # Model 2: Seasonal Moving Average (or statsmodels if available)
    arima_result = try_arima_forecast(train, test, args.forecast_horizon)
    if arima_result:
        ma_result = arima_result
    else:
        ma_result = forecast_moving_average(train, test, args.forecast_horizon)

    ma_metrics = compute_forecast_metrics(
        test["teu_occupied"].values, ma_result["test_forecast"])
    print(f"\n    {ma_result['model']}:")
    print(f"      MAPE: {ma_metrics['mape']:.1f}%  |  "
          f"RMSE: {ma_metrics['rmse']:.1f}  |  MAE: {ma_metrics['mae']:.1f}")

    # Select best forecasting model
    if hw_metrics["mape"] <= ma_metrics["mape"]:
        best_forecast_model = hw_result["model"]
        best_forecast_metrics = hw_metrics
    else:
        best_forecast_model = ma_result["model"]
        best_forecast_metrics = ma_metrics

    print(f"\n    Selected: {best_forecast_model} (MAPE: {best_forecast_metrics['mape']:.1f}%)")

    if best_forecast_metrics["mape"] > 30:
        print("    ⚠ WARNING: MAPE > 30% — forecast reliability is limited.")
        print("    Consider providing more historical data (6+ months).")

    # Generate forecast chart
    generate_forecast_chart(daily, train.index[-1],
                            test["teu_occupied"].values,
                            hw_result, ma_result,
                            best_forecast_model, args.forecast_horizon,
                            args.output_dir)

    # ===== Save all outputs =====
    # Strip large arrays for JSON storage
    cluster_output = {
        "all_results": [{k: v for k, v in r.items() if k != "labels"}
                        for r in cluster_results],
        "best": {
            "algorithm": best_cluster["algorithm"],
            "k": best_cluster["k"],
            "silhouette_score": best_cluster["silhouette_score"],
            "calinski_harabasz": best_cluster["calinski_harabasz"],
            "quality": quality,
        },
        "segment_profiles": _build_segment_profiles(df_valid),
    }

    forecast_output = {
        "model1": {"model": hw_result["model"], "metrics": hw_metrics,
                   "params": hw_result["params"],
                   "future_forecast": [round(v, 1) for v in hw_result["future_forecast"]]},
        "model2": {"model": ma_result["model"], "metrics": ma_metrics,
                   "params": ma_result["params"],
                   "future_forecast": [round(v, 1) for v in ma_result["future_forecast"]]},
        "best_model": best_forecast_model,
        "forecast_horizon_days": args.forecast_horizon,
    }

    validation_output = {
        "clustering": {
            "best_algorithm": best_cluster["algorithm"],
            "best_k": best_cluster["k"],
            "silhouette_score": best_cluster["silhouette_score"],
            "quality_interpretation": quality,
        },
        "forecasting": {
            "best_model": best_forecast_model,
            "mape": best_forecast_metrics["mape"],
            "rmse": best_forecast_metrics["rmse"],
            "mae": best_forecast_metrics["mae"],
        },
    }

    # Save
    with open(os.path.join(args.output_dir, "cluster_results.json"), "w") as f:
        json.dump(cluster_output, f, indent=2, default=str)

    with open(os.path.join(args.output_dir, "forecast_results.json"), "w") as f:
        json.dump(forecast_output, f, indent=2, default=str)

    with open(os.path.join(args.output_dir, "validation_metrics.json"), "w") as f:
        json.dump(validation_output, f, indent=2, default=str)

    # Save cluster labels to CSV for report generation
    df_valid[["container_id", "cluster"]].to_csv(
        os.path.join(args.output_dir, "cluster_labels.csv"), index=False)

    print(f"\n  All outputs saved to {args.output_dir}/")
    print("  ✓ Modelling & validation complete. Proceed to Stage 5 (LLM) & Stage 6.")


if __name__ == "__main__":
    main()
