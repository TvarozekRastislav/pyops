"""Deterministic pipeline for the controlled process approach.

The LLM is used ONLY for text generation (no tools parameter):
  1. Generate an initial Dockerfile + metadata from source code.
  2. Fix a Dockerfile when build or runtime fails.

All flow control is in Python — the LLM never decides what to do next.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time

import docker

from poc.harness.cost_tracker import TrackedOpenAIClient
from poc.harness import docker_utils
from poc.state import BuildState
from poc.tools import read_source_code, write_and_build_dockerfile, run_container, check_container, stop_container, MAX_LOG_CHARS

from .prompts import get_system_prompt, get_generate_prompt, get_fix_prompt

logger = logging.getLogger(__name__)

MAX_FIX_ATTEMPTS = 4

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
    _log(f"  CONTROLLED PROCESS  |  {run_id}")
    _log(f"  Model: {model}  |  Image: {image_tag}")
    _log(f"{'=' * _W}{_RESET}")


def _step(label: str) -> None:
    side = (_W - len(label) - 2) // 2
    _log(f"\n{_DIM}{'─' * side}{_RESET}{_BOLD} {label} {_RESET}{_DIM}{'─' * side}{_RESET}")


def _tool_call(name: str, detail: str = "") -> None:
    msg = f"  {_CYAN}▶ {name}{_RESET}"
    if detail:
        msg += f"  {_DIM}{detail}{_RESET}"
    _log(msg)


def _tool_result(name: str, result: str) -> None:
    preview = result.replace("\n", "\n    ")
    if len(preview) > 300:
        preview = preview[:300] + "..."
    _log(f"  {_YELLOW}◀ {name}{_RESET}")
    _log(f"    {_DIM}{preview}{_RESET}")


def _agent_text(text: str) -> None:
    preview = text[:200] + "..." if len(text) > 200 else text
    _log(f"  {_GREEN}● LLM response:{_RESET}")
    _log(f"    {_DIM}{preview}{_RESET}")


def _tokens(response, call_number: int) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    inp = usage.prompt_tokens or 0
    out = usage.completion_tokens or 0
    _log(f"  {_DIM}  tokens [call {call_number}]: {inp:,} in / {out:,} out ({inp + out:,} total){_RESET}")


def _ok(msg: str) -> None:
    _log(f"  {_GREEN}✓ {msg}{_RESET}")


def _fail(msg: str) -> None:
    _log(f"  {_RED}✗ {msg}{_RESET}")


def _footer(state: BuildState, elapsed: float, llm_calls: int, fix_count: int) -> None:
    status = f"{_GREEN}SUCCESS{_RESET}" if state.build_succeeded else f"{_RED}FAILED{_RESET}"
    outcome = "COMPLETED" if state.completed else "STOPPED"
    _log(f"\n{_BOLD}{'=' * _W}")
    _log(f"  {outcome}  |  Build: {status}{_BOLD}")
    _log(f"  Time: {elapsed:.1f}s  |  Build attempts: {state.build_attempts}  |  LLM calls: {llm_calls}")
    _log(f"  Fixes: {fix_count}/{MAX_FIX_ATTEMPTS}")
    if state.error:
        _log(f"  {_RED}Error: {state.error}{_RESET}{_BOLD}")
    _log(f"{'=' * _W}{_RESET}\n")


# ---------------------------------------------------------------------------
# LLM call helper (plain chat completion — no tools parameter)
# ---------------------------------------------------------------------------


def _call_llm(
    client: TrackedOpenAIClient,
    model: str,
    messages: list[dict],
):
    """Call the LLM and return the raw response, or None on failure."""
    try:
        return client.chat.completions.create(
            model=model,
            messages=messages,
        )
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_response(text: str) -> dict | None:
    """Parse LLM response into {dockerfile, is_server, port}.

    Tries json.loads first, then falls back to extracting a Dockerfile
    from a code block.
    """
    # Try direct JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "dockerfile" in data:
            return {
                "dockerfile": data["dockerfile"],
                "is_server": bool(data.get("is_server", False)),
                "port": data.get("port"),
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting JSON from markdown fences
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict) and "dockerfile" in data:
                return {
                    "dockerfile": data["dockerfile"],
                    "is_server": bool(data.get("is_server", False)),
                    "port": data.get("port"),
                }
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: extract Dockerfile from code block
    dockerfile_match = re.search(
        r"```(?:dockerfile)?\s*(FROM .+?)```", text, re.DOTALL | re.IGNORECASE
    )
    if dockerfile_match:
        return {
            "dockerfile": dockerfile_match.group(1).strip(),
            "is_server": False,
            "port": None,
        }

    return None


def _truncate_log(log: str) -> str:
    """Truncate a log to MAX_LOG_CHARS for LLM context."""
    if len(log) <= MAX_LOG_CHARS:
        return log
    half = MAX_LOG_CHARS // 2
    return log[:half] + "\n... [truncated] ...\n" + log[-half:]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    client: TrackedOpenAIClient,
    docker_client: docker.DockerClient,
    app_source_path: str,
    run_id: str,
    state: BuildState,
    model: str = "gpt-4o",
) -> BuildState:
    """Run the deterministic containerization pipeline.

    Steps:
        1. Read source code (deterministic).
        2. Generate Dockerfile via LLM (no tools param).
        3-4. Build → run → fix loop (up to MAX_FIX_ATTEMPTS fixes).
        5. Cleanup and mark complete.
    """
    t_start = time.time()
    verbose = _verbose()
    fix_count = 0
    llm_call_count = 0

    if verbose:
        _header(run_id, model, state.image_tag)

    # ── Step 1: Read source code ──────────────────────────────────────────
    if verbose:
        _step("Step 1: Read source")

    source_json = read_source_code(
        {"directory_path": app_source_path}, state, docker_client, app_source_path
    )

    if verbose:
        _tool_call("read_source_code", f"{len(source_json)} chars")

    # ── Step 2: Generate Dockerfile via LLM ───────────────────────────────
    if verbose:
        _step("Step 2: Generate Dockerfile")

    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": get_generate_prompt(source_json, state.image_tag)},
    ]

    response = _call_llm(client, model, messages)
    if response is None:
        state.error = "LLM failed to generate Dockerfile"
        if verbose:
            _fail(state.error)
            _footer(state, time.time() - t_start, llm_call_count, fix_count)
        return state

    llm_call_count += 1
    llm_text = response.choices[0].message.content

    if verbose:
        _tokens(response, llm_call_count)
        _agent_text(llm_text or "(empty)")

    parsed = _parse_response(llm_text or "")
    if parsed is None:
        state.error = "Failed to parse LLM response for Dockerfile generation"
        if verbose:
            _fail(state.error)
            _footer(state, time.time() - t_start, llm_call_count, fix_count)
        return state

    dockerfile = parsed["dockerfile"]
    is_server = parsed["is_server"]
    port = parsed["port"]

    if verbose:
        _ok(f"Parsed: is_server={is_server}, port={port}, dockerfile={len(dockerfile)} chars")

    # Build conversation history so the LLM sees prior fix attempts
    conversation = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": get_generate_prompt(source_json, state.image_tag)},
        {"role": "assistant", "content": llm_text},
    ]

    # ── Steps 3-4: Build → Run → Fix loop ────────────────────────────────
    while fix_count <= MAX_FIX_ATTEMPTS:
        # ── 3a: Build ─────────────────────────────────────────────────────
        if verbose:
            _step(f"Step 3: Build (attempt {state.build_attempts + 1})")

        build_result = write_and_build_dockerfile(
            {"dockerfile_content": dockerfile}, state, docker_client, app_source_path
        )

        if verbose:
            _tool_call("write_and_build_dockerfile")
            _tool_result("build", build_result[:200] if len(build_result) > 200 else build_result)

        if state.build_succeeded:
            if verbose:
                _ok("Build succeeded")
        else:
            if verbose:
                _fail("Build failed")

            # Fix or bail
            if fix_count >= MAX_FIX_ATTEMPTS:
                state.error = f"Build failed after {fix_count} fix attempts"
                break

            fix_count += 1
            if verbose:
                _step(f"Step 3b: Fix build error ({fix_count}/{MAX_FIX_ATTEMPTS})")

            fixed = _request_fix(
                client, model, conversation, dockerfile, build_result,
                "build", is_server, port, verbose, llm_call_count,
            )
            llm_call_count = fixed[3]
            if fixed[0] is None:
                state.error = "LLM failed to produce a fix for build error"
                break
            dockerfile, is_server, port = fixed[0], fixed[1], fixed[2]
            continue

        # ── 4: Run container ──────────────────────────────────────────────
        if verbose:
            _step("Step 4: Run container")

        run_ok = _run_and_verify(
            state, docker_client, app_source_path, is_server, port, verbose
        )

        if run_ok:
            if verbose:
                _ok("Container ran successfully")
            state.completed = True
            break
        else:
            # Runtime failure
            error_log = state.container_logs or "No container logs available"
            if verbose:
                _fail(f"Runtime failure (exit_code={state.container_exit_code})")

            if fix_count >= MAX_FIX_ATTEMPTS:
                state.error = f"Runtime failed after {fix_count} fix attempts"
                break

            fix_count += 1
            if verbose:
                _step(f"Step 4b: Fix runtime error ({fix_count}/{MAX_FIX_ATTEMPTS})")

            fixed = _request_fix(
                client, model, conversation, dockerfile,
                _truncate_log(error_log), "runtime", is_server, port,
                verbose, llm_call_count,
            )
            llm_call_count = fixed[3]
            if fixed[0] is None:
                state.error = "LLM failed to produce a fix for runtime error"
                break
            dockerfile, is_server, port = fixed[0], fixed[1], fixed[2]
            # Rebuild with the fixed Dockerfile
            continue

    # ── Step 5: Cleanup server container if still running ─────────────────
    if state.container_id:
        try:
            container = docker_client.containers.get(state.container_id)
            if container.status == "running":
                if verbose:
                    _step("Step 5: Cleanup")
                    _tool_call("stop_container")
                stop_container({}, state, docker_client, app_source_path)
        except Exception:
            pass

    if verbose:
        _footer(state, time.time() - t_start, llm_call_count, fix_count)

    return state


# ---------------------------------------------------------------------------
# Sub-routines
# ---------------------------------------------------------------------------


def _request_fix(
    client: TrackedOpenAIClient,
    model: str,
    conversation: list[dict],
    previous_dockerfile: str,
    error_log: str,
    error_type: str,
    is_server: bool,
    port: int | None,
    verbose: bool,
    llm_call_count: int,
) -> tuple[str | None, bool, int | None, int]:
    """Ask the LLM to fix the Dockerfile using full conversation history.

    Returns (dockerfile, is_server, port, updated_llm_call_count).
    dockerfile is None on failure.
    """
    fix_message = {
        "role": "user",
        "content": get_fix_prompt(
            "", previous_dockerfile,
            error_log, error_type, is_server, port,
        ),
    }
    conversation.append(fix_message)

    response = _call_llm(client, model, conversation)
    if response is None:
        if verbose:
            _fail("LLM fix call failed")
        return None, is_server, port, llm_call_count

    llm_call_count += 1

    if verbose:
        _tokens(response, llm_call_count)

    llm_text = response.choices[0].message.content

    if verbose:
        _agent_text(llm_text or "(empty)")

    # Append assistant response to conversation for future fix attempts
    conversation.append({"role": "assistant", "content": llm_text or ""})

    parsed = _parse_response(llm_text or "")
    if parsed is None:
        if verbose:
            _fail("Failed to parse LLM fix response")
        return None, is_server, port, llm_call_count

    if verbose:
        _ok(f"Fix parsed: is_server={parsed['is_server']}, port={parsed['port']}, dockerfile={len(parsed['dockerfile'])} chars")

    return parsed["dockerfile"], parsed["is_server"], parsed["port"], llm_call_count


def _run_and_verify(
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
    is_server: bool,
    port: int | None,
    verbose: bool,
) -> bool:
    """Run the container and verify it works. Returns True on success."""
    if not is_server:
        # Script mode: blocking run, check exit code
        result = run_container(
            {"detach": False}, state, docker_client, app_source_path
        )
        if verbose:
            _tool_call("run_container", "detach=False")
            _tool_result("run", f"exit_code={state.container_exit_code}")
        return state.container_exit_code == 0

    # Server mode: detached run, wait for ready, check
    ports_map = {}
    if port:
        ports_map = {f"{port}/tcp": port}

    result = run_container(
        {"detach": True, "ports": ports_map}, state, docker_client, app_source_path
    )

    if verbose:
        _tool_call("run_container", f"detach=True, ports={ports_map}")

    if not state.container_id:
        if verbose:
            _fail("No container ID returned")
        state.container_logs = result
        return False

    # Wait for server to be ready
    ready = docker_utils.wait_for_ready(docker_client, state.container_id, timeout=30.0)

    # Get logs regardless of outcome
    check_container(
        {"container_id": state.container_id}, state, docker_client, app_source_path
    )

    if verbose:
        _tool_call("check_container", f"ready={ready}")
        _tool_result("check", f"status={'running' if ready else 'exited/crashed'}")

    if not ready:
        # Server crashed or never started
        state.container_exit_code = -1
        return False

    return True
