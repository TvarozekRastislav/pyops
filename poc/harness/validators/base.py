"""Base validator ABC for app validation."""

from __future__ import annotations

import socket
import time
from abc import ABC, abstractmethod

import docker

from ..docker_utils import (
    get_container_logs,
    run_container,
    stop_and_remove,
    wait_for_ready,
)
from ..interface import ApproachResult


def _find_free_port() -> int:
    """Find and return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class ValidationResult:
    """Result of running validation checks."""

    def __init__(self):
        self.s2_container_starts: bool = False
        self.s3_tests_pass: bool = False
        self.s4_deep_validation: bool = False
        self.container_logs: str = ""
        self.test_details: list[str] = []
        self.container_id: str = ""

    @property
    def details_str(self) -> str:
        return "\n".join(self.test_details)


class BaseValidator(ABC):
    """Abstract base validator for a test application."""

    is_server: bool = False
    container_timeout: float = 30.0

    @property
    @abstractmethod
    def app_name(self) -> str:
        """Return the app directory name (e.g. 'a1_simple_script')."""
        ...

    def validate(
        self,
        result: ApproachResult,
        client: docker.DockerClient,
    ) -> ValidationResult:
        """Run full validation (s2, s3, s4) on a built image."""
        vr = ValidationResult()
        if not result.build_succeeded or not result.image_name:
            vr.test_details.append("SKIP: build failed, no image to validate")
            return vr

        image_tag = (
            f"{result.image_name}:{result.image_tag}"
            if result.image_tag
            else result.image_name
        )

        if self.is_server:
            return self._validate_server(image_tag, client, vr)
        return self._validate_script(image_tag, client, vr)

    def _validate_script(
        self,
        image_tag: str,
        client: docker.DockerClient,
        vr: ValidationResult,
    ) -> ValidationResult:
        """Validate a non-server (script) app."""
        container_id, logs, exit_code = run_container(
            client, image_tag, timeout=self.container_timeout
        )
        vr.container_id = container_id
        vr.container_logs = logs

        # s2: container was created (has container_id)
        vr.s2_container_starts = container_id != ""
        vr.test_details.append(
            f"s2: container_created={vr.s2_container_starts} exit_code={exit_code} ({'PASS' if vr.s2_container_starts else 'FAIL'})"
        )

        if vr.s2_container_starts:
            # s3: basic automated tests
            passed, detail = self.check_s3(container_id, logs, client)
            vr.s3_tests_pass = passed
            vr.test_details.append(f"s3: {detail}")

            # s4: deep validation
            passed, detail = self.check_s4(container_id, logs, client)
            vr.s4_deep_validation = passed
            vr.test_details.append(f"s4: {detail}")

        return vr

    def _validate_server(
        self,
        image_tag: str,
        client: docker.DockerClient,
        vr: ValidationResult,
    ) -> ValidationResult:
        """Validate a server app (run detached, test via HTTP, then stop)."""
        self._allocated_port = _find_free_port()
        container_id, _, _ = run_container(
            client, image_tag, detach=True, ports=self._get_ports()
        )
        vr.container_id = container_id

        if not container_id:
            vr.test_details.append("s2: FAIL - container did not start")
            return vr

        # Give server time to start
        time.sleep(5)
        ready = wait_for_ready(client, container_id, timeout=self.container_timeout)
        vr.s2_container_starts = ready
        vr.test_details.append(
            f"s2: running={'PASS' if ready else 'FAIL'}"
        )

        if ready:
            logs = get_container_logs(client, container_id)
            vr.container_logs = logs

            passed, detail = self.check_s3(container_id, logs, client)
            vr.s3_tests_pass = passed
            vr.test_details.append(f"s3: {detail}")

            passed, detail = self.check_s4(container_id, logs, client)
            vr.s4_deep_validation = passed
            vr.test_details.append(f"s4: {detail}")
        else:
            logs = get_container_logs(client, container_id)
            vr.container_logs = logs

        return vr

    def _get_ports(self) -> dict:
        """Return port mapping for server apps. Override in subclass."""
        host_port = getattr(self, "_allocated_port", 8000)
        return {"8000/tcp": host_port}

    @abstractmethod
    def check_s3(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Run basic automated tests (s3). Return (passed, detail)."""
        ...

    @abstractmethod
    def check_s4(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Run deep heuristic validation (s4). Return (passed, detail)."""
        ...
