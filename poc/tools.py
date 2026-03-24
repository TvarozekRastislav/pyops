"""Shared tool schemas (OpenAI function-calling format) and implementations.

Used by all approaches: mono_agent, multi_agent, and controlled_process.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time

import docker

from .harness import docker_utils
from .state import BuildState

logger = logging.getLogger(__name__)

MAX_BUILD_ATTEMPTS = 5
MAX_SOURCE_CHARS = 30_000
MAX_LOG_CHARS = 4_000

_SKIP_DIRS = {
    "__pycache__", ".git", ".mypy_cache", "node_modules", ".venv", "venv",
    ".tox", ".eggs",
}
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".o", ".a", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".db", ".sqlite", ".sqlite3",
}

# ---------------------------------------------------------------------------
# OpenAI tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_source_code",
            "description": (
                "Recursively read all source files in a directory. "
                "Returns a JSON object mapping relative file paths to their contents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Absolute path to the directory to read.",
                    }
                },
                "required": ["directory_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_and_build_dockerfile",
            "description": (
                "Write a Dockerfile and build a Docker image. "
                "The source code is copied to a temporary build directory automatically. "
                "Returns the build log."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dockerfile_content": {
                        "type": "string",
                        "description": "Full contents of the Dockerfile to write.",
                    }
                },
                "required": ["dockerfile_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_container",
            "description": (
                "Run a container from the last successfully built image. "
                "If detach=false (default), blocks until the container exits and returns logs + exit code. "
                "If detach=true, starts the container in background and returns immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "detach": {
                        "type": "boolean",
                        "description": "Run in background (true) or blocking (false). Default: false.",
                    },
                    "ports": {
                        "type": "object",
                        "description": 'Port mappings, e.g. {"5000/tcp": 5000}.',
                    },
                    "environment": {
                        "type": "object",
                        "description": "Environment variables to pass to the container.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_container",
            "description": (
                "Get the current status and recent logs of a running or exited container."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "container_id": {
                        "type": "string",
                        "description": "Container ID. If omitted, uses the last started container.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_container",
            "description": "Stop and remove a running container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container_id": {
                        "type": "string",
                        "description": "Container ID. If omitted, uses the last started container.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "push_image",
            "description": (
                "Push the last successfully built image to a Docker registry. "
                "Reads the registry from the PYOPS_REGISTRY environment variable. "
                "Tags the image as {registry}/pyops-{app_name}:{run_id} and pushes it."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def read_source_code(
    args: dict,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Recursively read source files and return as JSON."""
    directory_path = args.get("directory_path", app_source_path)

    if not os.path.isdir(directory_path):
        return json.dumps({"error": f"Directory not found: {directory_path}"})

    files: dict[str, str] = {}

    for root, dirs, filenames in os.walk(directory_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in filenames:
            _, ext = os.path.splitext(fname)
            if ext.lower() in _SKIP_EXTENSIONS:
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, directory_path)
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    files[rel_path] = f.read()
            except Exception as e:
                files[rel_path] = f"<error reading file: {e}>"

    result = json.dumps(files, indent=2)
    if len(result) > MAX_SOURCE_CHARS:
        result = result[:MAX_SOURCE_CHARS] + "\n... [truncated]"
    return result


