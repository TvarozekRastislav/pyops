"""Validator for a5_configurable: batch data processor with config."""

from __future__ import annotations

import json

import docker

from .base import BaseValidator


class A5Validator(BaseValidator):
    is_server = False
    container_timeout = 30.0

    @property
    def app_name(self) -> str:
        return "a5_configurable"

    def check_s3(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Check stdout has 'Loading configuration'."""
        checks = []
        has_loading = "Loading configuration" in logs
        checks.append(f"'Loading configuration' in output: {has_loading}")

        passed = has_loading
        return passed, f"{'PASS' if passed else 'FAIL'} - {'; '.join(checks)}"

    def check_s4(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Deep: output is valid JSON with batch_results, verify sum(1..50)=1275, config values match."""
        checks = []
        all_ok = True

        # Find the JSON output in logs (after "Results (json):")
        json_start = logs.find("Results (json):")
        if json_start == -1:
            json_start = logs.find("Results (")

        if json_start == -1:
            checks.append("Results section not found in output")
            return False, f"FAIL - {'; '.join(checks)}"

        # Extract JSON from after the results header
        json_text = logs[json_start:]
        brace_start = json_text.find("{")
        if brace_start == -1:
            checks.append("No JSON object found after Results header")
            return False, f"FAIL - {'; '.join(checks)}"

        json_text = json_text[brace_start:]
        # Find matching closing brace
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

        if end == 0:
            checks.append("Unbalanced JSON braces")
            return False, f"FAIL - {'; '.join(checks)}"

        try:
            results = json.loads(json_text[:end])
        except json.JSONDecodeError as e:
            checks.append(f"JSON parse error: {e}")
            return False, f"FAIL - {'; '.join(checks)}"

        # Check batch_results present
        batch_results = results.get("batch_results")
        if not batch_results:
            checks.append("batch_results missing or empty")
            all_ok = False
        else:
            checks.append(f"batch_results count: {len(batch_results)}")

            # Verify batch math: sum of 1..50 = 1275
            total_sum = sum(b.get("sum", 0) for b in batch_results)
            checks.append(
                f"total sum across batches: {total_sum} (expected 1275)"
            )
            if total_sum != 1275:
                all_ok = False

            # Verify total records
            total_records = results.get("total_records", 0)
            checks.append(f"total_records: {total_records} (expected 50)")
            if total_records != 50:
                all_ok = False

        # Check config values reflected (must differ from default "DataProcessor")
        app_name = results.get("app_name")
        checks.append(f"app_name: {app_name}")
        if app_name != "DataProcessor-Configured":
            all_ok = False

        return all_ok, f"{'PASS' if all_ok else 'FAIL'} - {'; '.join(checks)}"
