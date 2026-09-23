#!/usr/bin/env python3
"""
Autonomous Multi-Agent Triad: Ambient HTTP Server (server.py).
Provides high-availability, zero-token-rent HTTP daemon for:
- /health: Subsystem status and advisor health checks
- /telemetry: Real-time Council session metrics & adjudication history
- /auto: Remote intent classification and autonomous routing
- /gate: Pre-commit ground-truth gate verification
- /review: Dual-advisor diff review & consensus synthesis
"""

import sys
import os
import json
import time
import socket
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from triad.advisor_manager import query_configured_advisor, get_advisors
    from triad.competition import query_competition_council, COUNCIL_SESSIONS_LOG
    from triad.intent_engine import classify_intent
    from triad.worktree import isolated_worktree, get_repo_root
except ImportError:
    from advisor_manager import query_configured_advisor, get_advisors
    from competition import query_competition_council, COUNCIL_SESSIONS_LOG
    from intent_engine import classify_intent
    from worktree import isolated_worktree, get_repo_root


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Quick TCP connect check with guaranteed socket cleanup."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def get_telemetry_summary(limit: int = 50) -> Dict[str, Any]:
    """Read council_sessions.jsonl and aggregate metrics."""
    sessions = []
    if COUNCIL_SESSIONS_LOG.exists():
        try:
            with open(COUNCIL_SESSIONS_LOG, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            sessions.append(json.loads(line))
                        except Exception:
                            continue
        except Exception as e:
            print(f"[Server Warning] Failed reading telemetry log: {e}", file=sys.stderr)

    total_sessions = len(sessions)
    modes: Dict[str, int] = {}
    advisors_count: Dict[str, int] = {}
    total_elapsed = 0.0

    for s in sessions:
        m = s.get("mode", "unknown")
        modes[m] = modes.get(m, 0) + 1
        for adv in s.get("advisors", []):
            advisors_count[adv] = advisors_count.get(adv, 0) + 1
        total_elapsed += float(s.get("elapsed_seconds", 0.0))

    avg_elapsed = round(total_elapsed / total_sessions, 2) if total_sessions > 0 else 0.0
    recent_sessions = list(reversed(sessions[-limit:]))

    return {
        "total_sessions": total_sessions,
        "modes": modes,
        "advisors_used": advisors_count,
        "avg_elapsed_seconds": avg_elapsed,
        "sessions": recent_sessions,
    }


class TriadRequestHandler(BaseHTTPRequestHandler):
    """Multi-threaded request handler for Triad Ambient HTTP Bridge."""

    server_version = "TriadHTTP/1.0"

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-webhook-token")

    def _send_json(self, status_code: int, data: Any):
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/health"):
            advisors = get_advisors()
            resp = {
                "status": "ok",
                "service": "autonomous-triad",
                "version": "1.0.0",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "advisors": advisors,
                "subsystems": {
                    "pieces_os": is_port_open("127.0.0.1", 39300),
                    "hermes_relay": is_port_open("127.0.0.1", 8766),
                    "pieces_proxy": is_port_open("127.0.0.1", 8787),
                    "ollama": is_port_open("127.0.0.1", 11434),
                },
            }
            self._send_json(200, resp)
            return

        if path == "/telemetry":
            limit_val = 50
            if "limit" in query_params:
                try:
                    limit_val = max(1, min(500, int(query_params["limit"][0])))
                except ValueError:
                    pass
            data = get_telemetry_summary(limit=limit_val)
            self._send_json(200, data)
            return

        self._send_json(404, {"error": "Not Found", "path": path})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Read JSON body
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len <= 0:
            self._send_json(400, {"error": "Empty or missing request body"})
            return

        body_raw = self.rfile.read(content_len).decode("utf-8", errors="replace")
        try:
            body = json.loads(body_raw)
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON body: {e}"})
            return

        if path == "/auto":
            self._handle_auto(body)
            return

        if path == "/review":
            self._handle_review(body)
            return

        self._send_json(404, {"error": "Not Found", "path": path})

    def _handle_auto(self, body: Dict[str, Any]):
        prompt = str(body.get("prompt", "")).strip()
        context = body.get("context", "")
        diff = body.get("diff", "")
        force_competition = bool(body.get("competition", False))
        use_worktree = bool(body.get("worktree", False))
        ref = str(body.get("ref", "HEAD"))

        if not prompt and not diff:
            self._send_json(400, {"error": "Prompt or diff is required"})
            return

        classification = classify_intent(prompt, context=context, diff=diff)
        if force_competition:
            classification.suggested_engine = "competition"

        # If worktree is requested, execute inside isolated worktree
        if use_worktree:
            try:
                repo_root = get_repo_root(".")
                with isolated_worktree(repo_root, branch_or_commit=ref, prefix="triad-http-auto", cd=True):
                    result = self._execute_remote_intent(classification, prompt, context, diff)
            except Exception as e:
                self._send_json(500, {
                    "error": f"Worktree execution failed: {e}",
                    "intent": classification.intent
                })
                return
        else:
            result = self._execute_remote_intent(classification, prompt, context, diff)

        self._send_json(200, {
            "status": "success",
            "intent": classification.intent,
            "confidence": classification.confidence,
            "reason": classification.reason,
            "suggested_mode": classification.suggested_mode,
            "suggested_engine": classification.suggested_engine,
            "high_stakes": classification.high_stakes,
            "result": result,
        })

    def _execute_remote_intent(self, classification, prompt: str, context: str, diff: str) -> Any:
        intent = classification.intent
        engine = classification.suggested_engine

        if intent == "REVIEW":
            if engine == "competition":
                session = query_competition_council(prompt or "Review this diff", context=context, diff=diff, mode="review_diff")
                return {"synthesis": session["synthesis"], "advisors": session["advisors"]}
            resp = query_configured_advisor("auto", prompt or "Review this diff", context=context, diff=diff, mode="review_diff")
            return {"response": resp}

        if intent in ("ARCHITECT", "GENERAL"):
            if engine == "competition":
                session = query_competition_council(prompt, context=context, mode="architect")
                return {"synthesis": session["synthesis"], "advisors": session["advisors"]}
            resp = query_configured_advisor("auto", prompt, context=context, mode="architect")
            return {"response": resp}

        if intent == "DEBUG":
            if engine == "competition":
                session = query_competition_council(prompt, context=context, mode="debug")
                return {"synthesis": session["synthesis"], "advisors": session["advisors"]}
            resp = query_configured_advisor("auto", prompt, context=context, mode="debug")
            return {"response": resp}

        if intent == "DOCTOR":
            return {
                "pieces_os": is_port_open("127.0.0.1", 39300),
                "hermes_relay": is_port_open("127.0.0.1", 8766),
                "pieces_proxy": is_port_open("127.0.0.1", 8787),
                "ollama": is_port_open("127.0.0.1", 11434),
                "advisors": get_advisors(),
            }

        if intent == "DEVICE":
            bridge_alive = is_port_open("127.0.0.1", 8766)
            return {
                "bridge_online": bridge_alive,
                "port": 8766,
                "status": "ready" if bridge_alive else "standby",
                "message": "Android relay connected" if bridge_alive else "Dial phone app com.hermesandroid.bridge",
            }

        if intent == "MEMORY":
            pieces_alive = is_port_open("127.0.0.1", 39300)
            return {
                "pieces_os_online": pieces_alive,
                "mem0_configured": Path(r"C:\Users\micha\.agents\skills\mem0\mem0.js").exists(),
                "query": prompt,
            }

        return {"message": f"Intent {intent} received"}

    def _handle_review(self, body: Dict[str, Any]):
        prompt = str(body.get("prompt", "")).strip() or "Review this diff"
        diff = str(body.get("diff", "")).strip()
        context = str(body.get("context", "")).strip()
        competition = bool(body.get("competition", False))
        engine = str(body.get("engine", "auto"))

        if not diff:
            self._send_json(400, {"error": "Diff content is required for /review"})
            return

        if competition:
            session = query_competition_council(prompt, context=context, diff=diff, mode="review_diff")
            self._send_json(200, {
                "status": "success",
                "mode": "competition",
                "synthesis": session["synthesis"],
                "advisors": session["advisors"],
                "elapsed_seconds": session["elapsed_seconds"],
            })
        else:
            resp = query_configured_advisor(engine, prompt, context=context, diff=diff, mode="review_diff")
            self._send_json(200, {
                "status": "success",
                "mode": "single",
                "engine": engine,
                "response": resp,
            })

    def log_message(self, format, *args):
        # Override standard logging to provide clean one-line Triad server logs
        print(f"[Triad Server] {self.address_string()} - {format % args}")


def start_server(host: str = "127.0.0.1", port: int = 8789) -> None:
    """Start Triad Ambient HTTP server listening until interrupted."""
    server_address = (host, port)
    try:
        httpd = ThreadingHTTPServer(server_address, TriadRequestHandler)
    except OSError as e:
        print(f"[Triad Server Error] Could not bind to {host}:{port}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"================================================================================")
    print(f"           AUTONOMOUS MULTI-AGENT TRIAD: AMBIENT HTTP BRIDGE                    ")
    print(f"================================================================================")
    print(f"Listening on http://{host}:{port}")
    print(f"Endpoints:")
    print(f"  - GET  /health      System health, subsystem connectivity, and advisor status")
    print(f"  - GET  /telemetry   Real-time Council adjudication history & session stats")
    print(f"  - POST /auto        Sub-millisecond intent classification & autonomous execution")
    print(f"  - POST /review      Diff review and dual-advisor competition consensus")
    print(f"Press Ctrl+C to terminate.")
    print(f"================================================================================\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Triad Server] Shutting down...")
    finally:
        httpd.server_close()
        print("[Triad Server] Stopped.")


if __name__ == "__main__":
    port = int(os.environ.get("TRIAD_PORT", 8789))
    start_server(port=port)
