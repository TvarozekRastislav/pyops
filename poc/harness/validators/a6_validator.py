"""Validator for a6_problematic: data fetcher with network + bad requirements."""

from __future__ import annotations

import json

import docker

from ..docker_utils import copy_from_container
from .base import BaseValidator


class A6Validator(BaseValidator):
    is_server = False
    container_timeout = 60.0  # needs network access

    @property
    def app_name(self) -> str:
        return "a6_problematic"

    def check_s3(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Check stdout has 'Fetching' and 'Received:'."""
        checks = []
        has_fetching = "Fetching" in logs or "fetching" in logs.lower()
        checks.append(f"'Fetching' in output: {has_fetching}")

        has_received = "Received:" in logs
        checks.append(f"'Received:' in output: {has_received}")

        passed = has_fetching and has_received
        return passed, f"{'PASS' if passed else 'FAIL'} - {'; '.join(checks)}"

    def check_s4(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Deep: response is valid JSON, keys/total_values in processed, results/output.json created."""
        checks = []
        all_ok = True

        # Check that the received data is valid JSON
        received_start = logs.find("Received:")
        if received_start != -1:
            after_received = logs[received_start + len("Received:"):]
            brace_start = after_received.find("{")
            if brace_start != -1:
                json_text = after_received[brace_start:]
                depth = 0
                end = 0
                for i, c in enumerate(json_text):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > 0:
                    try:
                        data = json.loads(json_text[:end])
                        checks.append(
                            f"received data is valid JSON with keys: {list(data.keys())}"
                        )
                    except json.JSONDecodeError:
                        checks.append("received data is not valid JSON")
                        all_ok = False
                else:
                    checks.append("could not find complete JSON object")
                    all_ok = False
            else:
                checks.append("no JSON object after 'Received:'")
                all_ok = False
        else:
            checks.append("'Received:' not found in logs")
            all_ok = False

        # Check "keys" and "total_values" in processed output
        has_keys = "'keys'" in logs or '"keys"' in logs
        has_total_values = "'total_values'" in logs or '"total_values"' in logs
        checks.append(f"'keys' in processed output: {has_keys}")
        checks.append(f"'total_values' in processed output: {has_total_values}")
        if not has_keys or not has_total_values:
            all_ok = False

        # Check results/output.json exists in container
        file_data = copy_from_container(
            client, container_id, "/app/results/output.json"
        )
        if file_data is None:
            file_data = copy_from_container(
                client, container_id, "results/output.json"
            )

        if file_data:
            try:
                output = json.loads(file_data.decode("utf-8"))
                checks.append(
                    f"results/output.json exists, valid JSON, keys: {list(output.keys())}"
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                checks.append("results/output.json exists but invalid JSON")
                all_ok = False
        else:
            checks.append("results/output.json not found in container")
            all_ok = False

        return all_ok, f"{'PASS' if all_ok else 'FAIL'} - {'; '.join(checks)}"
