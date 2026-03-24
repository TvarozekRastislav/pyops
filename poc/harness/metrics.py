"""Per-run metrics dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawRunMetrics:
    """All metrics collected for a single run."""

    # Identity
    run_id: str
    approach: str
    app: str
    repetition: int
    model: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Accuracy (s1-s4)
    s1_build: bool = False
    s2_container_starts: bool = False
    s3_tests_pass: bool = False
    s4_deep_validation: bool = False

    # Cost
    cost_usd: float = 0.0
    n_calls: int = 0
    n_tokens: int = 0

    # Time (seconds)
    t_total: float = 0.0
    t_build: float = 0.0

    # Stability flags (True = failure)
    f_build: bool = False
    f_run: bool = False
    f_push: bool = False

    # Artifacts
    dockerfile_content: str = ""
    build_log: str = ""
    container_logs: str = ""
    test_details: str = ""
