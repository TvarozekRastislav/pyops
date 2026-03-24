"""Validator for a4_server: FastAPI inventory REST API."""

from __future__ import annotations

import httpx
import docker

from .base import BaseValidator


class A4Validator(BaseValidator):
    is_server = True
    container_timeout = 30.0

    @property
    def app_name(self) -> str:
        return "a4_server"

    def _get_ports(self) -> dict:
        host_port = getattr(self, "_allocated_port", 8000)
        return {"8000/tcp": host_port}

    def check_s3(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Basic: /health -> 200, GET /items -> 200."""
        checks = []
        base = f"http://localhost:{self._allocated_port}"
        all_ok = True

        try:
            r = httpx.get(f"{base}/health", timeout=10)
            checks.append(f"/health -> {r.status_code}")
            if r.status_code != 200:
                all_ok = False
        except Exception as e:
            checks.append(f"/health -> error: {e}")
            all_ok = False

        try:
            r = httpx.get(f"{base}/items", timeout=10)
            checks.append(f"GET /items -> {r.status_code}")
            if r.status_code != 200:
                all_ok = False
        except Exception as e:
            checks.append(f"GET /items -> error: {e}")
            all_ok = False

        return all_ok, f"{'PASS' if all_ok else 'FAIL'} - {'; '.join(checks)}"

    def check_s4(
        self, container_id: str, logs: str, client: docker.DockerClient
    ) -> tuple[bool, str]:
        """Deep: full CRUD cycle + stats verification."""
        checks = []
        base = f"http://localhost:{self._allocated_port}"
        all_ok = True

        try:
            # POST -> 201
            item = {"name": "TestWidget", "quantity": 10, "price": 9.99}
            r = httpx.post(f"{base}/items", json=item, timeout=10)
            checks.append(f"POST /items -> {r.status_code}")
            if r.status_code != 201:
                all_ok = False
                return all_ok, f"FAIL - {'; '.join(checks)}"

            created = r.json()
            item_id = created.get("id")
            checks.append(f"created id={item_id}")

            # GET returns the item
            r = httpx.get(f"{base}/items/{item_id}", timeout=10)
            checks.append(f"GET /items/{item_id} -> {r.status_code}")
            if r.status_code != 200:
                all_ok = False
            else:
                got = r.json()
                if got.get("name") != "TestWidget":
                    checks.append(f"name mismatch: {got.get('name')}")
                    all_ok = False

            # PUT modifies
            r = httpx.put(
                f"{base}/items/{item_id}", json={"quantity": 20}, timeout=10
            )
            checks.append(f"PUT /items/{item_id} -> {r.status_code}")
            if r.status_code != 200:
                all_ok = False
            else:
                updated = r.json()
                if updated.get("quantity") != 20:
                    checks.append(
                        f"quantity not updated: {updated.get('quantity')}"
                    )
                    all_ok = False

            # /stats reflects changes
            r = httpx.get(f"{base}/stats", timeout=10)
            checks.append(f"GET /stats -> {r.status_code}")
            if r.status_code == 200:
                stats = r.json()
                if stats.get("unique_products", 0) < 1:
                    checks.append("stats.unique_products < 1")
                    all_ok = False
                checks.append(f"stats: {stats}")

            # DELETE -> 204
            r = httpx.delete(f"{base}/items/{item_id}", timeout=10)
            checks.append(f"DELETE /items/{item_id} -> {r.status_code}")
            if r.status_code != 204:
                all_ok = False

            # Verify deleted
            r = httpx.get(f"{base}/items/{item_id}", timeout=10)
            if r.status_code != 404:
                checks.append(
                    f"item still exists after delete: {r.status_code}"
                )
                all_ok = False

        except Exception as e:
            checks.append(f"error during CRUD: {e}")
            all_ok = False

        return all_ok, f"{'PASS' if all_ok else 'FAIL'} - {'; '.join(checks)}"
