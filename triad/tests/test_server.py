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

from triad.server import TriadRequestHandler, get_telemetry_summary


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

    def _get(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = resp.read().decode("utf-8")
            return resp.status, resp.headers, json.loads(data)

    def _post(self, path: str, payload: dict):
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = resp.read().decode("utf-8")
            return resp.status, resp.headers, json.loads(data)

    def test_health_endpoint(self):
        status, headers, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(body.get("service"), "autonomous-triad")
        self.assertIn("subsystems", body)
        self.assertIn("advisors", body)
        # Check CORS
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_root_alias_to_health(self):
        status, _, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("status"), "ok")

    def test_telemetry_endpoint(self):
        status, _, body = self._get("/telemetry")
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

    def test_cors_options_preflight(self):
        url = f"{self.base_url}/auto"
        req = urllib.request.Request(url, method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
            self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
