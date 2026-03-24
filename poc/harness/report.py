"""Comparison tables and export (CSV, LaTeX, JSON)."""

from __future__ import annotations

import csv
import io
import json

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .scoring import compute_approach_scores, normalize_and_aggregate
from .storage import load_all_runs


def generate_report(
    fmt: str = "table", output_path: str | None = None, dry_run: bool = False,
) -> str:
    """Generate a comparison report in the specified format.

    For 'table' format, prints colored output directly to the terminal and
    returns empty string. For file output, writes a plain-text version.
    """
    runs = load_all_runs(dry_run=dry_run, include_dry=dry_run)
    approach_metrics = compute_approach_scores(runs)
    final_scores = normalize_and_aggregate(approach_metrics)

    if fmt == "table":
        plain = _format_table(final_scores, runs)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(plain)
        return ""
    elif fmt == "csv":
        text = _format_csv(final_scores)
    elif fmt == "json":
        text = json.dumps(final_scores, indent=2)
    elif fmt == "latex":
        text = _format_latex(final_scores)
    else:
        text = f"Unknown format: {fmt}"

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

    return text


# -- Color helpers -------------------------------------------------------------

def _score_color(value: float, thresholds: tuple[float, float] = (0.4, 0.7)) -> str:
    """Return a rich color name based on value (0-1 scale)."""
    low, high = thresholds
    if value >= high:
        return "green"
    if value >= low:
        return "yellow"
    return "red"


def _pct_color(pct: float) -> str:
    """Color for a 0-100% rate."""
    if pct >= 80:
        return "green"
    if pct >= 50:
        return "yellow"
    return "red"


def _colored(value: str, color: str) -> Text:
    return Text(value, style=color)


def _rank_column(scores: dict, key: str, reverse: bool = False) -> dict[str, str]:
    """Return best/worst styling per approach for a given key.

    reverse=True means lower raw value is better (cost, time, fails).
    Tied values get the same color.
    """
    vals = {a: s[key] for a, s in scores.items()}
    sorted_a = sorted(vals, key=vals.get, reverse=not reverse)
    best_val = vals[sorted_a[0]]
    worst_val = vals[sorted_a[-1]]
    styles = {}
    for a in sorted_a:
        v = vals[a]
        if v == best_val:
            styles[a] = "bold green"
        elif v == worst_val:
            styles[a] = "red"
        else:
            styles[a] = "yellow"
    return styles


# -- Rich table formatter ------------------------------------------------------

def _format_table(scores: dict, runs: list[dict]) -> str:
    """Print colored table to terminal, return plain text version for file output."""
    if not scores:
        Console().print("[dim]No results to report.[/]")
        return "No results to report."

    renderables = _build_table_renderables(scores, runs)

    # Print colored to terminal
    console = Console()
    for r in renderables:
        console.print(r)

    # Capture plain text for file output
    plain = Console(record=True, file=io.StringIO(), width=120)
    for r in renderables:
        plain.print(r)
    return plain.export_text()


