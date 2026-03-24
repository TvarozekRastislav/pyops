"""Validator for a2_dependencies: sensor data processor with visualization."""

from __future__ import annotations

import re

import docker

from ..docker_utils import copy_from_container
from .base import BaseValidator


class A2Validator(BaseValidator):
    is_server = False
    container_timeout = 120.0  # extra time for pip install

    @property
    def app_name(self) -> str:
        return "a2_dependencies"

    def check_s3(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Check stdout has sensor data markers and 'Saved to:'."""
        checks = []

        has_sensor = (
            "Generating sensor data" in logs or "sensor data" in logs.lower()
        )
        checks.append(f"sensor data marker: {has_sensor}")

        has_cleaning = (
            "Cleaning" in logs
            or "cleaning" in logs.lower()
            or "Clean records" in logs
        )
        checks.append(f"cleaning marker: {has_cleaning}")

        has_saved = "Saved to:" in logs
        checks.append(f"'Saved to:' in output: {has_saved}")

        passed = has_sensor and has_saved
        return passed, f"{'PASS' if passed else 'FAIL'} - {'; '.join(checks)}"

    def check_s4(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Deep: PNG exists + >1KB, per-sensor stats, anomalies removed with N>0."""
        checks = []
        all_ok = True

        # Check PNG file exists in container and is >1KB
        png_data = copy_from_container(
            client, container_id, "/app/sensor_report.png"
        )
        if png_data is None:
            png_data = copy_from_container(
                client, container_id, "sensor_report.png"
            )

        if png_data and len(png_data) > 1024:
            checks.append(f"PNG exists, size={len(png_data)} bytes (>1KB)")
        else:
            size = len(png_data) if png_data else 0
            checks.append(f"PNG check failed: size={size}")
            all_ok = False

        # Check per-sensor stats in output (S1, S2, S3 sensor IDs)
        has_sensor_stats = any(s in logs for s in ["S1", "S2", "S3"])
        checks.append(f"per-sensor stats present: {has_sensor_stats}")
        if not has_sensor_stats:
            all_ok = False

        # Check "removed N anomalies" with N > 0
        anomaly_match = re.search(r"removed\s+(\d+)\s+anomal", logs)
        if anomaly_match:
            n_removed = int(anomaly_match.group(1))
            checks.append(f"anomalies removed: {n_removed}")
            if n_removed <= 0:
                all_ok = False
        else:
            checks.append("anomaly removal not reported")
            all_ok = False

        return all_ok, f"{'PASS' if all_ok else 'FAIL'} - {'; '.join(checks)}"
