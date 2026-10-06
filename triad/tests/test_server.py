#!/usr/bin/env python3
"""
Unit tests for Triad Ambient HTTP Server (triad/server.py).
Tests:
- Server startup and graceful shutdown
- GET /health (service, version, subsystems, advisors)
- GET /telemetry (sessions aggregate metrics, pagination)
- POST /auto (intent classification and execution)
- POST /review (diff review endpoints)
- CORS header verification
"""

import json
import time
import socket
import urllib.request
import urllib.error
import threading
import unittest
from http.server import ThreadingHTTPServer

from triad.server import TriadRequestHandler


def find_free_port() -> int:
    """Locate an available local ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestTriadServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = find_free_port()
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), TriadRequestHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2.0)

    def _get(self, path: str, extra_headers: dict = None):
        url = f"{self.base_url}{path}"
        h = {"Connection": "close"}
        if extra_headers:
            h.update(extra_headers)
        req = urllib.request.Request(url, headers=h, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = resp.read().decode("utf-8")
                return resp.status, resp.headers, json.loads(data)
        except urllib.error.HTTPError as exc:
            data = exc.read().decode("utf-8")
            try:
                payload = json.loads(data) if data else {}
            except Exception:
                payload = {"raw": data}
            return exc.code, exc.headers, payload

    def _post(self, path: str, payload: dict, extra_headers: dict = None):
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        h = {"Content-Type": "application/json", "Connection": "close"}
        if extra_headers:
            h.update(extra_headers)
        req = urllib.request.Request(url, data=body, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = resp.read().decode("utf-8")
                return resp.status, resp.headers, json.loads(data)
        except urllib.error.HTTPError as exc:
            data = exc.read().decode("utf-8")
            try:
                payload = json.loads(data) if data else {}
            except Exception:
                payload = {"raw": data}
            return exc.code, exc.headers, payload

    def test_health_endpoint(self):
        status, headers, body = self._get("/health", extra_headers={"Origin": "http://localhost:3000"})
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(body.get("service"), "autonomous-triad")
        self.assertIn("subsystems", body)
        self.assertIn("advisors", body)
        self.assertIn("circuits", body)
        # Check CORS
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://localhost:3000")

    def test_root_alias_to_health(self):
        status, _, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "ok")

    def test_telemetry_endpoint(self):
        from unittest.mock import patch
        # Unauthenticated request returns 401
        with patch("triad.server.SERVER_TOKEN", ""):
            status, _, body = self._get("/telemetry")
            self.assertEqual(status, 401)
            self.assertIn("error", body)

        # Authenticated request returns 200 and telemetry data
        with patch("triad.server.SERVER_TOKEN", "mock-telemetry-token"):
            status, _, body = self._get("/telemetry", extra_headers={"Authorization": "Bearer mock-telemetry-token"})
            self.assertEqual(status, 200)
            self.assertIn("total_sessions", body)
            self.assertIn("modes", body)
            self.assertIn("sessions", body)
            self.assertIsInstance(body["sessions"], list)

    def test_auto_doctor_intent(self):
        status, _, body = self._post("/auto", {"prompt": "triad doctor system health"})
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "success")
        self.assertEqual(body.get("intent"), "DOCTOR")
        self.assertIn("result", body)
        self.assertIn("advisors", body["result"])

    def test_auto_debug_intent(self):
        from unittest.mock import patch
        with patch("triad.server.query_configured_advisor", return_value="Mock debug fix"):
            status, _, body = self._post("/auto", {
                "prompt": "why is this failing? Traceback: TypeError: undefined is not a function",
                "context": "const x = null; x();"
            })
            self.assertEqual(status, 200)
            self.assertEqual(body.get("status"), "success")
            self.assertEqual(body.get("intent"), "DEBUG")
            self.assertIn("result", body)

    def test_auto_device_intent(self):
        status, _, body = self._post("/auto", {"prompt": "check android phone notification"})
        self.assertEqual(status, 200)
        self.assertEqual(body.get("intent"), "DEVICE")
        self.assertIn("result", body)
        self.assertIn("bridge_online", body["result"])

    def test_auto_memory_intent(self):
        status, _, body = self._post("/auto", {"prompt": "what was done on past workstream?"})
        self.assertEqual(status, 200)
        self.assertEqual(body.get("intent"), "MEMORY")
        self.assertIn("result", body)
        self.assertIn("pieces_os_online", body["result"])

    def test_auto_worktree_is_not_implemented(self):
        url = f"{self.base_url}/auto"
        body = json.dumps({"prompt": "triad doctor system health", "worktree": True}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10.0)
            self.fail("worktree request should be rejected")
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            self.assertEqual(exc.code, 501)
            self.assertIn("triad auto --worktree", payload.get("error", ""))

    def test_cors_options_preflight(self):
        url = f"{self.base_url}/auto"
        # 1. Valid localhost origin -> returned in header
        req = urllib.request.Request(url, headers={"Origin": "http://localhost:8080"}, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://localhost:8080")
            self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods", ""))

        # 2. Spoofed attacker prefix -> no CORS header
        req = urllib.request.Request(url, headers={"Origin": "http://localhost.attacker.com"}, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 204)
            self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

        # 3. Null origin -> no CORS header
        req = urllib.request.Request(url, headers={"Origin": "null"}, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 204)
            self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

    def test_content_type_json_required(self):
        url = f"{self.base_url}/auto"
        body = b"plain text prompt"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "text/plain"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5.0)
            self.fail("text/plain POST should be rejected with 415")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 415)
            exc.close()

    def test_health_advisors_sanitized(self):
        status, _, body = self._get("/health")
        self.assertEqual(status, 200)
        advisors = body.get("advisors", [])
        self.assertTrue(len(advisors) > 0)
        for adv in advisors:
            self.assertNotIn("env", adv)
            self.assertNotIn("binary_path", adv)
            self.assertIn("name", adv)
            self.assertIn("priority", adv)

    def test_action_endpoints(self):
        import os
        from unittest.mock import patch

        # 1. When SERVER_TOKEN is unset, action endpoints must fail closed (401)
        with patch("triad.server.SERVER_TOKEN", ""):
            status, _, body = self._post("/action/approve", {"reason": "Unauthed attempt"})
            self.assertEqual(status, 401)
            self.assertIn("error", body)

            status, _, body = self._post("/action/reject", {"reason": "Unauthed attempt"})
            self.assertEqual(status, 401)

        # 2. When SERVER_TOKEN is configured:
        with patch("triad.server.SERVER_TOKEN", "secret-token-123"):
            # Missing token header -> 401
            status, _, body = self._post("/action/approve", {"reason": "No auth header"})
            self.assertEqual(status, 401)

            # Invalid token -> 401
            status, _, body = self._post("/action/approve", {"reason": "Wrong token"}, extra_headers={"Authorization": "Bearer bad-token"})
            self.assertEqual(status, 401)

            # Valid token with invalid repo path -> 400
            auth_headers = {"Authorization": "Bearer secret-token-123"}
            status, _, body = self._post("/action/approve", {"repo_path": "nonexistent_dir_12345"}, extra_headers=auth_headers)
            self.assertEqual(status, 400)
            self.assertIn("not a valid git repository", body.get("error", ""))

            # Valid token with unsafe patch path -> 400
            status, _, body = self._post("/action/approve", {"patch_file": "C:/Windows/System32/cmd.exe"}, extra_headers=auth_headers)
            self.assertEqual(status, 400)
            self.assertIn("Invalid patch_file", body.get("error", ""))

            # Valid token with an unapplyable patch in PATCHES_DIR
            from triad.server import PATCHES_DIR
            import hashlib
            patch_content = b"# empty dummy patch\n"
            dummy_sha = hashlib.sha256(patch_content).hexdigest()
            temp_patch_path = str(PATCHES_DIR / "test_conflict.patch")
            with open(temp_patch_path, "wb") as pf:
                pf.write(patch_content)

            try:
                # Missing patch_sha256 -> 400
                status, _, body = self._post("/action/approve", {"patch_file": temp_patch_path}, extra_headers=auth_headers)
                self.assertEqual(status, 400)
                self.assertIn("patch_sha256 required", body.get("error", ""))

                # Disallowed repo in TRIAD_ALLOWED_REPOS -> 403
                with patch.dict(os.environ, {"TRIAD_ALLOWED_REPOS": "C:/completely/different/repo"}):
                    status, _, body = self._post("/action/approve", {
                        "patch_file": temp_patch_path,
                        "patch_sha256": dummy_sha,
                    }, extra_headers=auth_headers)
                    self.assertEqual(status, 403)
                    self.assertIn("TRIAD_ALLOWED_REPOS", body.get("error", ""))

                status, _, body = self._post("/action/approve", {
                    "patch_file": temp_patch_path,
                    "patch_sha256": dummy_sha,
                    "reason": "Conflict patch"
                }, extra_headers=auth_headers)
                self.assertEqual(status, 409)
                self.assertEqual(body.get("status"), "conflict")
                self.assertIn("does not apply cleanly", body.get("error", ""))

                # Mismatched SHA256 -> 409 Conflict
                status, _, body = self._post("/action/approve", {
                    "patch_file": temp_patch_path,
                    "patch_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                }, extra_headers=auth_headers)
                self.assertEqual(status, 409)
                self.assertEqual(body.get("status"), "conflict")
                self.assertIn("digest mismatch", body.get("error", ""))
            finally:
                try:
                    import os
                    os.unlink(temp_patch_path)
                except Exception:
                    pass

            # Action approve without patch file (e.g. manual gate approval) -> 200
            status, _, body = self._post("/action/approve", {"reason": "Approved without patch"}, extra_headers=auth_headers)
            self.assertEqual(status, 200)
            self.assertEqual(body.get("status"), "approved")
            self.assertFalse(body.get("patch_applied"))

            # Action reject with valid token -> 200
            status, _, body = self._post("/action/reject", {"reason": "Test rejection"}, extra_headers=auth_headers)
            self.assertEqual(status, 200)
            self.assertEqual(body.get("status"), "rejected")

    def test_auto_doctor_sanitizes_advisors(self):
        status, _, body = self._post("/auto", {"prompt": "triad doctor check system health and subscriptions"})
        self.assertEqual(status, 200)
        self.assertEqual(body.get("intent"), "DOCTOR")
        res = body.get("result", {})
        advisors = res.get("advisors", [])
        self.assertTrue(len(advisors) > 0)
        for adv in advisors:
            self.assertNotIn("env", adv)
            self.assertNotIn("binary_path", adv)
            self.assertIn("name", adv)


class TestResolveRepoPathContainment(unittest.TestCase):
    def test_allowlist_enforced_inside_resolver(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from triad.server import RepoNotAllowed, _resolve_repo_path

        with tempfile.TemporaryDirectory() as td:
            allowed = Path(td) / "repo"
            sibling = Path(td) / "repo_evil"
            for d in (allowed, sibling):
                d.mkdir()
                subprocess.run(["git", "init", "-q", str(d)], check=True)
            with patch.dict(os.environ, {"TRIAD_ALLOWED_REPOS": str(allowed)}):
                self.assertEqual(_resolve_repo_path(str(allowed)).resolve(), allowed.resolve())
                with self.assertRaises(RepoNotAllowed):
                    _resolve_repo_path(str(sibling))  # shares a name prefix, must not pass
                with self.assertRaises(RepoNotAllowed):
                    _resolve_repo_path(str(allowed / ".." / "repo_evil"))
                self.assertIsNone(_resolve_repo_path(str(allowed / "missing_dir")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