def _build_table_renderables(scores: dict, runs: list[dict]) -> list:
    """Build all rich renderables for the report."""
    from rich.rule import Rule
    from rich.text import Text as RichText

    parts: list = []

    # Header
    models_used = sorted({r.get("model", "") for r in runs if r.get("model")})
    model_str = ", ".join(models_used) if models_used else "unknown"
    parts.append(RichText())
    parts.append(Rule("[bold]PyOps Approach Comparison", style="bright_blue"))
    parts.append(RichText(f"  Model: {model_str}    Runs: {len(runs)}"))
    parts.append(RichText())

    # -- Summary table --
    rank_acc = _rank_column(scores, "avg_accuracy")
    rank_cost = _rank_column(scores, "avg_cost", reverse=True)
    rank_time = _rank_column(scores, "avg_time", reverse=True)
    rank_calls = _rank_column(scores, "avg_calls", reverse=True)
    rank_tokens = _rank_column(scores, "avg_tokens", reverse=True)
    rank_fail = _rank_column(scores, "total_failures", reverse=True)
    rank_s = _rank_column(scores, "S")

    summary = Table(
        title="Summary", title_style="bold", show_lines=False,
        border_style="bright_blue", padding=(0, 1),
    )
    summary.add_column("Approach", style="bold cyan", min_width=20)
    summary.add_column("Runs", justify="right")
    summary.add_column("Accuracy", justify="right")
    summary.add_column("Cost ($)", justify="right")
    summary.add_column("Time (s)", justify="right")
    summary.add_column("LLM Calls", justify="right")
    summary.add_column("Tokens", justify="right")
    summary.add_column("Fails", justify="right")
    summary.add_column("S Score", justify="right", style="bold")

    for approach in sorted(scores):
        s = scores[approach]
        summary.add_row(
            approach,
            str(s["n_runs"]),
            Text(f"{s['avg_accuracy']:.1f}", style=rank_acc[approach]),
            Text(f"{s['avg_cost']:.4f}", style=rank_cost[approach]),
            Text(f"{s['avg_time']:.1f}", style=rank_time[approach]),
            Text(f"{s['avg_calls']:.0f}", style=rank_calls[approach]),
            Text(f"{s['avg_tokens']:,.0f}", style=rank_tokens[approach]),
            Text(f"{s['total_failures']}", style=rank_fail[approach]),
            Text(f"{s['S']:.4f}", style=rank_s[approach]),
        )

    parts.append(summary)
    parts.append(RichText())

    # -- Normalized scores table --
    norm_table = Table(
        title="Normalized Scores",
        title_style="bold",
        show_lines=False,
        border_style="dim",
        padding=(0, 1),
    )
    norm_table.add_column("Approach", style="bold cyan", min_width=20)
    for col in ("A_norm", "C_norm", "T_norm", "F_norm", "S"):
        norm_table.add_column(col, justify="right")

    for approach in sorted(scores):
        s = scores[approach]
        norm_table.add_row(
            approach,
            _colored(f"{s['A_norm']:.4f}", _score_color(s["A_norm"])),
            _colored(f"{s['C_norm']:.4f}", _score_color(s["C_norm"])),
            _colored(f"{s['T_norm']:.4f}", _score_color(s["T_norm"])),
            _colored(f"{s['F_norm']:.4f}", _score_color(s["F_norm"])),
            Text(f"{s['S']:.4f}", style="bold " + _score_color(s["S"])),
        )

    parts.append(norm_table)
    parts.append(RichText())

    # -- Per-app breakdown table --
    by_approach_app: dict[tuple[str, str], list] = {}
    for r in runs:
        key = (r["approach"], r["app"])
        by_approach_app.setdefault(key, []).append(r)

    all_apps = sorted({r["app"] for r in runs})
    sorted_approaches = sorted(scores)

    app_table = Table(
        title="Per-App Pass Rates  [dim](s1/s2/s3/s4)[/]",
        title_style="bold",
        show_lines=True,
        border_style="dim",
        padding=(0, 1),
    )
    app_table.add_column("App", style="bold", min_width=16)
    for approach in sorted_approaches:
        app_table.add_column(approach, justify="center", min_width=14)

    for app in all_apps:
        row: list[Text | str] = [app]
        for approach in sorted_approaches:
            key = (approach, app)
            app_runs = by_approach_app.get(key, [])
            if not app_runs:
                row.append(Text("-", style="dim"))
                continue

            n = len(app_runs)
            pcts = [
                sum(1 for r in app_runs if r[field]) / n * 100
                for field in ("s1_build", "s2_container_starts",
                              "s3_tests_pass", "s4_deep_validation")
            ]

            cell = Text()
            for i, pct in enumerate(pcts):
                color = _pct_color(pct)
                cell.append(f"{pct:3.0f}", style=color)
                if i < 3:
                    cell.append("/", style="dim")
            row.append(cell)

        app_table.add_row(*row)

    parts.append(app_table)

    return parts


def _format_csv(scores: dict) -> str:
    """Format scores as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "approach",
            "n_runs",
            "avg_accuracy",
            "avg_cost",
            "avg_time",
            "avg_calls",
            "avg_tokens",
            "total_failures",
            "A_norm",
            "C_norm",
            "T_norm",
            "F_norm",
            "S",
        ]
    )
    for approach in sorted(scores):
        s = scores[approach]
        writer.writerow(
            [
                approach,
                s["n_runs"],
                s["avg_accuracy"],
                s["avg_cost"],
                s["avg_time"],
                s["avg_calls"],
                s["avg_tokens"],
                s["total_failures"],
                s["A_norm"],
                s["C_norm"],
                s["T_norm"],
                s["F_norm"],
                s["S"],
            ]
        )
    return output.getvalue()


def _format_latex(scores: dict) -> str:
    """Format scores as a LaTeX table."""
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Approach Comparison Results}",
        r"\label{tab:approach-comparison}",
        r"\begin{tabular}{lrrrrrrrrrrrr}",
        r"\toprule",
        r"Approach & Runs & Accuracy & Cost (\$) & Time (s) & Calls & Tokens & Fails "
        r"& $A_n$ & $C_n$ & $T_n$ & $F_n$ & $S$ \\",
        r"\midrule",
    ]

    for approach in sorted(scores):
        s = scores[approach]
        lines.append(
            f"{approach} & {s['n_runs']} & {s['avg_accuracy']:.1f} & "
            f"{s['avg_cost']:.4f} & {s['avg_time']:.1f} & "
            f"{s['avg_calls']:.1f} & {s['avg_tokens']:.0f} & "
            f"{s['total_failures']} & "
            f"{s['A_norm']:.3f} & {s['C_norm']:.3f} & "
            f"{s['T_norm']:.3f} & {s['F_norm']:.3f} & {s['S']:.3f} \\\\"
        )

    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )

    return "\n".join(lines)