def write_and_build_dockerfile(
    args: dict,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Write Dockerfile to temp dir with source copy, then build."""
    if state.build_attempts >= MAX_BUILD_ATTEMPTS:
        return (
            f"Build attempt limit reached ({MAX_BUILD_ATTEMPTS}). "
            "Cannot attempt another build."
        )

    dockerfile_content = args["dockerfile_content"]
    state.dockerfile_content = dockerfile_content
    state.build_attempts += 1

    # Create temp build directory with source files
    temp_dir = tempfile.mkdtemp(prefix="pyops_build_")
    state.temp_dirs.append(temp_dir)

    try:
        # Copy application source into the temp build context
        for item in os.listdir(app_source_path):
            s = os.path.join(app_source_path, item)
            d = os.path.join(temp_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

        # Write Dockerfile
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, "w", encoding="utf-8") as f:
            f.write(dockerfile_content)

        # Build image
        t0 = time.monotonic()
        success, build_log = docker_utils.build_image(
            docker_client, temp_dir, state.image_tag
        )
        state.t_build += time.monotonic() - t0

        state.build_succeeded = success
        state.build_log = build_log

        # Truncate log for LLM response
        log_response = build_log
        if len(log_response) > MAX_LOG_CHARS:
            log_response = (
                log_response[: MAX_LOG_CHARS // 2]
                + "\n... [truncated] ...\n"
                + log_response[-MAX_LOG_CHARS // 2 :]
            )

        status = "SUCCESS" if success else "FAILED"
        return (
            f"Build {status} (attempt {state.build_attempts}/{MAX_BUILD_ATTEMPTS})\n"
            f"Image tag: {state.image_tag}\n\n"
            f"Build log:\n{log_response}"
        )
    except Exception as e:
        state.build_succeeded = False
        state.build_log = str(e)
        return f"Build error: {e}"


def run_container(
    args: dict,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Run a container from the last built image."""
    if not state.build_succeeded:
        return "Cannot run container — no successful build yet."

    # Auto-clean previous container
    if state.container_id:
        try:
            docker_utils.stop_and_remove(docker_client, state.container_id)
        except Exception:
            pass

    detach = args.get("detach", False)
    ports = args.get("ports")
    environment = args.get("environment")

    container_id, logs, exit_code = docker_utils.run_container(
        docker_client,
        state.image_tag,
        detach=detach,
        ports=ports,
        environment=environment,
    )

    state.container_id = container_id
    if container_id:
        state.container_ids.append(container_id)
    state.container_logs = logs
    state.container_exit_code = exit_code

    if detach:
        return (
            f"Container started in detached mode.\n"
            f"Container ID: {container_id[:12] if container_id else 'N/A'}\n"
            "Use check_container to inspect status and logs."
        )

    # Truncate logs for LLM
    log_response = logs
    if len(log_response) > MAX_LOG_CHARS:
        log_response = log_response[:MAX_LOG_CHARS] + "\n... [truncated]"

    return (
        f"Container exited with code: {exit_code}\n"
        f"Container ID: {container_id[:12] if container_id else 'N/A'}\n\n"
        f"Logs:\n{log_response}"
    )


def check_container(
    args: dict,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Check container status and retrieve logs."""
    container_id = args.get("container_id") or state.container_id
    if not container_id:
        return "No container to check."

    try:
        container = docker_client.containers.get(container_id)
        status = container.status
        logs = container.logs().decode("utf-8", errors="replace")

        state.container_logs = logs

        if len(logs) > MAX_LOG_CHARS:
            logs = logs[:MAX_LOG_CHARS] + "\n... [truncated]"

        return (
            f"Container {container_id[:12]} status: {status}\n\n"
            f"Logs:\n{logs}"
        )
    except Exception as e:
        return f"Error checking container: {e}"


def stop_container(
    args: dict,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Stop and remove a container."""
    container_id = args.get("container_id") or state.container_id
    if not container_id:
        return "No container to stop."

    try:
        docker_utils.stop_and_remove(docker_client, container_id)
        if container_id == state.container_id:
            state.container_id = ""
        return f"Container {container_id[:12]} stopped and removed."
    except Exception as e:
        return f"Error stopping container: {e}"


def push_image(
    args: dict,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Push the built image to a registry."""
    registry = os.environ.get("PYOPS_REGISTRY")
    if not registry:
        return "No registry configured (PYOPS_REGISTRY not set), push skipped."

    if not state.build_succeeded or not state.image_tag:
        return "Cannot push — no successfully built image."

    app_name = os.path.basename(app_source_path)
    # Extract run_id from image_tag (format: pyops-{app_name}:{run_id})
    run_id = state.image_tag.rsplit(":", 1)[-1] if ":" in state.image_tag else "latest"
    target_tag = f"{registry}/pyops-{app_name}:{run_id}"

    if not docker_utils.tag_image(docker_client, state.image_tag, target_tag):
        return f"Failed to tag image as {target_tag}"

    success, log = docker_utils.push_image(docker_client, target_tag)
    if success:
        return f"Image pushed successfully: {target_tag}"
    return f"Push failed: {log}"


# ---------------------------------------------------------------------------
# Dispatch map
# ---------------------------------------------------------------------------

TOOL_DISPATCH = {
    "read_source_code": read_source_code,
    "write_and_build_dockerfile": write_and_build_dockerfile,
    "run_container": run_container,
    "check_container": check_container,
    "stop_container": stop_container,
    "push_image": push_image,
}


def execute_tool(
    tool_name: str,
    args: dict,
    state: BuildState,
    docker_client: docker.DockerClient,
    app_source_path: str,
) -> str:
    """Execute a tool by name, returning the result string.

    All exceptions are caught and returned as error text for the LLM.
    """
    handler = TOOL_DISPATCH.get(tool_name)
    if handler is None:
        return f"Unknown tool: {tool_name}"

    try:
        return handler(args, state, docker_client, app_source_path)
    except Exception as e:
        logger.exception("Tool %s crashed", tool_name)
        return f"Tool '{tool_name}' crashed with error: {e}"
