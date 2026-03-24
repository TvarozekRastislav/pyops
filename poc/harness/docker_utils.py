"""Docker SDK wrappers for building, running, and managing containers."""

from __future__ import annotations

import io
import tarfile
import time

import docker
from docker.errors import APIError, BuildError, DockerException


def get_client() -> docker.DockerClient:
    """Return a Docker client connected to the local daemon."""
    return docker.from_env()


def build_image(client: docker.DockerClient, path: str, tag: str) -> tuple[bool, str]:
    """Build a Docker image from a directory containing a Dockerfile.

    Returns (success, build_log).
    """
    log_lines: list[str] = []
    try:
        _image, build_logs = client.images.build(path=path, tag=tag, rm=True)
        for chunk in build_logs:
            if "stream" in chunk:
                log_lines.append(chunk["stream"].rstrip())
        return True, "\n".join(log_lines)
    except BuildError as e:
        for chunk in e.build_log:
            if "stream" in chunk:
                log_lines.append(chunk["stream"].rstrip())
            if "error" in chunk:
                log_lines.append(f"ERROR: {chunk['error']}")
        return False, "\n".join(log_lines)
    except (DockerException, APIError) as e:
        return False, str(e)


def run_container(
    client: docker.DockerClient,
    image_tag: str,
    *,
    detach: bool = False,
    ports: dict | None = None,
    environment: dict | None = None,
    timeout: float = 60.0,
) -> tuple[str, str, int | None]:
    """Run a container from an image.

    If detach=False: runs blocking, returns (container_id, logs, exit_code).
    If detach=True: starts container, returns (container_id, "", None).
    """
    try:
        if detach:
            container = client.containers.run(
                image_tag,
                detach=True,
                ports=ports or {},
                environment=environment or {},
            )
            return container.id, "", None

        container = client.containers.run(
            image_tag,
            detach=True,
            environment=environment or {},
        )
        try:
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)
        except Exception:
            container.stop(timeout=5)
            exit_code = -1
        logs = container.logs().decode("utf-8", errors="replace")
        return container.id, logs, exit_code
    except (DockerException, APIError) as e:
        return "", str(e), -1


def wait_for_ready(
    client: docker.DockerClient, container_id: str, timeout: float = 30.0
) -> bool:
    """Wait for a container to be in 'running' state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            container = client.containers.get(container_id)
            if container.status == "running":
                return True
            if container.status in ("exited", "dead"):
                return False
        except DockerException:
            return False
        time.sleep(0.5)
    return False


def get_container_logs(client: docker.DockerClient, container_id: str) -> str:
    """Retrieve logs from a container."""
    try:
        container = client.containers.get(container_id)
        return container.logs().decode("utf-8", errors="replace")
    except DockerException:
        return ""


def copy_from_container(
    client: docker.DockerClient, container_id: str, src_path: str
) -> bytes | None:
    """Copy a file from a container. Returns file contents as bytes, or None."""
    try:
        container = client.containers.get(container_id)
        bits, _ = container.get_archive(src_path)
        stream = io.BytesIO()
        for chunk in bits:
            stream.write(chunk)
        stream.seek(0)
        with tarfile.open(fileobj=stream) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    f = tar.extractfile(member)
                    if f:
                        return f.read()
        return None
    except Exception:
        return None


def stop_and_remove(client: docker.DockerClient, container_id: str) -> None:
    """Stop and remove a container, ignoring errors."""
    try:
        container = client.containers.get(container_id)
        container.stop(timeout=5)
        container.remove(force=True)
    except DockerException:
        pass


def remove_image(client: docker.DockerClient, tag: str) -> None:
    """Remove a Docker image by tag, ignoring errors."""
    try:
        client.images.remove(tag, force=True)
    except DockerException:
        pass


def tag_image(
    client: docker.DockerClient, source_tag: str, target_tag: str
) -> bool:
    """Tag an image with a new name."""
    try:
        image = client.images.get(source_tag)
        if ":" in target_tag:
            repo, tag = target_tag.rsplit(":", 1)
        else:
            repo, tag = target_tag, "latest"
        return image.tag(repo, tag=tag)
    except DockerException:
        return False


def push_image(client: docker.DockerClient, tag: str) -> tuple[bool, str]:
    """Push an image to a registry. Returns (success, log)."""
    try:
        if ":" in tag:
            repo, image_tag = tag.rsplit(":", 1)
        else:
            repo, image_tag = tag, "latest"
        output = client.images.push(repo, tag=image_tag)
        if "error" in output.lower():
            return False, output
        return True, output
    except (DockerException, APIError) as e:
        return False, str(e)
