"""Scoring formulas from thesis: accuracy, cost, time, stability + normalization."""

from __future__ import annotations

from .storage import load_all_runs


def accuracy_score(s1: bool, s2: bool, s3: bool, s4: bool) -> float:
    """Compute accuracy for a single run: (s1*15 + s2*20 + s3*30 + s4*35)."""
    return int(s1) * 15 + int(s2) * 20 + int(s3) * 30 + int(s4) * 35


def compute_approach_scores(runs: list[dict] | None = None) -> dict:
    """Compute aggregated scores per approach.

    Returns {approach: {metric: value, ...}, ...}
    """
    if runs is None:
        runs = load_all_runs()
    if not runs:
        return {}

    # Group runs by approach
    by_approach: dict[str, list[dict]] = {}
    for r in runs:
        by_approach.setdefault(r["approach"], []).append(r)

    approach_metrics = {}
    for approach, approach_runs in by_approach.items():
        accuracies = [
            accuracy_score(
                r["s1_build"],
                r["s2_container_starts"],
                r["s3_tests_pass"],
                r["s4_deep_validation"],
            )
            for r in approach_runs
        ]
        avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0

        costs = [r["cost_usd"] for r in approach_runs]
        avg_cost = sum(costs) / len(costs) if costs else 0

        times = [r["t_total"] for r in approach_runs]
        avg_time = sum(times) / len(times) if times else 0

        build_times = [r["t_build"] for r in approach_runs]
        avg_build_time = (
            sum(build_times) / len(build_times) if build_times else 0
        )

        n_build_failures = sum(1 for r in approach_runs if r["f_build"])
        n_run_failures = sum(1 for r in approach_runs if r["f_run"])
        n_push_failures = sum(1 for r in approach_runs if r["f_push"])
        total_failures = n_build_failures + n_run_failures + n_push_failures

        calls = [r.get("n_calls", 0) for r in approach_runs]
        avg_calls = sum(calls) / len(calls) if calls else 0

        tokens = [r.get("n_tokens", 0) for r in approach_runs]
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0

        approach_metrics[approach] = {
            "n_runs": len(approach_runs),
            "avg_accuracy": avg_accuracy,
            "avg_cost": avg_cost,
            "avg_time": avg_time,
            "avg_build_time": avg_build_time,
            "avg_calls": avg_calls,
            "avg_tokens": avg_tokens,
            "n_build_failures": n_build_failures,
            "n_run_failures": n_run_failures,
            "n_push_failures": n_push_failures,
            "total_failures": total_failures,
        }

    return approach_metrics


def normalize_and_aggregate(approach_metrics: dict) -> dict:
    """Apply min-max normalization and compute final aggregated score S.

    S = 0.70*A_norm + 0.20*C_norm + 0.05*T_norm + 0.05*F_norm

    Higher = better for all normalized metrics.
    """
    if not approach_metrics:
        return {}

    approaches = list(approach_metrics.keys())

    # Accuracy: higher = better (direct)
    accuracies = {a: approach_metrics[a]["avg_accuracy"] for a in approaches}
    a_norm = _min_max_normalize(accuracies, invert=False)

    # Cost: lower = better (invert)
    costs = {a: approach_metrics[a]["avg_cost"] for a in approaches}
    c_norm = _min_max_normalize(costs, invert=True)

    # Time complexity: 0.9*(1/T_total) + 0.1*(1/T_build), then normalize
    time_scores = {}
    for a in approaches:
        t_total = approach_metrics[a]["avg_time"]
        t_build = approach_metrics[a]["avg_build_time"]
        inv_total = 1.0 / t_total if t_total > 0 else 0
        inv_build = 1.0 / t_build if t_build > 0 else 0
        time_scores[a] = 0.9 * inv_total + 0.1 * inv_build
    t_norm = _min_max_normalize(time_scores, invert=False)

    # Stability (failures): lower = better (invert)
    failures = {a: approach_metrics[a]["total_failures"] for a in approaches}
    f_norm = _min_max_normalize(failures, invert=True)

    results = {}
    for a in approaches:
        s = (
            0.70 * a_norm[a]
            + 0.20 * c_norm[a]
            + 0.05 * t_norm[a]
            + 0.05 * f_norm[a]
        )
        results[a] = {
            **approach_metrics[a],
            "A_norm": round(a_norm[a], 4),
            "C_norm": round(c_norm[a], 4),
            "T_norm": round(t_norm[a], 4),
            "F_norm": round(f_norm[a], 4),
            "S": round(s, 4),
        }

    return results


def _min_max_normalize(
    values: dict[str, float], invert: bool = False
) -> dict[str, float]:
    """Min-max normalize to [0, 1]. If invert, lower raw = higher normalized."""
    vals = list(values.values())
    v_min = min(vals)
    v_max = max(vals)

    if v_max == v_min:
        return {k: 1.0 for k in values}

    result = {}
    for k, v in values.items():
        if invert:
            result[k] = (v_max - v) / (v_max - v_min)
        else:
            result[k] = (v - v_min) / (v_max - v_min)

    return result
