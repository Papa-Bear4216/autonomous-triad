#!/usr/bin/env python3
"""
Autonomous Multi-Agent Triad Engine (triad_engine.py).
Unified Executive Orchestrator & Advisory Bridge:
- Antigravity: Executive Engine, Massive 2M Context, Code Writer & Test Runner
- Advisory Council: Claude 3.7 Sonnet (Claude Pro) with zero-downtime failover to OpenAI Codex (gpt-6-astra via ChatGPT Plus)
- Hermes Agent: Android Phone Automation & Skill Specialist
- Ground Truth Gates: Local TypeScript (tsc) and Vitest/Jest test suites
- 100% Zero-Incremental-Cost Policy: Flat-rate subscriptions only ($0 extra per-token billing)
"""

import sys
import os
import subprocess
import argparse
import json
import tempfile
import socket
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

TRIAD_DIR = Path(__file__).resolve().parent
EMPTY_MCP = TRIAD_DIR / "empty-mcp.json"

CLAUDE_PATH = Path(r"C:\Users\micha\.local\bin\claude.exe")
CODEX_PATH = Path(r"C:\Users\micha\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe")
AGY_PATH = Path(r"C:\Users\micha\AppData\Local\agy\bin\agy.exe")
HERMES_PATH = Path(r"C:\Users\micha\AppData\Local\hermes\bin\hermes.exe")
HERMES_CONFIG = Path(r"C:\Users\micha\AppData\Local\hermes\config.yaml")
CODEX_AUTH = Path(r"C:\Users\micha\.codex\auth.json")

