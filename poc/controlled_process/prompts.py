"""Prompt templates for the controlled process approach.

Three prompt functions:
- get_system_prompt(): shared role + response format instructions
- get_generate_prompt(): source code → Dockerfile generation
- get_fix_prompt(): error context → Dockerfile fix
"""

from __future__ import annotations


def get_system_prompt() -> str:
    """Return the system prompt shared across generate and fix calls."""
    return """\
You are an expert DevOps engineer specializing in containerizing Python applications.

## Response Format
You MUST respond with a JSON object containing exactly these fields:
```json
{
  "dockerfile": "FROM python:3.11-slim\\n...",
  "is_server": false,
  "port": null
}
```

- **dockerfile**: The complete Dockerfile content as a single string with \\n for newlines.
- **is_server**: `true` if the application is a long-running server (Flask, FastAPI, Django, etc.), `false` if it is a script that runs and exits.
- **port**: The port number the server listens on (integer), or `null` if it is not a server.

Respond ONLY with the JSON object — no markdown fences, no commentary before or after.

## Dockerfile Best Practices
- Use `python:3.11-slim` as base image.
- `COPY . /app` and `WORKDIR /app`.
- If requirements.txt exists, run `RUN pip install --no-cache-dir -r requirements.txt`.
- Cross-reference the imports in the Python source files with requirements.txt. If a package name in requirements.txt does not match the pip package name for an import, use the correct pip package name. Common mismatches:
  - `import cv2` → pip package is `opencv-python`
  - `import sklearn` → pip package is `scikit-learn`
  - `import yaml` → pip package is `pyyaml`
  - `import PIL` → pip package is `pillow`
- Set an appropriate CMD to run the application entry point.
- For servers: expose the correct port, bind to 0.0.0.0, use a production-ready command.

## Rules
- Do not modify the application source code — only create a Dockerfile.
- Derive package names from import statements, not guesses.
- If the source code has unfixable bugs, still create the best possible Dockerfile.\
"""


def get_generate_prompt(source_json: str, image_tag: str) -> str:
    """Return the user prompt for initial Dockerfile generation."""
    return (
        f"Containerize this Python application as Docker image `{image_tag}`.\n\n"
        f"## Source Files\n```json\n{source_json}\n```\n\n"
        "Analyze the source code, determine if it is a script or server, "
        "and respond with the JSON object containing the Dockerfile, "
        "is_server flag, and port."
    )


def get_fix_prompt(
    source_json: str,
    previous_dockerfile: str,
    error_log: str,
    error_type: str,
    is_server: bool,
    port: int | None,
) -> str:
    """Return the user prompt for fixing a failed Dockerfile.

    Parameters
    ----------
    error_type : str
        Either "build" or "runtime".
    """
    return (
        f"The previous Dockerfile failed during **{error_type}**.\n\n"
        f"## Previous Dockerfile\n```dockerfile\n{previous_dockerfile}\n```\n\n"
        f"## Previous settings\n- is_server: {is_server}\n- port: {port}\n\n"
        f"## Error Log\n```\n{error_log}\n```\n\n"
        f"## Source Files\n```json\n{source_json}\n```\n\n"
        "Analyze the error, fix the Dockerfile, and respond with the updated JSON object. "
        "You may also change is_server or port if needed."
    )
