"""Central orchestrator agent with delegation meta-tools."""

from __future__ import annotations

import json
import logging
import sys
import time

import docker

from poc.harness.cost_tracker import TrackedOpenAIClient
from poc.state import BuildState
from poc.tools import TOOL_SCHEMAS

from .prompts import (
    get_agent_a_system_prompt,
    get_agent_b_system_prompt,
    get_agent_c_system_prompt,
    get_orchestrator_system_prompt,
    get_orchestrator_user_message,
)
from .sub_agent import run_sub_agent

logger = logging.getLogger(__name__)

MAX_ORCHESTRATOR_ITERATIONS = 10

# ---------------------------------------------------------------------------
# Tool name sets for sub-agents (filter from shared TOOL_SCHEMAS)
# ---------------------------------------------------------------------------

AGENT_A_TOOL_NAMES = {"read_source_code", "write_and_build_dockerfile"}
AGENT_B_TOOL_NAMES = {"run_container", "check_container", "stop_container"}
AGENT_C_TOOL_NAMES = {"push_image"}


def _filter_tool_schemas(names: set[str]) -> list[dict]:
    """Return only the tool schemas whose names are in the given set."""
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] in names]


# ---------------------------------------------------------------------------
# Orchestrator meta-tool schemas
# ---------------------------------------------------------------------------

