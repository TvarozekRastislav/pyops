"""Validator for a1_simple_script: multiplication table with statistics."""

from __future__ import annotations

import re

import docker

from .base import BaseValidator


class A1Validator(BaseValidator):
    is_server = False
    container_timeout = 30.0

    @property
    def app_name(self) -> str:
        return "a1_simple_script"

    def check_s3(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Check stdout has 'Multiplication table' and 'Statistics for values'."""
        checks = []
        has_table = "Multiplication table" in logs
        checks.append(f"'Multiplication table' in output: {has_table}")

        has_stats = "Statistics for values" in logs
        checks.append(f"'Statistics for values' in output: {has_stats}")

        passed = has_table and has_stats
        return passed, f"{'PASS' if passed else 'FAIL'} - {'; '.join(checks)}"

    def check_s4(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Deep: parse table, verify 5x5 cells, check math (mean=13, sum=325)."""
        checks = []
        all_ok = True

        # Extract table lines between "Multiplication table" header and blank/stats
        lines = logs.split("\n")
        table_lines = []
        in_table = False
        for line in lines:
            if "Multiplication table" in line:
                in_table = True
                continue
            if in_table:
                if line.strip() == "" or "Statistics" in line:
                    break
                table_lines.append(line)

        # Verify 5 rows
        if len(table_lines) == 5:
            checks.append("table has 5 rows: True")
        else:
            checks.append(f"table has 5 rows: False (got {len(table_lines)})")
            all_ok = False

        # Verify each row has 5 values, total 25 cells, spot-check values
        cell_count = 0
        found_25 = False
        for i, line in enumerate(table_lines):
            values = line.split()
            cell_count += len(values)
            if "25" in values:
                found_25 = True
            # Check last column: row (i+1), col 5 → (i+1)*5
            if len(values) == 5:
                try:
                    last_val = int(values[-1])
                    expected = (i + 1) * 5
                    if last_val != expected:
                        checks.append(
                            f"row {i + 1} last cell: expected {expected}, got {last_val}"
                        )
                        all_ok = False
                except ValueError:
                    pass

        checks.append(f"total cells: {cell_count} (expected 25)")
        if cell_count != 25:
            all_ok = False

        checks.append(f"found 25 in table: {found_25}")
        if not found_25:
            all_ok = False

        # Verify mean of 1..25 = 13.0
        mean_match = re.search(r"mean:\s*([\d.]+)", logs)
        if mean_match:
            mean_val = float(mean_match.group(1))
            checks.append(f"mean={mean_val} (expected 13.0)")
            if abs(mean_val - 13.0) > 0.01:
                all_ok = False
        else:
            checks.append("mean not found in output")
            all_ok = False

        # Verify count = 25
        count_match = re.search(r"count:\s*(\d+)", logs)
        if count_match:
            count_val = int(count_match.group(1))
            checks.append(f"count={count_val} (expected 25)")
            if count_val != 25:
                all_ok = False

        # Verify sum = 325
        sum_match = re.search(r"sum:\s*([\d.]+)", logs)
        if sum_match:
            sum_val = float(sum_match.group(1))
            checks.append(f"sum={sum_val} (expected 325.0)")
            if abs(sum_val - 325.0) > 0.01:
                all_ok = False

        return all_ok, f"{'PASS' if all_ok else 'FAIL'} - {'; '.join(checks)}"
