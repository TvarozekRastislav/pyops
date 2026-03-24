"""Dual storage: JSON files + SQLite."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .metrics import RawRunMetrics

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# Real run storage
RUNS_DIR = RESULTS_DIR / "runs"
DB_PATH = RESULTS_DIR / "pyops_results.db"

# Dry-run storage (separate folder + database)
DRY_RUNS_DIR = RESULTS_DIR / "dry_runs"
DRY_DB_PATH = RESULTS_DIR / "pyops_dry_results.db"


def _paths(dry_run: bool = False) -> tuple[Path, Path]:
    """Return (runs_dir, db_path) for the given mode."""
    if dry_run:
        return DRY_RUNS_DIR, DRY_DB_PATH
    return RUNS_DIR, DB_PATH

_METRIC_COLUMNS = [
    "run_id",
    "approach",
    "app",
    "repetition",
    "model",
    "timestamp",
    "s1_build",
    "s2_container_starts",
    "s3_tests_pass",
    "s4_deep_validation",
    "cost_usd",
    "n_calls",
    "n_tokens",
    "t_total",
    "t_build",
    "f_build",
    "f_run",
    "f_push",
    "dockerfile_content",
    "build_log",
    "container_logs",
    "test_details",
]

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    approach TEXT NOT NULL,
    app TEXT NOT NULL,
    repetition INTEGER NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL,
    s1_build INTEGER NOT NULL DEFAULT 0,
    s2_container_starts INTEGER NOT NULL DEFAULT 0,
    s3_tests_pass INTEGER NOT NULL DEFAULT 0,
    s4_deep_validation INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    n_calls INTEGER NOT NULL DEFAULT 0,
    n_tokens INTEGER NOT NULL DEFAULT 0,
    t_total REAL NOT NULL DEFAULT 0.0,
    t_build REAL NOT NULL DEFAULT 0.0,
    f_build INTEGER NOT NULL DEFAULT 0,
    f_run INTEGER NOT NULL DEFAULT 0,
    f_push INTEGER NOT NULL DEFAULT 0,
    dockerfile_content TEXT NOT NULL DEFAULT '',
    build_log TEXT NOT NULL DEFAULT '',
    container_logs TEXT NOT NULL DEFAULT '',
    test_details TEXT NOT NULL DEFAULT ''
)
"""

_BOOL_FIELDS = (
    "s1_build",
    "s2_container_starts",
    "s3_tests_pass",
    "s4_deep_validation",
    "f_build",
    "f_run",
    "f_push",
)


def _ensure_dirs(runs_dir: Path) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)


def _get_db(dry_run: bool = False) -> sqlite3.Connection:
    runs_dir, db_path = _paths(dry_run)
    _ensure_dirs(runs_dir)
    conn = sqlite3.connect(str(db_path))
    conn.execute(_CREATE_TABLE)
    # Migrate: add model column if missing (for pre-existing databases)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "model" not in existing:
        conn.execute("ALTER TABLE runs ADD COLUMN model TEXT NOT NULL DEFAULT ''")
    conn.commit()
    return conn


def save_run(metrics: RawRunMetrics, dry_run: bool = False) -> None:
    """Save a run to both JSON and SQLite."""
    _save_json(metrics, dry_run=dry_run)
    _save_sqlite(metrics, dry_run=dry_run)


def _save_json(metrics: RawRunMetrics, dry_run: bool = False) -> None:
    runs_dir, _ = _paths(dry_run)
    run_dir = runs_dir / metrics.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "metrics.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(metrics), f, indent=2)


def _save_sqlite(metrics: RawRunMetrics, dry_run: bool = False) -> None:
    conn = _get_db(dry_run=dry_run)
    data = asdict(metrics)
    for key in _BOOL_FIELDS:
        data[key] = int(data[key])
    columns = ", ".join(_METRIC_COLUMNS)
    placeholders = ", ".join("?" for _ in _METRIC_COLUMNS)
    values = [data[col] for col in _METRIC_COLUMNS]
    conn.execute(
        f"INSERT OR REPLACE INTO runs ({columns}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    conn.close()


def load_all_runs(dry_run: bool = False, include_dry: bool = False) -> list[dict]:
    """Load all runs from SQLite.

    Args:
        dry_run: If True, load from dry-run storage only.
        include_dry: If True (and dry_run is True), merge real + dry-run data.
    """
    def _load_from_db(is_dry: bool) -> list[dict]:
        conn = _get_db(dry_run=is_dry)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM runs ORDER BY timestamp").fetchall()
        conn.close()
        result = []
        for row in rows:
            d = dict(row)
            for key in _BOOL_FIELDS:
                d[key] = bool(d[key])
            result.append(d)
        return result

    if dry_run and include_dry:
        # Merge: real runs first, then dry runs
        return _load_from_db(False) + _load_from_db(True)
    return _load_from_db(dry_run)


def load_run(run_id: str, dry_run: bool = False) -> dict | None:
    """Load a single run from SQLite."""
    conn = _get_db(dry_run=dry_run)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    for key in _BOOL_FIELDS:
        d[key] = bool(d[key])
    return d


def clear_all_runs(dry_run: bool = False) -> int:
    """Delete all run directories and clear the SQLite table. Returns count deleted."""
    import shutil

    runs_dir, _ = _paths(dry_run)
    count = 0
    if runs_dir.exists():
        for child in runs_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
                count += 1
            elif child.is_file():
                child.unlink()
                count += 1

    conn = _get_db(dry_run=dry_run)
    conn.execute("DELETE FROM runs")
    conn.commit()
    conn.close()
    return count


def count_runs(dry_run: bool = False) -> dict:
    """Return run counts grouped by approach and app."""
    conn = _get_db(dry_run=dry_run)
    rows = conn.execute(
        "SELECT approach, app, COUNT(*) as count FROM runs GROUP BY approach, app"
    ).fetchall()
    conn.close()
    return {(r[0], r[1]): r[2] for r in rows}
