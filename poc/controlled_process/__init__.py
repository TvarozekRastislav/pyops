"""Controlled process approach — deterministic pipeline with LLM for text generation only.

Low-agenticity contrast to mono_agent: Python code controls all flow.
The LLM is called only to (1) generate an initial Dockerfile and (2) fix it on failure.
No tools parameter is passed — plain chat completions only.
"""

from __future__ import annotations

import logging
from pathlib import Path

from poc.harness.cost_tracker import TrackedOpenAIClient
from poc.harness.docker_utils import get_client
from poc.harness.interface import Approach, ApproachResult
from poc.state import BuildState

from .pipeline import run_pipeline

logger = logging.getLogger(__name__)


class ControlledProcessApproach:
    """Low-agenticity approach: deterministic pipeline, LLM generates text only."""

    def __init__(self, client: TrackedOpenAIClient, model: str = "gpt-4o"):
        self._client = client
        self._model = model
        self._docker_client = get_client()

    @property
    def name(self) -> str:
        return "controlled_process"

    def run(self, app_source_path: Path, run_id: str) -> ApproachResult:
        """Run the controlled pipeline to containerize the application.

        Never raises — all exceptions are caught and stored in state.error.
        """
        app_name = app_source_path.name
        image_tag = f"pyops-{app_name}:{run_id}"

        state = BuildState(image_tag=image_tag)
        try:
            state = run_pipeline(
                client=self._client,
                docker_client=self._docker_client,
                app_source_path=str(app_source_path),
                run_id=run_id,
                state=state,
                model=self._model,
            )
        except Exception as e:
            logger.exception("Controlled process pipeline crashed")
            state.error = f"Pipeline crashed: {e}"
        finally:
            state.cleanup(self._docker_client)

        return state.to_approach_result()


def create_approach(client: TrackedOpenAIClient, **kwargs) -> Approach:
    """Factory function called by the harness runner."""
    model = kwargs.get("model", "gpt-4o")
    return ControlledProcessApproach(client, model=model)
