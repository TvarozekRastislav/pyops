"""Generic reusable sub-agent runner for the multi-agent architecture."""

from __future__ import annotations

import json
import logging
import sys
import time

import docker

from poc.harness.cost_tracker import TrackedOpenAIClient
from poc.state import BuildState
from poc.tools import execute_tool

logger = logging.getLogger(__name__)

MAX_SUB_AGENT_ITERATIONS = 10

# ---------------------------------------------------------------------------
# Verbose output helpers (stderr, colored, indented for nesting)
# ---------------------------------------------------------------------------

_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"
_RESET = "\033[0m"
_INDENT = "    "


def _verbose() -> bool:
    return logger.isEnabledFor(logging.INFO)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _sub_header(agent_name: str) -> None:
    _log(f"\n{_INDENT}{_MAGENTA}{_BOLD}{'─' * 40}")
    _log(f"{_INDENT}  SUB-AGENT: {agent_name}")
    _log(f"{_INDENT}{'─' * 40}{_RESET}")


def _sub_iteration(agent_name: str, iteration: int) -> None:
    _log(f"{_INDENT}{_DIM}[ITERATION] {agent_name} {iteration}/{MAX_SUB_AGENT_ITERATIONS}{_RESET}")


def _sub_tool_call(agent_name: str, name: str, args: dict) -> None:
    _log(f"{_INDENT}  {_CYAN}[TOOL CALL] {name}{_RESET}")
    for k, v in args.items():
        v_str = str(v)
        if len(v_str) > 120:
            v_str = v_str[:120] + "..."
        _log(f"{_INDENT}    {_DIM}{k}: {v_str}{_RESET}")


def _sub_tool_result(agent_name: str, name: str, result: str) -> None:
    preview = result.replace("\n", "\n" + _INDENT + "    ")
    if len(preview) > 300:
        preview = preview[:300] + "..."
    _log(f"{_INDENT}  {_YELLOW}[TOOL RESULT] {name} returned:{_RESET}")
    _log(f"{_INDENT}    {_DIM}{preview}{_RESET}")


def _sub_text(agent_name: str, text: str) -> None:
    preview = text[:200] + "..." if len(text) > 200 else text
    _log(f"{_INDENT}  {_GREEN}[LLM RESPONSE] {agent_name} (final):{_RESET}")
    _log(f"{_INDENT}    {_DIM}{preview}{_RESET}")


def _sub_footer(agent_name: str) -> None:
    _log(f"{_INDENT}{_MAGENTA}{_BOLD}{'─' * 40}")
    _log(f"{_INDENT}  END: {agent_name}")
    _log(f"{_INDENT}{'─' * 40}{_RESET}")


def _sub_tokens(agent_name: str, response, call_number: int) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    inp = usage.prompt_tokens or 0
    out = usage.completion_tokens or 0
    _log(f"{_INDENT}  {_DIM}[TOKENS] {agent_name} call {call_number}: {inp:,} in / {out:,} out{_RESET}")


# ---------------------------------------------------------------------------
# Sub-agent runner
# ---------------------------------------------------------------------------


def run_sub_agent(
    client: TrackedOpenAIClient,
    model: str,
    system_prompt: str,
    user_message: str,
    tool_schemas: list[dict],
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
    agent_name: str = "SubAgent",
) -> str:
    """Run a sub-agent ReAct loop and return its final text summary.

    If tool_schemas is empty, makes a single LLM call without tools.
    """
    verbose = _verbose()

    if verbose:
        _sub_header(agent_name)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    llm_call_count = 0

    # If no tools, single LLM call
    if not tool_schemas:
        response = _call_llm(client, model, messages, tool_schemas=None)
        if response is None:
            summary = f"[{agent_name}] LLM call failed."
        else:
            llm_call_count += 1
            if verbose:
                _sub_tokens(agent_name, response, llm_call_count)
            summary = response.choices[0].message.content or ""
            if verbose:
                _sub_text(agent_name, summary)
        if verbose:
            _sub_footer(agent_name)
        return summary

    # ReAct loop
    for iteration in range(1, MAX_SUB_AGENT_ITERATIONS + 1):
        if verbose:
            _sub_iteration(agent_name, iteration)

        response = _call_llm(client, model, messages, tool_schemas=tool_schemas)
        if response is None:
            if verbose:
                _sub_footer(agent_name)
            return f"[{agent_name}] LLM call failed after retries."

        llm_call_count += 1
        if verbose:
            _sub_tokens(agent_name, response, llm_call_count)

        choice = response.choices[0]
        assistant_message = choice.message

        messages.append(_message_to_dict(assistant_message))

        # No tool calls = agent is done
        if not assistant_message.tool_calls:
            summary = assistant_message.content or ""
            if verbose:
                _sub_text(agent_name, summary)
                _sub_footer(agent_name)
            return summary

        # Execute tool calls
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            if verbose:
                _sub_tool_call(agent_name, tool_name, tool_args)

            result = execute_tool(
                tool_name, tool_args, state, docker_client, app_source_path
            )

            if verbose:
                _sub_tool_result(agent_name, tool_name, result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

    # Exhausted iterations
    if verbose:
        _sub_footer(agent_name)
    return f"[{agent_name}] Did not complete within {MAX_SUB_AGENT_ITERATIONS} iterations."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call_llm(
    client: TrackedOpenAIClient,
    model: str,
    messages: list[dict],
    tool_schemas: list[dict] | None,
    retries: int = 1,
):
    """Call the LLM with one retry on failure."""
    kwargs: dict = {
        "model": model,
        "messages": messages,
    }
    if tool_schemas:
        kwargs["tools"] = tool_schemas
        kwargs["tool_choice"] = "auto"

    for attempt in range(retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.warning(
                "Sub-agent LLM call failed (attempt %d): %s", attempt + 1, e
            )
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
