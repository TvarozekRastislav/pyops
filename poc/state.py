"""Mutable build state tracking all artifacts during a run."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field

from .harness.interface import ApproachResult


@dataclass
class BuildState:
    """Accumulates artifacts produced during a single run.

    Shared across all approaches (mono_agent, multi_agent, controlled_process).
    """

    # Dockerfile
    dockerfile_content: str = ""

    # Build
    image_tag: str = ""
    build_succeeded: bool = False
    build_log: str = ""
    build_attempts: int = 0

    # Container
    container_id: str = ""
    container_logs: str = ""
    container_exit_code: int | None = None

    # Cleanup tracking
    temp_dirs: list[str] = field(default_factory=list)
    container_ids: list[str] = field(default_factory=list)

    # Timing
    t_build: float = 0.0

    # Loop control
    iteration: int = 0
    completed: bool = False
    error: str | None = None

    def to_approach_result(self) -> ApproachResult:
        """Convert build state to the harness ApproachResult contract."""
        image_name: str | None = None
        image_tag: str | None = None
        if self.image_tag and ":" in self.image_tag:
            image_name, image_tag = self.image_tag.rsplit(":", 1)
        elif self.image_tag:
            image_name = self.image_tag

        return ApproachResult(
            image_name=image_name,
            image_tag=image_tag,
            build_succeeded=self.build_succeeded,
            build_log=self.build_log,
            dockerfile_content=self.dockerfile_content,
            error=self.error,
            t_build=self.t_build,
        )

    def cleanup(self, docker_client) -> None:
        """Remove temp directories and orphaned containers."""
        from .harness.docker_utils import stop_and_remove

        for container_id in self.container_ids:
            try:
                stop_and_remove(docker_client, container_id)
            except Exception:
                pass

        for temp_dir in self.temp_dirs:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
