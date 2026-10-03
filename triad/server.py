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
import subprocess
import threading
import hmac
import hashlib
import json
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Any, Optional, List

try:
    from triad import __version__ as TRIAD_VERSION
except Exception:
    TRIAD_VERSION = "0.0.0"

try:
    from triad.advisor_manager import query_configured_advisor, get_advisors, ADVISOR_CALLS_LOG
    from triad.competition import query_competition_council, COUNCIL_SESSIONS_LOG
    from triad.intent_engine import classify_intent
    from triad.procutil import is_port_open, clean_git_env
    from triad.paths import MEM0_SCRIPT, PORT_HERMES_RELAY, PORT_PIECES_PROXY, PORT_PIECES_OS, PORT_OLLAMA, PORT_TRIAD_SERVER
    from triad.circuit import snapshot_circuits
except ImportError:
    from advisor_manager import query_configured_advisor, get_advisors, ADVISOR_CALLS_LOG
    from competition import query_competition_council, COUNCIL_SESSIONS_LOG
    from intent_engine import classify_intent
    from procutil import is_port_open, clean_git_env
    from paths import MEM0_SCRIPT, PORT_HERMES_RELAY, PORT_PIECES_PROXY, PORT_PIECES_OS, PORT_OLLAMA, PORT_TRIAD_SERVER
    from circuit import snapshot_circuits

def _safe_int_env(var: str, default: int) -> int:
    try:
        val = os.environ.get(var, "").strip()
        return int(val) if val else default
    except (ValueError, TypeError):
        return default

MAX_BODY_BYTES = _safe_int_env("TRIAD_MAX_BODY_BYTES", 4 * 1024 * 1024)  # 4 MiB
SERVER_TOKEN = os.environ.get("TRIAD_SERVER_TOKEN", "").strip()
PATCHES_DIR = (Path.home() / ".agents" / "triad" / "patches").resolve()
try:
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


_REPO_LOCKS: Dict[str, threading.Lock] = {}
_REPO_LOCKS_GUARD = threading.Lock()


def _get_repo_lock(repo_dir: Path) -> threading.Lock:
    key = str(repo_dir.resolve()).lower() if sys.platform == "win32" else str(repo_dir.resolve())
    with _REPO_LOCKS_GUARD:
        if key not in _REPO_LOCKS:
            _REPO_LOCKS[key] = threading.Lock()
        return _REPO_LOCKS[key]


def _resolve_repo_path(repo_arg: Optional[str]) -> Optional[Path]:
    target = Path(repo_arg).resolve() if repo_arg else Path.cwd().resolve()
    if not target.is_dir():
        return None
    try:
        ret = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(target), env=clean_git_env(), capture_output=True, text=True, timeout=5)
        if ret.returncode == 0 and ret.stdout.strip():
            return Path(ret.stdout.strip()).resolve()
    except Exception:
        pass
def _public_advisors() -> List[Dict[str, Any]]:
    """Return public, sanitized advisor list stripped of sensitive env vars and local paths."""
    return [
        {
            "name": a.get("name"),
            "display_name": a.get("display_name", a.get("name")),
            "enabled": a.get("enabled", True),
            "priority": a.get("priority", 99),
            "role": a.get("role", "general"),
        }
        for a in get_advisors()
    ]


def _public_circuits() -> Dict[str, Any]:
    """Sanitize circuit snapshot to omit internal file paths."""
    snap = snapshot_circuits()
    return {
        "enabled": snap.get("enabled", True),
        "advisors": snap.get("advisors", {}),
    }


def _safe_patch_path(p: str) -> Optional[Path]:
    if not p:
        return None
    try:
        resolved = Path(p).resolve()
        if not resolved.is_file():
            return None
        resolved.relative_to(PATCHES_DIR.resolve())
        return resolved
    except (ValueError, Exception):
        return None


def _is_safe_patch_path(p: str) -> bool:
    return _safe_patch_path(p) is not None


def _is_allowed_origin(origin: str) -> bool:
    if not origin or origin.lower() == "null":
        return False
    try:
        parts = urllib.parse.urlsplit(origin)
        if parts.scheme not in ("http", "https"):
            return False
        hostname = (parts.hostname or "").lower()
        return hostname in ("127.0.0.1", "localhost", "::1")
    except Exception:
        return False


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        print(f"[Server Warning] Failed reading {path.name}: {e}", file=sys.stderr)
    return rows


