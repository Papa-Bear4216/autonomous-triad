#!/usr/bin/env python3
"""
Autonomous Multi-Agent Triad: Advisor Manager (advisor_manager.py).
Config-driven management and dynamic query routing for advisory models:
- Loads declarative configurations from advisors.json.
- Supports runtime inspection (get_advisors, get_active_advisor).
- Executes queries against configured advisors (Claude, Codex, Ollama, Mock, or custom).
- Allows dynamic registration of new advisors without modifying engine code.
"""

import sys
import os
import re
import subprocess
import json
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

# Ensure UTF-8 console output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

TRIAD_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = TRIAD_DIR / "advisors.json"
DEFAULT_EMPTY_MCP = TRIAD_DIR / "empty-mcp.json"


import psutil

def kill_process_tree(pid: int) -> None:
    """Force-terminate a process and all child descendants on Windows."""
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        parent.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    except Exception:
        pass

    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
    except Exception:
        pass


def build_advisor_prompt(prompt: str, context: Optional[str] = None, diff: Optional[str] = None, mode: str = "general") -> str:
    """Construct structured advisor prompt based on query mode."""
    system_preamble = (
        "You are the Lead Architect and Code Reviewer acting as the autonomous advisory council to Antigravity (the primary coding agent).\n"
        "Antigravity has already handled the broad workspace and heavy context ingestion.\n"
        "You are strictly in Advisory mode. Provide direct, high-density analysis, exact code snippets, or architectural flags.\n"
    )

    if mode == "review_diff":
        return (
            f"{system_preamble}\n"
            "TASK: Review this git diff for subtle bugs, race conditions, edge cases, type soundness, and architectural regressions.\n\n"
            f"DIFF:\n```\n{diff or context or ''}\n```\n\n"
            f"ADDITIONAL CONTEXT / GOAL:\n{prompt}\n"
        )
    elif mode == "architect":
        return (
            f"{system_preamble}\n"
            "TASK: Evaluate this architectural proposal / design. Spot missing edge cases, security risks, or scalability flaws, and suggest the optimal pattern.\n\n"
            f"PROPOSAL / PROBLEM:\n{prompt}\n\n"
            f"CONTEXT:\n{context or ''}\n"
        )
    elif mode == "debug":
        return (
            f"{system_preamble}\n"
            "TASK: Diagnose this persistent error. Identify the root cause and provide the cleanest surgical fix.\n\n"
            f"ERROR / PROBLEM:\n{prompt}\n\n"
            f"SNIPPET / CONTEXT:\n{context or ''}\n"
        )
    else:
        return f"{system_preamble}\nQUERY:\n{prompt}\n\nCONTEXT:\n{context or ''}\n"


def load_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load advisor configuration JSON from disk."""
    path = Path(config_path).resolve() if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        return {"advisors": []}

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def save_config(config_data: Dict[str, Any], config_path: Optional[Union[str, Path]] = None) -> None:
    """Save advisor configuration JSON to disk."""
    path = Path(config_path).resolve() if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)


def get_advisors(config_path: Optional[Union[str, Path]] = None, enabled_only: bool = False) -> List[Dict[str, Any]]:
    """
    Return all configured advisors ordered by priority (lower priority number = higher precedence).
    """
    data = load_config(config_path)
    advisors = data.get("advisors", [])
    if enabled_only:
        advisors = [adv for adv in advisors if adv.get("enabled", True)]
    return sorted(advisors, key=lambda x: x.get("priority", 999))


def get_active_advisor(name: Optional[str] = None, config_path: Optional[Union[str, Path]] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieve advisor configuration by name (case-insensitive).
    If name is None or 'auto', returns the highest priority active advisor available.
    """
    advisors = get_advisors(config_path=config_path, enabled_only=True)
    if not advisors:
        return None

    if name and name.lower() not in ("auto", "none"):
        target = "claude" if name.lower() == "bare_single" else name.lower()
        for adv in advisors:
            if adv.get("name", "").lower() == target:
                return adv
        return None

    # 'auto' or None: return highest-priority enabled advisor
    return advisors[0]


def resolve_binary(binary_path: str, fallback_binary: Optional[str] = None) -> str:
    """Resolve absolute executable path or check PATH."""
    if binary_path in ("python", "python3"):
        return sys.executable

    p = Path(binary_path)
    if p.exists():
        return str(p)

    which_bin = shutil.which(binary_path)
    if which_bin:
        return which_bin

    if fallback_binary:
        if fallback_binary in ("python", "python3"):
            return sys.executable
        fb = Path(fallback_binary)
        if fb.exists():
            return str(fb)
        which_fb = shutil.which(fallback_binary)
        if which_fb:
            return which_fb

    return binary_path


def add_advisor(advisor_config: Dict[str, Any], config_path: Optional[Union[str, Path]] = None) -> None:
    """
    Dynamically register or update an advisor in the configuration without touching code.
    """
    data = load_config(config_path)
    advisors = data.setdefault("advisors", [])

    name = advisor_config.get("name", "").lower()
    updated = False
    for i, adv in enumerate(advisors):
        if adv.get("name", "").lower() == name:
            advisors[i] = advisor_config
            updated = True
            break

    if not updated:
        advisors.append(advisor_config)

    save_config(data, config_path)


def remove_advisor(advisor_name: str, config_path: Optional[Union[str, Path]] = None) -> bool:
    """Remove an advisor by name from the configuration."""
    data = load_config(config_path)
    advisors = data.get("advisors", [])
    target = advisor_name.lower()
    filtered = [adv for adv in advisors if adv.get("name", "").lower() != target]

    if len(filtered) != len(advisors):
        data["advisors"] = filtered
        save_config(data, config_path)
        return True
    return False


