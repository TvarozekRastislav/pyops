"""Approach protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ApproachResult:
    """Result returned by an approach's run method."""

    image_name: str | None = None  # e.g. "pyops-a1"
    image_tag: str | None = None  # e.g. "controlled_process-1"
    build_succeeded: bool = False
    build_log: str = ""
    dockerfile_content: str = ""
    error: str | None = None
    t_build: float = 0.0


@runtime_checkable
class Approach(Protocol):
    @property
    def name(self) -> str: ...

    def run(self, app_source_path: Path, run_id: str) -> ApproachResult: ...
