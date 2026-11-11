"""Black-box acceptance tests for SPEC-32: ML Model ETA Error Probability Distribution Plots.

These tests strictly verify artifact outputs, summary tables, quantile distributions,
and run manifests against the formal requirements and acceptance criteria in:
docs/specs/32_ML_EVALUATION_ERROR_DISTRIBUTION_PLOTS_SPEC.md.

Per AGENTS.md:
- Black-box testing only.
- No access to or assertion on Coder implementation code.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIGURES_DIR = PROJECT_ROOT / "docs" / "figures" / "ml_evaluation"
REPORTS_DIR = PROJECT_ROOT / "reports" / "evaluation" / "ml_error_distribution"

EXPECTED_SINGLE_FIGURES = [
    "fig_error_dist_k01_time_sec.png",
    "fig_error_dist_k01_percent.png",
    "fig_error_dist_k02_time_sec.png",
    "fig_error_dist_k02_percent.png",
    "fig_error_dist_k05_time_sec.png",
    "fig_error_dist_k05_percent.png",
    "fig_error_dist_k10_time_sec.png",
    "fig_error_dist_k10_percent.png",
]
EXPECTED_GRID_FIGURE = "fig_error_dist_combined_grid_4x2.png"

EXPECTED_COUNTS_BY_K = {
    1: 863984,
    2: 124490,
    5: 47128,
    10: 50040,
}
EXPECTED_TOTAL_N = sum(EXPECTED_COUNTS_BY_K.values())  # 1,085,642


def _compute_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest().lower()


class TestSpec32FiguresArtifacts:
    """Verifies existence, format, dimensions, and file size of all generated figures."""

    @pytest.mark.parametrize("filename", EXPECTED_SINGLE_FIGURES)
    def test_single_figure_exists_and_valid(self, filename: str) -> None:
        fig_path = FIGURES_DIR / filename
        assert fig_path.exists(), f"Figure file missing: {fig_path}"

        # File size must be greater than 50 KB
        file_size = fig_path.stat().st_size
        assert file_size > 50_000, f"Figure {filename} is too small ({file_size} bytes, expected > 50KB)"

        # Must have valid PNG magic bytes
        with fig_path.open("rb") as f:
            header = f.read(8)
            assert header == b"\x89PNG\r\n\x1a\n", f"Figure {filename} has invalid PNG signature"

        # Must open cleanly in PIL
        with Image.open(fig_path) as img:
            assert img.format == "PNG", f"Expected PNG format, got {img.format}"
            width, height = img.size
            assert width >= 2000, f"Expected high-res width >= 2000px, got {width}"
            assert height >= 1200, f"Expected high-res height >= 1200px, got {height}"

            # DPI verification (spec requires minimum 300 DPI)
            dpi = img.info.get("dpi")
            if dpi is not None:
                assert dpi[0] >= 295.0, f"Expected ~300 DPI, got {dpi[0]}"

    def test_combined_grid_dashboard_figure(self) -> None:
        grid_path = FIGURES_DIR / EXPECTED_GRID_FIGURE
        assert grid_path.exists(), f"Combined grid figure missing: {grid_path}"

        file_size = grid_path.stat().st_size
        assert file_size > 500_000, f"Combined grid is too small ({file_size} bytes, expected > 500KB)"

        with Image.open(grid_path) as img:
            assert img.format == "PNG"
            width, height = img.size
            assert width >= 4000, f"Expected grid dashboard width >= 4000px, got {width}"
            assert height >= 5000, f"Expected grid dashboard height >= 5000px, got {height}"


class TestSpec32SummaryTable:
    """Verifies summary table structure, sample counts, and monotonicity constraints."""

    @pytest.fixture(scope="class")
    @classmethod
    def summary_rows(cls) -> list[dict[str, str]]:
        csv_path = REPORTS_DIR / "ml_error_distribution_summary_table.csv"
        assert csv_path.exists(), f"Summary table CSV missing: {csv_path}"

        with csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 4, f"Expected exactly 4 rows (K=1, 2, 5, 10), got {len(rows)}"
        return rows

    def test_summary_markdown_file_exists(self) -> None:
        md_path = REPORTS_DIR / "ml_error_distribution_summary_table.md"
        assert md_path.exists(), f"Summary markdown missing: {md_path}"
        assert md_path.stat().st_size > 500, "Summary markdown is too small"
        content = md_path.read_text(encoding="utf-8")
        for k in ["K=1", "K=2", "K=5", "K=10"]:
            assert k in content, f"Missing {k} in summary markdown"

    def test_summary_table_columns_present(self, summary_rows: list[dict[str, str]]) -> None:
        required_cols = {
            "horizon_case",
            "sample_count_N",
            "actual_eta_median_sec",
            "pred_eta_median_sec",
            "time_error_mean_sec",
            "time_error_std_sec",
            "time_error_median_sec",
            "mae_sec",
            "medae_sec",
            "pct_error_mean",
            "pct_error_std",
            "pct_error_median",
            "wape_pct",
            "pct_early_arrivals",
            "pct_late_arrivals",
            "within_tolerance_1m_pct",
            "within_tolerance_2m_pct",
        }
        for row in summary_rows:
            missing = required_cols - set(row.keys())
            assert not missing, f"Missing columns in summary row: {missing}"

    def test_sample_counts_match_specification(self, summary_rows: list[dict[str, str]]) -> None:
        total_n = 0
        for row in summary_rows:
            case_str = row["horizon_case"]
            k_val = int(case_str.replace("K=", ""))
            assert k_val in EXPECTED_COUNTS_BY_K, f"Unexpected horizon: {case_str}"

            actual_n = int(row["sample_count_N"])
            expected_n = EXPECTED_COUNTS_BY_K[k_val]
            assert actual_n == expected_n, f"For {case_str}: expected N={expected_n}, got {actual_n}"
            total_n += actual_n

        assert total_n == EXPECTED_TOTAL_N, f"Total test N={total_n}, expected {EXPECTED_TOTAL_N}"

    def test_mae_increases_monotonically_with_k(self, summary_rows: list[dict[str, str]]) -> None:
        mae_by_k: dict[int, float] = {}
        for row in summary_rows:
            k = int(row["horizon_case"].replace("K=", ""))
            mae_by_k[k] = float(row["mae_sec"])

        # MAE(K=1) < MAE(K=2) < MAE(K=5) < MAE(K=10)
        assert mae_by_k[1] < mae_by_k[2], f"MAE violation: K=1 ({mae_by_k[1]}) >= K=2 ({mae_by_k[2]})"
        assert mae_by_k[2] < mae_by_k[5], f"MAE violation: K=2 ({mae_by_k[2]}) >= K=5 ({mae_by_k[5]})"
        assert mae_by_k[5] < mae_by_k[10], f"MAE violation: K=5 ({mae_by_k[5]}) >= K=10 ({mae_by_k[10]})"

    def test_accuracy_tolerance_decreases_with_k(self, summary_rows: list[dict[str, str]]) -> None:
        acc_1m_by_k: dict[int, float] = {}
        acc_2m_by_k: dict[int, float] = {}
        for row in summary_rows:
            k = int(row["horizon_case"].replace("K=", ""))
            acc_1m_by_k[k] = float(row["within_tolerance_1m_pct"])
            acc_2m_by_k[k] = float(row["within_tolerance_2m_pct"])

        # Acc(K=1) > Acc(K=2) > Acc(K=5) > Acc(K=10)
        assert acc_1m_by_k[1] > acc_1m_by_k[2] > acc_1m_by_k[5] > acc_1m_by_k[10], (
            f"1-min accuracy monotonicity violation: {acc_1m_by_k}"
        )
        assert acc_2m_by_k[1] > acc_2m_by_k[2] > acc_2m_by_k[5] > acc_2m_by_k[10], (
            f"2-min accuracy monotonicity violation: {acc_2m_by_k}"
        )

    def test_time_error_std_increases_with_k(self, summary_rows: list[dict[str, str]]) -> None:
        std_by_k: dict[int, float] = {}
        for row in summary_rows:
            k = int(row["horizon_case"].replace("K=", ""))
            std_by_k[k] = float(row["time_error_std_sec"])

        assert std_by_k[1] < std_by_k[2] < std_by_k[5] < std_by_k[10], (
            f"Standard deviation monotonicity violation: {std_by_k}"
        )

    def test_wape_and_arrival_percentages(self, summary_rows: list[dict[str, str]]) -> None:
        for row in summary_rows:
            case = row["horizon_case"]
            wape = float(row["wape_pct"])
            assert wape > 0.0, f"{case}: WAPE must be > 0%, got {wape}"
            assert wape < 100.0, f"{case}: WAPE should be < 100%, got {wape}"

            early_pct = float(row["pct_early_arrivals"])
            late_pct = float(row["pct_late_arrivals"])
            total_arrival_pct = early_pct + late_pct
            assert 99.0 <= total_arrival_pct <= 100.0, (
                f"{case}: Early% + Late% should sum to ~100%, got {total_arrival_pct}"
            )


class TestSpec32QuantilesTable:
    """Verifies quantile monotonicity and sign invariance across all horizon cases."""

    @pytest.fixture(scope="class")
    @classmethod
    def quantile_rows(cls) -> list[dict[str, str]]:
        csv_path = REPORTS_DIR / "ml_error_distribution_quantiles.csv"
        assert csv_path.exists(), f"Quantiles CSV missing: {csv_path}"

        with csv_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 8, f"Expected 8 rows (4 K cases x 2 metrics), got {len(rows)}"
        return rows

    def test_strictly_increasing_quantiles_on_all_rows(self, quantile_rows: list[dict[str, str]]) -> None:
        quantile_keys = ["P1", "P5", "P10", "P25", "P50", "P75", "P90", "P95", "P99"]
        for row in quantile_rows:
            case_id = f"{row['horizon_case']}-{row['metric_variable']}"
            vals = [float(row[k]) for k in quantile_keys]

            for idx in range(len(vals) - 1):
                assert vals[idx] < vals[idx + 1], (
                    f"Quantile monotonicity violated for {case_id}: "
                    f"{quantile_keys[idx]} ({vals[idx]}) >= {quantile_keys[idx+1]} ({vals[idx+1]})"
                )

    def test_zero_crossing_tail_bounds(self, quantile_rows: list[dict[str, str]]) -> None:
        """P10 must be negative (early arrival tail) and P90 must be positive (late arrival tail)."""
        for row in quantile_rows:
            case_id = f"{row['horizon_case']}-{row['metric_variable']}"
            p10 = float(row["P10"])
            p90 = float(row["P90"])
            assert p10 < 0.0, f"{case_id}: P10 must be < 0 (early arrival region), got {p10}"
            assert p90 > 0.0, f"{case_id}: P90 must be > 0 (late arrival region), got {p90}"

    def test_iqr_consistency(self, quantile_rows: list[dict[str, str]]) -> None:
        for row in quantile_rows:
            case_id = f"{row['horizon_case']}-{row['metric_variable']}"
            p25 = float(row["P25"])
            p75 = float(row["P75"])
            iqr = float(row["IQR"])
            computed_iqr = p75 - p25
            assert abs(iqr - computed_iqr) < 0.05, (
                f"{case_id}: Reported IQR ({iqr}) doesn't match P75-P25 ({computed_iqr})"
            )


class TestSpec32ManifestIntegrity:
    """Verifies evaluation run manifest integrity, SHA256 checksums, and model metadata."""

    @pytest.fixture(scope="class")
    @classmethod
    def manifest(cls) -> dict:
        manifest_path = REPORTS_DIR / "evaluation_run_manifest.json"
        assert manifest_path.exists(), f"Manifest file missing: {manifest_path}"
        with manifest_path.open(encoding="utf-8") as f:
            return json.load(f)

    def test_manifest_metadata_and_features_count(self, manifest: dict) -> None:
        assert manifest.get("features_count") == 53, f"Expected 53 features, got {manifest.get('features_count')}"
        features_list = manifest.get("features_list", [])
        assert len(features_list) == 53, f"Expected 53 features in list, got {len(features_list)}"
        assert len(set(features_list)) == 53, "Duplicate feature names found in manifest"

        assert manifest.get("routes_evaluated") == 47, f"Expected 47 routes, got {manifest.get('routes_evaluated')}"
        assert manifest.get("target_horizons") == [1, 2, 5, 10]
        assert manifest.get("total_test_observations") == EXPECTED_TOTAL_N

    def test_manifest_model_and_metadata_sha256(self, manifest: dict) -> None:
        model_path = Path(manifest["model_file"])
        assert model_path.exists(), f"Model file referenced in manifest does not exist: {model_path}"
        actual_model_sha256 = _compute_sha256(model_path)
        assert manifest["model_sha256"].lower() == actual_model_sha256, (
            f"Model SHA256 mismatch: manifest={manifest['model_sha256']}, actual={actual_model_sha256}"
        )

        metadata_path = Path(manifest["metadata_file"])
        assert metadata_path.exists(), f"Metadata file referenced in manifest does not exist: {metadata_path}"
        actual_meta_sha256 = _compute_sha256(metadata_path)
        assert manifest["metadata_sha256"].lower() == actual_meta_sha256, (
            f"Metadata SHA256 mismatch: manifest={manifest['metadata_sha256']}, actual={actual_meta_sha256}"
        )

    def test_manifest_lists_all_generated_artifacts(self, manifest: dict) -> None:
        fig_list = manifest.get("figures_generated", [])
        for expected_fig in EXPECTED_SINGLE_FIGURES + [EXPECTED_GRID_FIGURE]:
            assert expected_fig in fig_list, f"Missing {expected_fig} in manifest figures_generated"

        table_list = manifest.get("tables_generated", [])
        for expected_tbl in [
            "ml_error_distribution_summary_table.csv",
            "ml_error_distribution_summary_table.md",
            "ml_error_distribution_quantiles.csv",
        ]:
            assert expected_tbl in table_list, f"Missing {expected_tbl} in manifest tables_generated"
