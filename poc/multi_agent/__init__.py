"""Multi-agent approach — orchestrator delegates to specialist sub-agents."""

from __future__ import annotations

import logging
from pathlib import Path

from poc.harness.cost_tracker import TrackedOpenAIClient
from poc.harness.docker_utils import get_client
from poc.harness.interface import Approach, ApproachResult
from poc.state import BuildState

from .orchestrator import run_orchestrator

logger = logging.getLogger(__name__)


class MultiAgentApproach:
    """Modular-agenticity approach: orchestrator + specialist sub-agents."""

    def __init__(self, client: TrackedOpenAIClient, model: str = "gpt-4o"):
        self._client = client
        self._model = model
        self._docker_client = get_client()

    @property
    def name(self) -> str:
        return "multi_agent"

    def run(self, app_source_path: Path, run_id: str) -> ApproachResult:
        """Run the multi-agent orchestrator to containerize the application.

        Never raises — all exceptions are caught and stored in state.error.
        """
        app_name = app_source_path.name
        image_tag = f"pyops-{app_name}:{run_id}"

        state = BuildState(image_tag=image_tag)
        try:
            state = run_orchestrator(
                client=self._client,
                docker_client=self._docker_client,
                app_source_path=str(app_source_path),
                run_id=run_id,
                state=state,
                model=self._model,
            )
        except Exception as e:
            logger.exception("Orchestrator loop crashed")
            state.error = f"Orchestrator loop crashed: {e}"
        finally:
            state.cleanup(self._docker_client)

        return state.to_approach_result()


def create_approach(client: TrackedOpenAIClient, **kwargs) -> Approach:
    """Factory function called by the harness runner."""
    model = kwargs.get("model", "gpt-4o")
    return MultiAgentApproach(client, model=model)
