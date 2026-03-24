"""ReAct loop engine: message management, tool dispatch, iteration control."""

from __future__ import annotations

import json
import logging
import sys
import time

import docker

from poc.harness.cost_tracker import TrackedOpenAIClient
from poc.state import BuildState
from poc.tools import TOOL_SCHEMAS, execute_tool

from .prompts import get_system_prompt, get_user_message

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

# ---------------------------------------------------------------------------
# Verbose output helpers (print to stderr, bypass logging format noise)
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
    _log(f"  MONO AGENT  |  {run_id}")
    _log(f"  Model: {model}  |  Image: {image_tag}")
    _log(f"{'=' * _W}{_RESET}")


def _iteration_bar(iteration: int) -> None:
    label = f" Iteration {iteration}/{MAX_ITERATIONS} "
    side = (_W - len(label)) // 2
    _log(f"\n{_DIM}{'─' * side}{_RESET}{_BOLD}{label}{_RESET}{_DIM}{'─' * side}{_RESET}")


def _tool_call(name: str, args: dict) -> None:
    _log(f"  {_CYAN}▶ Tool: {name}{_RESET}")
    for k, v in args.items():
        v_str = str(v)
        if len(v_str) > 120:
            v_str = v_str[:120] + "..."
        _log(f"    {_DIM}{k}: {v_str}{_RESET}")


def _tool_result(name: str, result: str) -> None:
    preview = result.replace("\n", "\n    ")
    if len(preview) > 300:
        preview = preview[:300] + "..."
    _log(f"  {_YELLOW}◀ {name}{_RESET}")
    _log(f"    {_DIM}{preview}{_RESET}")


def _agent_text(text: str) -> None:
    preview = text[:200] + "..." if len(text) > 200 else text
    _log(f"  {_GREEN}● Agent response:{_RESET}")
    _log(f"    {_DIM}{preview}{_RESET}")


def _tokens(response, call_number: int) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    inp = usage.prompt_tokens or 0
    out = usage.completion_tokens or 0
    _log(f"  {_DIM}  tokens [call {call_number}]: {inp:,} in / {out:,} out ({inp + out:,} total){_RESET}")


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
# Agent loop
# ---------------------------------------------------------------------------


def run_agent_loop(
    client: TrackedOpenAIClient,
    docker_client: docker.DockerClient,
    app_source_path: str,
    run_id: str,
    state: BuildState,
    model: str = "gpt-4o",
) -> BuildState:
    """Run the ReAct agent loop until completion or iteration limit."""
    t_start = time.time()
    verbose = _verbose()

    messages: list[dict] = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": get_user_message(app_source_path, state.image_tag)},
    ]

    llm_call_count = 0

    if verbose:
        _header(run_id, model, state.image_tag)

    for iteration in range(1, MAX_ITERATIONS + 1):
        state.iteration = iteration

        if verbose:
            _iteration_bar(iteration)

        # Call the LLM
        response = _call_llm(client, model, messages)
        if response is None:
            state.error = "LLM call failed after retries"
            break

        llm_call_count += 1

        if verbose:
            _tokens(response, llm_call_count)

        choice = response.choices[0]
        assistant_message = choice.message

        # Append assistant message to history
        messages.append(_message_to_dict(assistant_message))

        # Check if the agent is done (no tool calls)
        if not assistant_message.tool_calls:
            state.completed = True
            if verbose:
                _agent_text(assistant_message.content or "(no content)")
            break

        # Execute each tool call
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            if verbose:
                _tool_call(tool_name, tool_args)

            result = execute_tool(
                tool_name, tool_args, state, docker_client, app_source_path
            )

            if verbose:
                _tool_result(tool_name, result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )
    else:
        state.error = f"Agent did not complete within {MAX_ITERATIONS} iterations"

    if verbose:
        _footer(state, time.time() - t_start, total_calls=llm_call_count)

    return state


def _call_llm(
    client: TrackedOpenAIClient,
    model: str,
    messages: list[dict],
    retries: int = 1,
):
    """Call the LLM with one retry on failure."""
    for attempt in range(retries + 1):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
        except Exception as e:
            logger.warning("LLM call failed (attempt %d): %s", attempt + 1, e)
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