def _subsystem_status() -> Dict[str, bool]:
    probes = {
        "pieces_os": PORT_PIECES_OS,
        "hermes_relay": PORT_HERMES_RELAY,
        "pieces_proxy": PORT_PIECES_PROXY,
        "ollama": PORT_OLLAMA,
    }
    out: Dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        futures = {
            name: pool.submit(is_port_open, "127.0.0.1", port, 0.5)
            for name, port in probes.items()
        }
        for name, fut in futures.items():
            try:
                out[name] = bool(fut.result())
            except Exception:
                out[name] = False
    return out


def get_telemetry_summary(limit: int = 50) -> Dict[str, Any]:
    """
    Aggregate council_sessions.jsonl (competition adjudications) and
    advisor_calls.jsonl (every single-advisor call: latency + outcome).
    """
    sessions = _read_jsonl(COUNCIL_SESSIONS_LOG)

    total_sessions = len(sessions)
    modes: Dict[str, int] = {}
    advisors_count: Dict[str, int] = {}
    total_elapsed = 0.0

    for s in sessions:
        m = s.get("mode", "unknown")
        modes[m] = modes.get(m, 0) + 1
        for adv in s.get("advisors", []):
            advisors_count[adv] = advisors_count.get(adv, 0) + 1
        total_elapsed += _safe_float(s.get("elapsed_seconds", 0.0))

    avg_elapsed = round(total_elapsed / total_sessions, 2) if total_sessions > 0 else 0.0
    recent_sessions = list(reversed(sessions[-limit:]))

    # Per-advisor call statistics
    calls = _read_jsonl(ADVISOR_CALLS_LOG)
    per_advisor: Dict[str, Dict[str, Any]] = {}
    for c in calls:
        name = str(c.get("advisor", "unknown"))
        entry = per_advisor.setdefault(name, {"calls": 0, "ok": 0, "limit": 0, "error": 0, "timeout": 0, "empty": 0, "_elapsed": 0.0})
        entry["calls"] += 1
        status = str(c.get("status", "error"))
        if status in entry:
            entry[status] += 1
        entry["_elapsed"] += _safe_float(c.get("elapsed_seconds", 0.0))
    for name, entry in per_advisor.items():
        n = entry["calls"] or 1
        entry["avg_elapsed_seconds"] = round(entry.pop("_elapsed") / n, 2)
        entry["success_rate"] = round(entry["ok"] / n, 3)

    return {
        "total_sessions": total_sessions,
        "modes": modes,
        "advisors_used": advisors_count,
        "avg_elapsed_seconds": avg_elapsed,
        "sessions": recent_sessions,
        "advisor_calls": {
            "total": len(calls),
            "per_advisor": per_advisor,
            "recent": list(reversed(calls[-limit:])),
        },
    }


