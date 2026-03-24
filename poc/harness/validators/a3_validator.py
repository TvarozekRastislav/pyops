"""Validator for a3_modular: data pipeline with extract/transform/load/report."""

from __future__ import annotations

import json

import docker

from ..docker_utils import copy_from_container
from .base import BaseValidator


class A3Validator(BaseValidator):
    is_server = False
    container_timeout = 30.0

    @property
    def app_name(self) -> str:
        return "a3_modular"

    def check_s3(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Check stdout has pipeline step markers."""
        checks = []
        markers = ["[1/4]", "[2/4]", "[3/4]", "[4/4]"]
        found = [m for m in markers if m in logs]
        checks.append(f"pipeline markers found: {len(found)}/4")

        has_report = (
            "Pipeline Report" in logs
            or "Results saved" in logs
            or "saved to" in logs.lower()
        )
        checks.append(f"report/save marker: {has_report}")

        passed = len(found) >= 3 and has_report
        return passed, f"{'PASS' if passed else 'FAIL'} - {'; '.join(checks)}"

    def check_s4(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Deep: output/processed.json is valid JSON with hour, day_of_week, temp_category; count > 0."""
        checks = []
        all_ok = True

        # Extract processed.json from container
        file_data = copy_from_container(
            client, container_id, "/app/output/processed.json"
        )
        if file_data is None:
            file_data = copy_from_container(
                client, container_id, "output/processed.json"
            )

        if file_data is None:
            checks.append("output/processed.json not found in container")
            return False, f"FAIL - {'; '.join(checks)}"

        try:
            records = json.loads(file_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            checks.append(f"JSON parse error: {e}")
            return False, f"FAIL - {'; '.join(checks)}"

        if not isinstance(records, list):
            checks.append(f"expected list, got {type(records).__name__}")
            return False, f"FAIL - {'; '.join(checks)}"

        checks.append(f"record count: {len(records)}")
        if len(records) == 0:
            all_ok = False

        # Check required enriched fields
        required = {"hour", "day_of_week", "temp_category"}
        if records:
            sample = records[0]
            present = required.intersection(sample.keys())
            missing = required - present
            checks.append(f"required fields present: {present}")
            if missing:
                checks.append(f"missing fields: {missing}")
                all_ok = False

        return all_ok, f"{'PASS' if all_ok else 'FAIL'} - {'; '.join(checks)}"