ORCHESTRATOR_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "delegate_to_agent_a",
            "description": (
                "Delegate a task to Agent A (Docker Builder). "
                "Agent A can read source code and write/build Dockerfiles. "
                "Returns Agent A's summary when done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": (
                            "Detailed task description for Agent A. "
                            "Include any error context from previous attempts."
                        ),
                    }
                },
                "required": ["task_description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_agent_b",
            "description": (
                "Delegate a task to Agent B (Test Runner). "
                "Agent B can run containers, check their status, and stop them. "
                "Returns Agent B's summary when done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": (
                            "Detailed task description for Agent B. "
                            "Include what image to test and what to look for."
                        ),
                    }
                },
                "required": ["task_description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_agent_c",
            "description": (
                "Delegate a task to Agent C (Publisher). "
                "Agent C can push verified images to the registry. "
                "Returns Agent C's summary when done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": (
                            "Detailed task description for Agent C. "
                            "Include the image tag to push."
                        ),
                    }
                },
                "required": ["task_description"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Verbose output helpers
# ---------------------------------------------------------------------------

_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_RESET = "\033[0m"
_W = 60


def _verbose() -> bool:
    return logger.isEnabledFor(logging.INFO)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _header(run_id: str, model: str, image_tag: str) -> None:
    _log(f"\n{_BOLD}{'=' * _W}")
    _log(f"  MULTI AGENT ORCHESTRATOR  |  {run_id}")
    _log(f"  Model: {model}  |  Image: {image_tag}")
    _log(f"{'=' * _W}{_RESET}")


def _iteration_bar(iteration: int) -> None:
    label = f" Orchestrator Iteration {iteration}/{MAX_ORCHESTRATOR_ITERATIONS} "
    side = (_W - len(label)) // 2
    _log(f"\n{_DIM}{'─' * side}{_RESET}{_BOLD}{label}{_RESET}{_DIM}{'─' * side}{_RESET}")


def _delegation(agent_name: str, task: str) -> None:
    preview = task[:150] + "..." if len(task) > 150 else task
    _log(f"  {_CYAN}[TOOL CALL] delegate -> {agent_name}{_RESET}")
    _log(f"  {_DIM}  task: {preview}{_RESET}")


def _delegation_result(agent_name: str, summary: str) -> None:
    preview = summary[:300] + "..." if len(summary) > 300 else summary
    _log(f"  {_YELLOW}[TOOL RESULT] {agent_name} returned:{_RESET}")
    _log(f"  {_DIM}  {preview}{_RESET}")


def _orchestrator_text(text: str) -> None:
    preview = text[:200] + "..." if len(text) > 200 else text
    _log(f"  {_GREEN}[LLM RESPONSE] Orchestrator (final):{_RESET}")
    _log(f"  {_DIM}  {preview}{_RESET}")


def _tokens(response, call_number: int) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    inp = usage.prompt_tokens or 0
    out = usage.completion_tokens or 0
    _log(f"  {_DIM}[TOKENS] orch call {call_number}: {inp:,} in / {out:,} out ({inp + out:,} total){_RESET}")


def _footer(state: BuildState, elapsed: float, total_calls: int = 0) -> None:
    status = f"{_GREEN}SUCCESS{_RESET}" if state.build_succeeded else f"{_RED}FAILED{_RESET}"
    outcome = "COMPLETED" if state.completed else "STOPPED"
    _log(f"\n{_BOLD}{'=' * _W}")
    _log(f"  {outcome} in {state.iteration} iterations  |  Build: {status}{_BOLD}")
    _log(f"  Time: {elapsed:.1f}s  |  Build attempts: {state.build_attempts}  |  LLM calls: {total_calls}")
    if state.error:
        _log(f"  {_RED}Error: {state.error}{_RESET}{_BOLD}")
    _log(f"{'=' * _W}{_RESET}\n")


# ---------------------------------------------------------------------------
# Orchestrator loop
# ---------------------------------------------------------------------------


def run_orchestrator(
    client: TrackedOpenAIClient,
    docker_client: docker.DockerClient,
    app_source_path: str,
    run_id: str,
    state: BuildState,
    model: str = "gpt-4o",
) -> BuildState:
    """Run the orchestrator agent loop with delegation meta-tools."""
    t_start = time.time()
    verbose = _verbose()

    messages: list[dict] = [
        {"role": "system", "content": get_orchestrator_system_prompt()},
        {"role": "user", "content": get_orchestrator_user_message(app_source_path, state.image_tag)},
    ]

    llm_call_count = 0

    if verbose:
        _header(run_id, model, state.image_tag)

    for iteration in range(1, MAX_ORCHESTRATOR_ITERATIONS + 1):
        state.iteration = iteration

        if verbose:
            _iteration_bar(iteration)

        # Call the orchestrator LLM
        response = _call_llm(client, model, messages)
        if response is None:
            state.error = "Orchestrator LLM call failed after retries"
            break

        llm_call_count += 1

        if verbose:
            _tokens(response, llm_call_count)

        choice = response.choices[0]
        assistant_message = choice.message

        messages.append(_message_to_dict(assistant_message))

        # No tool calls = orchestrator is done
        if not assistant_message.tool_calls:
            state.completed = True
            if verbose:
                _orchestrator_text(assistant_message.content or "(no content)")
            break

        # Execute each meta-tool call (delegation)
        for tool_call in assistant_message.tool_calls:
            meta_tool_name = tool_call.function.name
            try:
                meta_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                meta_args = {}

            task_description = meta_args.get("task_description", "")

            if verbose:
                _delegation(meta_tool_name, task_description)

            # Dispatch to the appropriate sub-agent
            result = _dispatch_meta_tool(
                meta_tool_name,
                task_description,
                client=client,
                model=model,
                state=state,
                docker_client=docker_client,
                app_source_path=app_source_path,
            )

            if verbose:
                _delegation_result(meta_tool_name, result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )
    else:
        state.error = f"Orchestrator did not complete within {MAX_ORCHESTRATOR_ITERATIONS} iterations"

    if verbose:
        _footer(state, time.time() - t_start, total_calls=llm_call_count)

    return state


# ---------------------------------------------------------------------------
# Meta-tool dispatch
# ---------------------------------------------------------------------------

_AGENT_CONFIG = {
    "delegate_to_agent_a": {
        "system_prompt_fn": get_agent_a_system_prompt,
        "tool_names": AGENT_A_TOOL_NAMES,
        "agent_name": "Agent-A (Builder)",
    },
    "delegate_to_agent_b": {
        "system_prompt_fn": get_agent_b_system_prompt,
        "tool_names": AGENT_B_TOOL_NAMES,
        "agent_name": "Agent-B (Tester)",
    },
    "delegate_to_agent_c": {
        "system_prompt_fn": get_agent_c_system_prompt,
        "tool_names": AGENT_C_TOOL_NAMES,
        "agent_name": "Agent-C (Publisher)",
    },
}


def _dispatch_meta_tool(
    meta_tool_name: str,
    task_description: str,
    *,
    client: TrackedOpenAIClient,
    model: str,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Dispatch a meta-tool call to the appropriate sub-agent."""
    config = _AGENT_CONFIG.get(meta_tool_name)
    if config is None:
        return f"Unknown meta-tool: {meta_tool_name}"

    system_prompt = config["system_prompt_fn"]()
    tool_schemas = _filter_tool_schemas(config["tool_names"])
    agent_name = config["agent_name"]

    return run_sub_agent(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_message=task_description,
        tool_schemas=tool_schemas,
        state=state,
        docker_client=docker_client,
        app_source_path=app_source_path,
        agent_name=agent_name,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call_llm(
    client: TrackedOpenAIClient,
    model: str,
    messages: list[dict],
    retries: int = 1,
):
    """Call the orchestrator LLM with one retry on failure."""
    for attempt in range(retries + 1):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=ORCHESTRATOR_TOOL_SCHEMAS,
                tool_choice="auto",
            )
        except Exception as e:
            logger.warning("Orchestrator LLM call failed (attempt %d): %s", attempt + 1, e)
            if attempt < retries:
                time.sleep(2)
    return None


def _message_to_dict(message) -> dict:
    """Convert an OpenAI ChatCompletionMessage to a serializable dict."""
    msg: dict = {"role": message.role}

    if message.content:
        msg["content"] = message.content

    if message.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]

    return msg