def _execute_single_advisor(
    advisor: Dict[str, Any],
    prompt: str,
    context: Optional[str] = None,
    diff: Optional[str] = None,
    mode: str = "general",
    timeout: int = 120
) -> str:
    """Execute a single advisor using its declared configuration."""
    raw_bin = advisor.get("binary_path", "")
    fallback_bin = advisor.get("fallback_binary")
    bin_path = resolve_binary(raw_bin, fallback_bin)

    full_prompt = build_advisor_prompt(prompt, context=context, diff=diff, mode=mode)
    flags = list(advisor.get("execution_flags", []))
    input_mode = advisor.get("input_mode", "stdin")
    output_mode = advisor.get("output_mode", "stdout")
    advisor_name = advisor.get("name", "unknown")
    display_name = advisor.get("display_name", advisor_name)

    temp_out_path = None
    if output_mode == "file":
        temp_fd, temp_out_path = tempfile.mkstemp(suffix=".txt")
        os.close(temp_fd)

    # Parameter interpolation for flags
    resolved_flags = []
    empty_mcp_str = str(DEFAULT_EMPTY_MCP)
    for flag in flags:
        flag = flag.replace("{empty_mcp}", empty_mcp_str)
        if temp_out_path:
            flag = flag.replace("{output_file}", temp_out_path)
        if input_mode == "arg":
            flag = flag.replace("{prompt}", full_prompt)
        resolved_flags.append(flag)

    cmd = [bin_path] + resolved_flags

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    for k, v in advisor.get("env", {}).items():
        env[k] = str(v)

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input_mode == "stdin" else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )

        stdin_data = full_prompt if input_mode == "stdin" else None
        stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)

        # Output collection
        output = ""
        if output_mode == "file" and temp_out_path and os.path.exists(temp_out_path):
            try:
                with open(temp_out_path, "r", encoding="utf-8", errors="replace") as f:
                    output = f.read().strip()
            except Exception:
                output = ""

        if not output:
            output = stdout.strip()

        # Handle process exit codes
        if proc.returncode != 0:
            err_msg = stderr.strip() or output
            out_lower = output.lower()
            if "session limit" in out_lower or "rate limit" in out_lower or "usage limit" in out_lower:
                return f"[{display_name} Session Limit]: {output}"
            return f"[Error from {display_name} (exit code {proc.returncode})]: {err_msg}"

        # Advisor-specific cleaning
        if advisor_name.lower() == "claude":
            clean_lines = []
            for line in output.splitlines():
                if "Permission allow rule" in line or "Warning: no stdin data received" in line:
                    continue
                clean_lines.append(line)
            return "\n".join(clean_lines).strip()

        elif advisor_name.lower() == "codex" and not output_mode == "file":
            clean_lines = []
            capture = False
            for line in output.splitlines():
                if line.strip() == "codex":
                    capture = True
                    continue
                if "tokens used" in line:
                    capture = False
                    continue
                if capture:
                    clean_lines.append(line)
            parsed = "\n".join(clean_lines).strip()
            if parsed:
                return parsed

        return output

    except subprocess.TimeoutExpired:
        if proc:
            kill_process_tree(proc.pid)
        return f"[Error: {display_name} timed out after {timeout}s (process tree killed)]"
    except Exception as e:
        if proc:
            kill_process_tree(proc.pid)
        return f"[Error calling {display_name}: {e}]"
    finally:
        if proc:
            try:
                kill_process_tree(proc.pid)
            except Exception:
                pass
        if temp_out_path and os.path.exists(temp_out_path):
            try:
                os.remove(temp_out_path)
            except Exception:
                pass


def query_configured_advisor(
    advisor_name: str,
    prompt: str,
    context: Optional[str] = None,
    diff: Optional[str] = None,
    mode: str = "general",
    timeout: int = 120,
    config_path: Optional[Union[str, Path]] = None
) -> str:
    """
    Query an advisor defined in advisors.json by name.
    If advisor_name is 'auto', attempts advisors in priority order with zero-downtime failover.
    """
    if advisor_name.lower() == "auto":
        advisors = get_advisors(config_path=config_path, enabled_only=True)
        if not advisors:
            return "[Error: No enabled advisors found in configuration]"

        fail_notes = []
        for adv in advisors:
            adv_name = adv.get("name")
            res = _execute_single_advisor(adv, prompt, context=context, diff=diff, mode=mode, timeout=timeout)
            is_limit = bool(re.match(r"^\[[^\]]*(?:session limit|rate limit|usage limit)[^\]]*\]", res.strip(), re.IGNORECASE))
            is_err = res.startswith("[Error") or is_limit
            if not is_err:
                if fail_notes:
                    header = f"[Advisor Auto-Failover: Preceding advisors failed ({'; '.join(fail_notes)}). Active Advisor: {adv.get('display_name')}]\n\n"
                    return header + res
                return res
            fail_notes.append(f"{adv.get('name')}: {res.strip()[:60]}")

        return f"[Advisor Auto-Failover Exhausted]: All configured advisors failed: {'; '.join(fail_notes)}"

    advisor = get_active_advisor(advisor_name, config_path=config_path)
    if not advisor:
        return f"[Error: Advisor '{advisor_name}' not found in configuration]"

    return _execute_single_advisor(advisor, prompt, context=context, diff=diff, mode=mode, timeout=timeout)


if __name__ == "__main__":
    advisors = get_advisors()
    print(f"Loaded {len(advisors)} advisors from configuration:")
    for a in advisors:
        print(f"  - [{a.get('priority')}] {a.get('name')}: {a.get('display_name')} (binary: {a.get('binary_path')})")
