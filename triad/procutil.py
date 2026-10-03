"""
Autonomous Multi-Agent Triad: Process & Network Utilities (procutil.py).

Cross-platform helpers shared by the engine, advisor manager, and HTTP server.
Previously each module carried its own copy of these; this is the single
implementation.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
from typing import Optional

try:  # psutil is optional; we degrade to OS primitives without it.
    import psutil  # type: ignore
except Exception:  # pragma: no cover - exercised only when psutil is absent
    psutil = None  # type: ignore


def clean_git_env(extra_env: Optional[dict] = None, *, base_env: Optional[dict] = None) -> dict:
    """Return an environment dictionary sanitized of local Git environment variables."""
    try:
        from triad.worktree import clean_git_env as _clean
    except ImportError:
        from worktree import clean_git_env as _clean
    return _clean(extra_env=extra_env, base_env=base_env)


def kill_process_tree(pid: int, timeout: float = 5.0) -> None:
    """
    Force-terminate ``pid`` and every descendant.

    Strategy (best-effort, never raises):
      1. psutil, if installed - walks the tree and kills children first.
      2. Windows: ``taskkill /F /T``.
      3. POSIX: SIGKILL the process group if the pid leads one, else the pid.
    """
    if pid is None or pid <= 0:
        return

    if psutil is not None:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except Exception:
                    pass
            try:
                parent.kill()
            except Exception:
                pass
            try:
                psutil.wait_procs(children + [parent], timeout=timeout)
            except Exception:
                pass
            return
        except getattr(psutil, "NoSuchProcess", Exception):
            return
        except Exception:
            pass

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
        except Exception:
            pass
        return

    # POSIX fallback
    try:
        pgid = os.getpgid(pid)
        if pgid == pid:
            os.killpg(pgid, signal.SIGKILL)
            return
    except Exception:
        pass
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Quick TCP connect probe with guaranteed socket cleanup."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def classify_advisor_response(text: Optional[str]) -> str:
    """
    Classify a raw advisor response string into one of:
      ``"ok"``      - a usable answer
      ``"limit"``   - the advisor reported a session / rate / usage limit
      ``"error"``   - the advisor failed for any other reason
      ``"empty"``   - nothing came back

    Only the *leading bracketed tag* is inspected (e.g. ``[Claude Session Limit]: ...``),
    so an otherwise-valid review that merely mentions the word "limit" in its body is
    never misclassified as a failure.
    """
    s = (text or "").strip()
    if not s:
        return "empty"
    if not s.startswith("["):
        return "ok"
    close = s.find("]")
    if close == -1:
        return "ok"
    tag = s[1:close].lower()
    # A successful failover prefixes the *good* answer with a header that quotes the
    # earlier failures - that header must read as success, not as the failure it quotes.
    if tag.startswith("advisor auto-failover"):
        return "error" if "exhausted" in tag else "ok"
    if any(k in tag for k in ("session limit", "rate limit", "usage limit")):
        return "limit"
    if "triad circuit" in tag:
        return "limit" if any(k in tag for k in ("cooldown", "limit", "open")) else "error"
    if "timed out" in tag:
        return "timeout"
    if (
        tag in ("error", "failure", "failed")
        or tag.startswith(("error:", "failure:", "failed:", "error from ", "error calling ", "error in ", "failure from ", "error -", "error \u2013"))
        or (tag.startswith("competition") and ("fail" in tag or "error" in tag))
        or tag.startswith(("triad error", "advisor error"))
        or bool(re.search(r"\b(?:error|failure|failed)\s*:", tag))
        or bool(re.search(r"\b(?:error|failure|failed)$", tag))
    ):
        return "error"
    return "ok"


def is_failed_advisor_response(text: Optional[str]) -> bool:
    """True when ``text`` should trigger failover to the next advisor."""
    return classify_advisor_response(text) in ("limit", "error", "empty", "timeout")


__all__ = [
    "kill_process_tree",
    "is_port_open",
    "classify_advisor_response",
    "is_failed_advisor_response",
]