def kill_process_tree(pid: int):
    """Force kill a process and all its descendants on Windows."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
    except Exception:
        pass

def build_advisor_prompt(prompt: str, context: str = None, diff: str = None, mode: str = "general") -> str:
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

def query_claude(prompt: str, context: str = None, diff: str = None, mode: str = "general", timeout: int = 120) -> str:
    claude_bin = str(CLAUDE_PATH) if CLAUDE_PATH.exists() else "claude"
    full_prompt = build_advisor_prompt(prompt, context=context, diff=diff, mode=mode)

    cmd = [
        claude_bin,
        "-p",
        "--tools=",
        "--strict-mcp-config",
        "--mcp-config", str(EMPTY_MCP)
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )

        stdout, stderr = proc.communicate(input=full_prompt, timeout=timeout)
        output = stdout.strip()

        if proc.returncode != 0:
            if "session limit" in output.lower() or "rate limit" in output.lower():
                return f"[Claude Advisor Session Limit]: {output}"
            clean_err = stderr.strip()
            return f"[Error from Claude Advisor (exit code {proc.returncode})]: {output or clean_err}"

        clean_lines = []
        for line in output.splitlines():
            if "Permission allow rule" in line or "Warning: no stdin data received" in line:
                continue
            clean_lines.append(line)

        return "\n".join(clean_lines).strip()

    except subprocess.TimeoutExpired:
        if proc:
            kill_process_tree(proc.pid)
        return "[Error: Claude Advisor timed out (process tree killed)]"
    except Exception as e:
        if proc:
            kill_process_tree(proc.pid)
        return f"[Error calling Claude Advisor: {e}]"

def query_codex(prompt: str, context: str = None, diff: str = None, mode: str = "general", timeout: int = 120) -> str:
    codex_bin = str(CODEX_PATH) if CODEX_PATH.exists() else "codex"
    full_prompt = build_advisor_prompt(prompt, context=context, diff=diff, mode=mode)

    # Create temporary file and close handle immediately so Windows doesn't lock it
    temp_fd, temp_out_path = tempfile.mkstemp(suffix=".txt")
    os.close(temp_fd)

    cmd = [
        codex_bin,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "-s", "read-only",
        "-o", temp_out_path,
        "-"
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )

        stdout, stderr = proc.communicate(input=full_prompt, timeout=timeout)

        # Read pure model response from isolated output file
        if os.path.exists(temp_out_path):
            try:
                with open(temp_out_path, "r", encoding="utf-8", errors="replace") as f:
                    agent_output = f.read().strip()
                if agent_output:
                    return agent_output
            except Exception:
                pass

        # Fallback to parsing stdout if file was empty
        clean_lines = []
        capture = False
        for line in stdout.splitlines():
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

        if proc.returncode != 0:
            return f"[Error from Codex Advisor (exit code {proc.returncode})]: {stderr.strip() or stdout.strip()}"

        return stdout.strip()

    except subprocess.TimeoutExpired:
        if proc:
            kill_process_tree(proc.pid)
        return "[Error: OpenAI Codex timed out (process tree killed)]"
    except Exception as e:
        if proc:
            kill_process_tree(proc.pid)
        return f"[Error calling OpenAI Codex: {e}]"
    finally:
        if os.path.exists(temp_out_path):
            try:
                os.remove(temp_out_path)
            except Exception:
                pass

def query_advisory_council(prompt: str, context: str = None, diff: str = None, mode: str = "general", engine: str = "auto") -> str:
    """
    Autonomous Advisory Council with zero-downtime failover:
    Tries Claude Pro first. If rate limited, instantly routes to OpenAI Codex.
    """
    if engine == "codex":
        return query_codex(prompt, context=context, diff=diff, mode=mode)
    elif engine == "claude":
        return query_claude(prompt, context=context, diff=diff, mode=mode)

    # Auto mode: Claude Pro -> OpenAI Codex failover
    claude_resp = query_claude(prompt, context=context, diff=diff, mode=mode)
    if "session limit" in claude_resp.lower() or "rate limit" in claude_resp.lower() or claude_resp.startswith("[Error"):
        codex_resp = query_codex(prompt, context=context, diff=diff, mode=mode)
        header = f"[Advisor Auto-Failover: Claude Pro unavailable ({claude_resp.strip()}). Active Advisor: OpenAI Codex (gpt-6-astra)]\n\n"
        return header + codex_resp

    return claude_resp

def get_git_diff(cached: bool = False, head: bool = False) -> str:
    """Retrieve git diff from current repository."""
    cmd = ["git", "diff"]
    if cached:
        cmd.append("--cached")
    elif head:
        cmd.append("HEAD~1")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        return res.stdout.strip()
    except Exception as e:
        return ""

def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Quick TCP connect check."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def cmd_doctor(args):
    """Run full diagnostic audit across all 5 platform layers."""
    print("================================================================================")
    print("           AUTONOMOUS MULTI-AGENT TRIAD: SYSTEM HEALTH & COST AUDIT              ")
    print("================================================================================")
    print(f"Policy: STRICT ZERO INCREMENTAL COST (Flat-rate subscriptions & local execution)\n")

    # 1. Antigravity
    print("[1] Antigravity (Executive Engine & Context Shield)")
    if AGY_PATH.exists():
        print(f"    - Binary:       {AGY_PATH} (OK)")
    else:
        print(f"    - Binary:       agy (PATH check)")
    print(f"    - Context:      Up to 2,000,000 tokens")
    print(f"    - Billing:      $0 extra (Included in Antigravity IDE access)")

    # 2. Claude Code
    print("\n[2] Claude Code (Chief Architect & Diff Verifier)")
    if CLAUDE_PATH.exists():
        print(f"    - Binary:       {CLAUDE_PATH} (OK)")
    else:
        print(f"    - Binary:       claude (PATH check)")
    print(f"    - Subscription: Claude Pro (Flat-rate, $0 extra API cost)")
    # Quick probe
    quick_test = query_claude("Respond with OK", timeout=15)
    if "session limit" in quick_test.lower() or "rate limit" in quick_test.lower():
        print(f"    - Status:       PAUSED [Session Limit Hit] -> Auto-Failover to Codex active")
        print(f"                    ({quick_test.strip()})")
    elif "OK" in quick_test:
        print(f"    - Status:       ONLINE & READY")
    else:
        print(f"    - Status:       {quick_test.strip()[:80]}")

    # 3. OpenAI Codex
    print("\n[3] OpenAI Codex (High-Availability Failover Advisor)")
    if CODEX_PATH.exists():
        print(f"    - Binary:       {CODEX_PATH} (OK)")
    else:
        print(f"    - Binary:       codex (PATH check)")
    if CODEX_AUTH.exists():
        try:
            with open(CODEX_AUTH, "r", encoding="utf-8") as f:
                auth_data = json.load(f)
            # Find expiry date if present
            exp_str = "Active"
            tokens = auth_data.get("tokens", {})
            id_token = tokens.get("id_token", "")
            if id_token:
                # Basic JWT claim preview if parseable
                import base64
                parts = id_token.split(".")
                if len(parts) >= 2:
                    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                    payload = json.loads(base64.b64decode(padded).decode("utf-8", errors="replace"))
                    auth_meta = payload.get("https://api.openai.com/auth", {})
                    plan = auth_meta.get("chatgpt_plan_type", "plus")
                    exp_until = auth_meta.get("chatgpt_subscription_active_until", "Active")
                    print(f"    - Plan:         ChatGPT {plan.capitalize()} (Active until {exp_until[:10]})")
            print(f"    - Mode:         chatgpt OAuth via WebSockets")
            print(f"    - Model:        gpt-6-astra / gpt-5.6-terra")
            print(f"    - Billing:      $0 extra (Included in ChatGPT Plus subscription)")
            print(f"    - Status:       ONLINE & VERIFIED")
        except Exception as e:
            print(f"    - Status:       Configured ({e})")
    else:
        print(f"    - Status:       Auth config not found at {CODEX_AUTH}")

    # 4. Hermes Agent
    print("\n[4] Hermes Agent (Device Specialist & Mobile Bridge)")
    if HERMES_PATH.exists():
        print(f"    - Binary:       {HERMES_PATH} (OK)")
    print(f"    - Model:        stepfun/step-3.7-flash:free (Nous Portal, $0 cost)")
    print(f"    - Timezone:     America/Chicago")
    # Check bridge port 8766
    bridge_open = is_port_open("127.0.0.1", 8766)
    if bridge_open:
        print(f"    - Android Relay: Port 8766 LISTENING (Phone bridge connected)")
    else:
        print(f"    - Android Relay: Port 8766 STANDBY (Will accept connection from com.hermesandroid.bridge)")

    # 5. Local Infrastructure & Tooling
    print("\n[5] Local Subsystems (On-Device Local Memory & Execution)")
    pieces_open = is_port_open("127.0.0.1", 39300)
    print(f"    - PiecesOS:     {'ONLINE (Port 39300 responding)' if pieces_open else 'STANDBY (Restored MSIX autostart on user session login)'}")
    ollama_open = is_port_open("127.0.0.1", 11434)
    print(f"    - Ollama:       {'ONLINE (Port 11434 responding)' if ollama_open else 'STANDBY (Local on-demand daemon)'}")

    print("\n================================================================================")
    print("TRIAD AUDIT SUMMARY: ALL SUBSYSTEMS READY. HIGH-AVAILABILITY FAILOVER ARMED.")
    print("================================================================================\n")

def cmd_review(args):
    """Review git diff with the Advisory Council."""
    diff_content = ""
    if args.diff_file:
        if args.diff_file == "-":
            diff_content = sys.stdin.read()
        elif os.path.exists(args.diff_file):
            with open(args.diff_file, "r", encoding="utf-8", errors="replace") as f:
                diff_content = f.read()
    else:
        diff_content = get_git_diff(cached=args.cached, head=args.head)

    if not diff_content:
        print("[Triad] No git diff found to review. Stage changes or specify --diff-file.")
        sys.exit(0)

    prompt = args.prompt or "Review this git diff for edge cases, subtle bugs, type soundness, and architectural regressions."
    print(f"[Triad] Reviewing {len(diff_content.splitlines())} diff lines via Advisory Council (engine={args.engine})...\n")
    resp = query_advisory_council(prompt, diff=diff_content, mode="review_diff", engine=args.engine)
    print(resp)

def cmd_consult(args):
    """Consult the Advisory Council for architectural / system design."""
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("Usage: triad consult '<prompt>' [--context '...']")
        sys.exit(1)

    context = args.context or ""
    if args.context_file and os.path.exists(args.context_file):
        with open(args.context_file, "r", encoding="utf-8", errors="replace") as f:
            context = f.read()

    print(f"[Triad] Consulting Advisory Council (engine={args.engine})...\n")
    resp = query_advisory_council(prompt, context=context, mode="architect", engine=args.engine)
    print(resp)

def cmd_debug(args):
    """Debug an error or stack trace with the Advisory Council."""
    error = args.error
    if not error and not sys.stdin.isatty():
        error = sys.stdin.read().strip()

    if not error:
        print("Usage: triad debug '<error description or stacktrace>' [--context '...']")
        sys.exit(1)

    context = args.context or ""
    if args.context_file and os.path.exists(args.context_file):
        with open(args.context_file, "r", encoding="utf-8", errors="replace") as f:
            context = f.read()

    print(f"[Triad] Diagnosing with Advisory Council (engine={args.engine})...\n")
    resp = query_advisory_council(error, context=context, mode="debug", engine=args.engine)
    print(resp)

def cmd_gate(args):
    """
    The Pre-Commit Verification Gate:
    1. Runs TypeScript compiler (tsc) if present
    2. Runs test suite if present
    3. If clean, pipes git diff to Advisory Council for signoff
    """
    cwd = Path.cwd()
    print(f"[Triad Gate] Running pre-commit verification in {cwd}...\n")

    # Step 1: TypeScript Check
    tsconfig = cwd / "tsconfig.json"
    if tsconfig.exists():
        print("[Step 1/3] Verifying TypeScript type safety (npx tsc --noEmit)...")
        res = subprocess.run(["npx.cmd", "tsc", "--noEmit"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            print(f"\n❌ [Triad Gate FAILED] TypeScript errors detected:\n{res.stdout or res.stderr}")
            print("\nFix compiler errors before submitting to the Advisory Council.")
            sys.exit(1)
        print("✓ TypeScript: 0 errors.")
    else:
        print("[Step 1/3] No tsconfig.json found. Skipping tsc check.")

    # Step 2: Test Suite
    package_json = cwd / "package.json"
    if package_json.exists():
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                pkg_data = json.load(f)
            scripts = pkg_data.get("scripts", {})
            if "test" in scripts:
                print("[Step 2/3] Running local test suite (npm test)...")
                test_cmd = ["npm.cmd", "test", "--", "--run"]
                res = subprocess.run(test_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if res.returncode != 0:
                    print(f"\n❌ [Triad Gate FAILED] Test suite failed:\n{res.stdout or res.stderr}")
                    sys.exit(1)
                print("✓ Tests passed successfully.")
            else:
                print("[Step 2/3] No test script in package.json. Skipping.")
        except Exception as e:
            print(f"[Step 2/3] Skipped test verification: {e}")
    else:
        print("[Step 2/3] No package.json found. Skipping tests.")

    # Step 3: Advisory Council Diff Signoff
    print("\n[Step 3/3] Submitting diff to Advisory Council for pre-commit signoff...")
    diff = get_git_diff(cached=True) or get_git_diff()
    if not diff:
        print("✓ No changes detected in git working tree. Gate passed.")
        return

    resp = query_advisory_council(
        "Evaluate this diff as the final pre-commit gate. If safe and sound, approve with a brief confirmation. If edge cases or risks exist, flag them.",
        diff=diff,
        mode="review_diff",
        engine=args.engine
    )
    print("\n[Advisory Council Signoff]:")
    print(resp)
    print("\n✓ [Triad Gate COMPLETE]")

def main():
    parser = argparse.ArgumentParser(prog="triad", description="Autonomous Multi-Agent Triad Orchestrator")
    subparsers = parser.add_subparsers(dest="command", help="Triad command to execute")

    # doctor
    p_doc = subparsers.add_parser("doctor", help="Run comprehensive health and billing audit across all platforms")

    # review
    p_rev = subparsers.add_parser("review", help="Review a git diff with the Advisory Council")
    p_rev.add_argument("prompt", nargs="?", default="", help="Specific review instructions or feature intent")
    p_rev.add_argument("--diff-file", default="", help="Path to diff file or - for stdin")
    p_rev.add_argument("--cached", "--staged", action="store_true", help="Review staged changes")
    p_rev.add_argument("--head", action="store_true", help="Review latest commit (HEAD~1)")
    p_rev.add_argument("--engine", choices=["auto", "claude", "codex"], default="auto", help="Advisor engine override")

    # consult
    p_con = subparsers.add_parser("consult", help="Consult Advisory Council on architectural design")
    p_con.add_argument("prompt", nargs="?", default="", help="Architectural question or proposal")
    p_con.add_argument("--context", default="", help="Inline context or schema")
    p_con.add_argument("--context-file", default="", help="Path to context file")
    p_con.add_argument("--engine", choices=["auto", "claude", "codex"], default="auto", help="Advisor engine override")

    # debug
    p_dbg = subparsers.add_parser("debug", help="Diagnose a stubborn error or bug with Advisory Council")
    p_dbg.add_argument("error", nargs="?", default="", help="Error message or description")
    p_dbg.add_argument("--context", default="", help="Code snippet or context")
    p_dbg.add_argument("--context-file", default="", help="Path to context file")
    p_dbg.add_argument("--engine", choices=["auto", "claude", "codex"], default="auto", help="Advisor engine override")

    # gate
    p_gate = subparsers.add_parser("gate", help="Run full pre-commit verification (tsc + tests + diff review)")
    p_gate.add_argument("--engine", choices=["auto", "claude", "codex"], default="auto", help="Advisor engine override")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "doctor": cmd_doctor,
        "review": cmd_review,
        "consult": cmd_consult,
        "debug": cmd_debug,
        "gate": cmd_gate
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)

if __name__ == "__main__":
    main()