class TriadRequestHandler(BaseHTTPRequestHandler):
    """Multi-threaded request handler for Triad Ambient HTTP Bridge."""

    server_version = "TriadHTTP/1.0"

    def _drain_best_effort(self):
        """Drain already-buffered incoming request body with strict 50ms deadline to prevent Winsock RST."""
        try:
            raw_len = self.headers.get("Content-Length", "")
            if not raw_len:
                return
            length = min(int(raw_len), MAX_BODY_BYTES)
            if length <= 0:
                return
            orig_timeout = None
            try:
                if hasattr(self.connection, "gettimeout"):
                    orig_timeout = self.connection.gettimeout()
                    self.connection.settimeout(0.05)
                self.rfile.read(length)
            except (TimeoutError, OSError):
                pass
            finally:
                if orig_timeout is not None and hasattr(self.connection, "settimeout"):
                    try:
                        self.connection.settimeout(orig_timeout)
                    except Exception:
                        pass
        except Exception:
            pass

    def _send_cors_headers(self):
        origin = (self.headers.get("Origin") or "").strip()
        if _is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, x-webhook-token")
            self.send_header("Vary", "Origin")

    def _send_json(self, status_code: int, data: Any):
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if status_code >= 400:
            self.send_header("Connection", "close")
            self.close_connection = True
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)
        try:
            self.wfile.flush()
        except Exception:
            pass
        if status_code >= 400:
            self._drain_best_effort()

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    # --- Auth -----------------------------------------------------------------
    def _is_authorized(self) -> bool:
        """
        When TRIAD_SERVER_TOKEN is set, every POST (and the sensitive GET /telemetry,
        GET /doctor) must present it as ``Authorization: Bearer <token>`` or
        ``x-webhook-token: <token>``. With no token configured the server stays open,
        preserving the original loopback-only trust model.
        """
        if not SERVER_TOKEN:
            return True
        presented = ""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            presented = auth[7:].strip()
        if not presented:
            presented = (self.headers.get("x-webhook-token") or "").strip()
        return bool(presented) and hmac.compare_digest(presented.encode("utf-8"), SERVER_TOKEN.encode("utf-8"))

    def _require_auth(self, require_token_configured: bool = False) -> bool:
        if require_token_configured and not SERVER_TOKEN:
            self._send_json(401, {
                "error": "Unauthorized: TRIAD_SERVER_TOKEN must be configured on server to allow this sensitive endpoint",
                "hint": "Set TRIAD_SERVER_TOKEN in server environment"
            })
            return False
        if self._is_authorized():
            return True
        self._send_json(401, {"error": "Unauthorized", "hint": "Set Authorization: Bearer <TRIAD_SERVER_TOKEN>"})
        return False

    def _validate_host(self) -> bool:
        host = self.headers.get("Host", "").strip()
        if not host:
            return True
        if host.startswith("["):
            end_bracket = host.find("]")
            host_name = host[1:end_bracket].lower() if end_bracket != -1 else host.lower()
        else:
            host_name = host.rpartition(":")[0].lower() or host.lower()
        if host_name not in ("localhost", "127.0.0.1", "::1"):
            self._send_json(403, {"error": f"Forbidden Host: {host}"})
            return False
        return True

    # --- GET ------------------------------------------------------------------
    def do_GET(self):
        if not self._validate_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/health"):
            resp = {
                "status": "ok",
                "service": "autonomous-triad",
                "version": TRIAD_VERSION,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "auth_required": bool(SERVER_TOKEN),
                "advisors": _public_advisors(),
                "subsystems": _subsystem_status(),
                "circuits": _public_circuits(),
            }
            self._send_json(200, resp)
            return

        if path == "/telemetry":
            if not self._require_auth(require_token_configured=True):
                return
            limit_val = 50
            if "limit" in query_params:
                try:
                    limit_val = max(1, min(500, int(query_params["limit"][0])))
                except ValueError:
                    pass
            self._send_json(200, get_telemetry_summary(limit=limit_val))
            return

        if path == "/doctor":
            probe = query_params.get("probe", ["0"])[0] in ("1", "true", "yes")
            if not self._require_auth(require_token_configured=True):
                return
            try:
                try:
                    from triad.triad_engine import collect_doctor_report
                except ImportError:
                    from triad_engine import collect_doctor_report
                self._send_json(200, collect_doctor_report(probe_advisors=probe))
            except Exception as e:
                self._send_json(500, {"error": f"doctor failed: {e}"})
            return

        self._send_json(404, {"error": "Not Found", "path": path})

    # --- POST -----------------------------------------------------------------
    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        """Parse the JSON body defensively; sends the error response itself and returns None on failure."""
        if not self._validate_host():
            return None
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            self._send_json(415, {"error": "Unsupported Media Type: Content-Type must be application/json"})
            return None
        raw_len = self.headers.get("Content-Length", "")
        try:
            content_len = int(raw_len or 0)
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length header"})
            return None
        if content_len <= 0:
            self._send_json(400, {"error": "Empty or missing request body"})
            return None
        if content_len > MAX_BODY_BYTES:
            self._send_json(413, {"error": f"Request body exceeds {MAX_BODY_BYTES} bytes"})
            return None

        orig_timeout = None
        try:
            if hasattr(self.connection, "gettimeout"):
                orig_timeout = self.connection.gettimeout()
                self.connection.settimeout(10.0)
            body_raw = self.rfile.read(content_len).decode("utf-8", errors="replace")
        except (TimeoutError, OSError) as e:
            self._send_json(408, {"error": f"Request body read timed out: {e}"})
            return None
        finally:
            if orig_timeout is not None and hasattr(self.connection, "settimeout"):
                try:
                    self.connection.settimeout(orig_timeout)
                except Exception:
                    pass

        try:
            body = json.loads(body_raw)
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON body: {e}"})
            return None
        if not isinstance(body, dict):
            self._send_json(400, {"error": "JSON body must be an object"})
            return None
        return body

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path not in ("/auto", "/review", "/action/approve", "/action/reject"):
            self._send_json(404, {"error": "Not Found", "path": path})
            return
        if path.startswith("/action/"):
            if not self._require_auth(require_token_configured=True):
                return
        else:
            if not self._require_auth():
                return

        body = self._read_json_body()
        if body is None:
            return

        try:
            if path == "/auto":
                self._handle_auto(body)
            elif path == "/review":
                self._handle_review(body)
            elif path == "/action/approve":
                self._handle_action_approve(body)
            elif path == "/action/reject":
                self._handle_action_reject(body)
        except Exception as e:
            self._send_json(500, {"error": f"Internal error: {e}"})

    def _handle_action_approve(self, body: Dict[str, Any]):
        patch_file = body.get("patch_file", "")
        repo_arg = body.get("repo_path", "")
        reason = body.get("reason", "Approved via Mobile 1-Tap Bridge")

        repo_dir = _resolve_repo_path(repo_arg)
        if not repo_dir:
            self._send_json(400, {
                "error": "Target repository path is not a valid git repository",
                "repo_path": repo_arg or str(Path.cwd())
            })
            return

        allowed_repos_raw = os.environ.get("TRIAD_ALLOWED_REPOS", "").strip()
        if allowed_repos_raw:
            allowed_repos = [Path(p).resolve() for p in allowed_repos_raw.split(os.pathsep) if p.strip()]
        else:
            # Default-deny: only allow the server's own repository root when TRIAD_ALLOWED_REPOS is unset
            server_repo = _resolve_repo_path(str(Path(__file__).resolve().parent.parent))
            allowed_repos = [server_repo] if server_repo else []

        if not any(repo_dir == r or r in repo_dir.parents for r in allowed_repos):
            self._send_json(403, {
                "error": "repo not in TRIAD_ALLOWED_REPOS",
                "repo_path": str(repo_dir)
            })
            return

        applied = False
        if patch_file:
            safe_patch = _safe_patch_path(patch_file)
            if not safe_patch:
                self._send_json(400, {
                    "error": "Invalid patch_file: must be an existing file within allowed patch directory"
                })
                return

            patch_sha256 = str(body.get("patch_sha256", "")).strip()
            if not patch_sha256:
                self._send_json(400, {
                    "error": "patch_sha256 required"
                })
                return

            try:
                patch_bytes = safe_patch.read_bytes()
            except Exception as e:
                self._send_json(400, {"error": f"Failed reading patch file: {e}"})
                return

            actual_sha = hashlib.sha256(patch_bytes).hexdigest()
            if not hmac.compare_digest(actual_sha.lower(), patch_sha256.lower()):
                self._send_json(409, {
                    "status": "conflict",
                    "error": f"Patch SHA256 digest mismatch (expected {patch_sha256}, got {actual_sha})"
                })
                return

            repo_lock = _get_repo_lock(repo_dir)
            with repo_lock:
                try:
                    ret_check = subprocess.run(
                        ["git", "apply", "--check", "--whitespace=nowarn", "-"],
                        input=patch_bytes,
                        cwd=str(repo_dir),
                        env=clean_git_env(),
                        capture_output=True,
                        timeout=15
                    )
                    if ret_check.returncode != 0:
                        err_detail = ret_check.stderr.decode("utf-8", errors="replace").strip() or ret_check.stdout.decode("utf-8", errors="replace").strip()
                        self._send_json(409, {
                            "status": "conflict",
                            "error": "Patch does not apply cleanly to target repository",
                            "details": err_detail
                        })
                        return
                except Exception as e:
                    self._send_json(500, {"error": f"Failed checking patch: {e}"})
                    return

                try:
                    ret_apply = subprocess.run(
                        ["git", "apply", "--whitespace=nowarn", "-"],
                        input=patch_bytes,
                        cwd=str(repo_dir),
                        env=clean_git_env(),
                        capture_output=True,
                        timeout=15
                    )
                    if ret_apply.returncode != 0:
                        err_detail = ret_apply.stderr.decode("utf-8", errors="replace").strip() or ret_apply.stdout.decode("utf-8", errors="replace").strip()
                        self._send_json(409, {
                            "status": "conflict",
                            "error": "Failed applying patch to target repository",
                            "details": err_detail
                        })
                        return
                    applied = True
                except Exception as e:
                    self._send_json(500, {"error": f"Failed applying patch: {e}"})
                    return

        self._send_json(200, {
            "status": "approved",
            "action": "approve",
            "patch_applied": applied,
            "repo_path": str(repo_dir),
            "reason": reason,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        })

    def _handle_action_reject(self, body: Dict[str, Any]):
        reason = body.get("reason", "Rejected via Mobile 1-Tap Bridge")
        self._send_json(200, {
            "status": "rejected",
            "action": "reject",
            "reason": reason,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        })

    def _handle_auto(self, body: Dict[str, Any]):
        prompt = str(body.get("prompt", "")).strip()
        context = body.get("context", "")
        diff = body.get("diff", "")
        force_competition = bool(body.get("competition", False))
        use_worktree = bool(body.get("worktree", False))

        if not prompt and not diff:
            self._send_json(400, {"error": "Prompt or diff is required"})
            return

        classification = classify_intent(prompt, context=context, diff=diff)
        if force_competition:
            classification.suggested_engine = "competition"

        # os.chdir is process-global and this server is multi-threaded, so a worktree
        # cannot be entered safely here. The CLI (`triad auto --worktree`) does the
        # isolation in its own process. Pretending on HTTP ran the request in the
        # parent checkout.
        if use_worktree:
            self._send_json(501, {
                "error": "worktree isolation is not available on POST /auto. Use `triad auto --worktree` locally.",
                "intent": classification.intent,
            })
            return

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

        if intent in ("ARCHITECT", "GENERAL", "MICRO"):
            if engine == "competition":
                session = query_competition_council(prompt, context=context, mode="architect")
                return {"synthesis": session["synthesis"], "advisors": session["advisors"]}
            if (intent == "MICRO" or engine == "ollama") and is_port_open("127.0.0.1", PORT_OLLAMA, timeout=0.3):
                resp = query_configured_advisor("ollama", prompt, context=context, mode="general")
                return {"response": resp}
            resp = query_configured_advisor("auto", prompt, context=context, mode="architect")
            return {"response": resp}

        if intent == "DEBUG":
            if engine == "competition":
                session = query_competition_council(prompt, context=context, mode="debug")
                return {"synthesis": session["synthesis"], "advisors": session["advisors"]}
            resp = query_configured_advisor("auto", prompt, context=context, mode="debug")
            return {"response": resp}

        if intent == "DOCTOR":
            status = _subsystem_status()
            status["advisors"] = _public_advisors()
            return status

        if intent == "DEVICE":
            bridge_alive = is_port_open("127.0.0.1", PORT_HERMES_RELAY, timeout=0.5)
            return {
                "bridge_online": bridge_alive,
                "port": PORT_HERMES_RELAY,
                "status": "ready" if bridge_alive else "standby",
                "message": "Android relay connected" if bridge_alive else "Dial phone app com.hermesandroid.bridge",
            }

        if intent == "MEMORY":
            return {
                "pieces_os_online": is_port_open("127.0.0.1", PORT_PIECES_OS, timeout=0.5),
                "mem0_configured": MEM0_SCRIPT.exists(),
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

    print("================================================================================")
    print("           AUTONOMOUS MULTI-AGENT TRIAD: AMBIENT HTTP BRIDGE                    ")
    print("================================================================================")
    print(f"Listening on http://{host}:{port}")
    print(f"Auth: {'bearer token required (TRIAD_SERVER_TOKEN)' if SERVER_TOKEN else 'open (set TRIAD_SERVER_TOKEN to require a bearer token)'}")
    print("Endpoints:")
    print("  - GET  /health      System health, subsystem connectivity, and advisor status")
    print("  - GET  /doctor      Full structured doctor report (?probe=1 for a live Claude probe)")
    print("  - GET  /telemetry   Council adjudication history & per-advisor call stats")
    print("  - POST /auto        Sub-millisecond intent classification & autonomous execution")
    print("  - POST /review      Diff review and dual-advisor competition consensus")
    print("Press Ctrl+C to terminate.")
    print("================================================================================\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Triad Server] Shutting down...")
    finally:
        httpd.server_close()
        print("[Triad Server] Stopped.")


if __name__ == "__main__":
    start_server(port=PORT_TRIAD_SERVER)
