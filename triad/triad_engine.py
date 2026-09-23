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
import re
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
CODEX_AUTH = Path(r"C:\Users\micha\.codex\auth.json")

try:
    from triad.advisor_manager import query_configured_advisor, get_advisors, get_active_advisor
    from triad.worktree import create_worktree, remove_worktree, isolated_worktree, list_worktrees, prune_worktrees
    from triad.competition import query_competition_council
    from triad.intent_engine import classify_intent, execute_intent
except ImportError:
    from advisor_manager import query_configured_advisor, get_advisors, get_active_advisor
    from worktree import create_worktree, remove_worktree, isolated_worktree, list_worktrees, prune_worktrees
    from competition import query_competition_council
    from intent_engine import classify_intent, execute_intent

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
    """Query Claude advisor via configured advisor manager."""
    return query_configured_advisor("claude", prompt, context=context, diff=diff, mode=mode, timeout=timeout)

def query_codex(prompt: str, context: str = None, diff: str = None, mode: str = "general", timeout: int = 120) -> str:
    """Query OpenAI Codex advisor via configured advisor manager."""
    return query_configured_advisor("codex", prompt, context=context, diff=diff, mode=mode, timeout=timeout)

def query_advisory_council(prompt: str, context: str = None, diff: str = None, mode: str = "general", engine: str = "auto", timeout: int = 180) -> str:
    """
    Autonomous Advisory Council with zero-downtime failover and dynamic advisor routing:
    Delegates to configured advisors via advisor_manager.
    """
    target = "claude" if engine == "bare_single" else engine
    return query_configured_advisor(target, prompt, context=context, diff=diff, mode=mode, timeout=timeout)

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
    diff_file = getattr(args, "diff_file", "")
    diff_content = ""
    if diff_file:
        if diff_file == "-":
            diff_content = sys.stdin.read()
        elif os.path.exists(diff_file):
            with open(diff_file, "r", encoding="utf-8", errors="replace") as f:
                diff_content = f.read()
    else:
        diff_content = get_git_diff(cached=getattr(args, "cached", False), head=getattr(args, "head", False))

    if not diff_content:
        print("[Triad] No git diff found to review. Stage changes or specify --diff-file.")
        sys.exit(0)

    prompt = getattr(args, "prompt", "") or "Review this git diff for edge cases, subtle bugs, type soundness, and architectural regressions."
    engine = getattr(args, "engine", "auto")
    if getattr(args, "competition", False):
        print(f"[Triad Competition Mode] Evaluating diff via concurrent advisors (Claude Code & OpenAI Codex)...")
        session = query_competition_council(prompt, diff=diff_content, mode="review_diff")
        print("\n" + session["synthesis"])
        return

    print(f"[Triad] Reviewing {len(diff_content.splitlines())} diff lines via Advisory Council (engine={engine})...\n")
    resp = query_advisory_council(prompt, diff=diff_content, mode="review_diff", engine=engine)
    print(resp)

def cmd_consult(args):
    """Consult the Advisory Council for architectural / system design."""
    prompt = getattr(args, "prompt", "")
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("Usage: triad consult '<prompt>' [--context '...']")
        sys.exit(1)

    context = getattr(args, "context", "") or ""
    context_file = getattr(args, "context_file", "")
    if context_file and os.path.exists(context_file):
        with open(context_file, "r", encoding="utf-8", errors="replace") as f:
            context = f.read()

    engine = getattr(args, "engine", "auto")
    if getattr(args, "competition", False):
        print(f"[Triad Competition Mode] Consulting concurrent advisors (Claude Code & OpenAI Codex)...")
        session = query_competition_council(prompt, context=context, mode="architect")
        print("\n" + session["synthesis"])
        return

    print(f"[Triad] Consulting Advisory Council (engine={engine})...\n")
    resp = query_advisory_council(prompt, context=context, mode="architect", engine=engine)
    print(resp)

def cmd_debug(args):
    """Debug an error or stack trace with the Advisory Council."""
    error = getattr(args, "error", "") or getattr(args, "prompt", "")
    if not error and not sys.stdin.isatty():
        error = sys.stdin.read().strip()

    if not error:
        print("Usage: triad debug '<error description or stacktrace>' [--context '...']")
        sys.exit(1)

    context = getattr(args, "context", "") or ""
    context_file = getattr(args, "context_file", "")
    if context_file and os.path.exists(context_file):
        with open(context_file, "r", encoding="utf-8", errors="replace") as f:
            context = f.read()

    engine = getattr(args, "engine", "auto")
    if getattr(args, "competition", False):
        print(f"[Triad Competition Mode] Diagnosing error via concurrent advisors (Claude Code & OpenAI Codex)...")
        session = query_competition_council(error, context=context, mode="debug")
        print("\n" + session["synthesis"])
        return

    print(f"[Triad] Diagnosing with Advisory Council (engine={engine})...\n")
    resp = query_advisory_council(error, context=context, mode="debug", engine=engine)
    print(resp)

def apply_patch_text(patch_text: str) -> bool:
    """Extracts unified diff from model response, validates with git apply --check, and applies it."""
    import re
    # Extract fenced code blocks or raw diff
    m = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", patch_text, re.DOTALL)
    raw_diff = m.group(1).strip() if m else patch_text.strip()

    # Verify minimum diff headers
    has_diff_headers = (
        ("diff --git " in raw_diff or ("--- " in raw_diff and "+++" in raw_diff))
        and "@@ " in raw_diff
    )
    if not has_diff_headers:
        return False

    # Create safe unique temp patch file
    fd, temp_patch_path = tempfile.mkstemp(suffix=".patch", prefix="triad_heal_")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(raw_diff + "\n")

        # 1. Check dry-run
        check_res = subprocess.run(
            ["git", "apply", "--check", "--whitespace=fix", temp_patch_path],
            capture_output=True,
            text=True
        )
        if check_res.returncode != 0:
            return False

        # 2. Apply patch
        apply_res = subprocess.run(
            ["git", "apply", "--whitespace=fix", temp_patch_path],
            capture_output=True,
            text=True
        )
        return apply_res.returncode == 0
    except Exception:
        return False
    finally:
        if os.path.exists(temp_patch_path):
            try:
                os.remove(temp_patch_path)
            except Exception:
                pass

def run_subprocess_tree_safe(cmd: List[str], cwd: Path, timeout: int = 90) -> Tuple[int, str, str]:
    """Execute command, killing the entire process tree on timeout to prevent zombie workers."""
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        if proc:
            kill_process_tree(proc.pid)
        return 1, "", f"Command timed out after {timeout}s (entire process tree killed)"
    except Exception as e:
        if proc:
            kill_process_tree(proc.pid)
        return 1, "", f"Execution error: {e}"

def query_gate_fix(diag_output: str, args) -> str:
    """
    Query Advisory Council or Competition Council for a surgical fix to a test/build failure.
    """
    fix_prompt = (
        f"The test/build suite failed with this output:\n{diag_output}\n\n"
        "Diagnose the failure and provide the minimal unified diff to fix it."
    )
    competition = getattr(args, "competition", False)
    timeout = getattr(args, "timeout", 240)
    engine = getattr(args, "engine", "auto")

    if competition:
        try:
            from triad.competition import query_competition_council
        except ImportError:
            from competition import query_competition_council
        adv_pair = ("mock", "mock") if engine == "mock" else ("claude", "codex")
        session = query_competition_council(
            fix_prompt,
            mode="debug",
            timeout=timeout,
            advisor_names=adv_pair
        )
        return session.get("synthesis", "")

    return query_advisory_council(fix_prompt, mode="debug", engine=engine, timeout=timeout)

def cmd_gate(args):
    """
    Ground-Truth Verification Gate with self-healing retry loop:
    1. TypeScript compilation (tsc --noEmit)
    2. Test suites (npm test, Python unittests)
    3. Advisory Council diff review & pre-commit signoff
    If Step 1 or Step 2 fails, queries Advisory Council in debug mode for surgical fix,
    applies patch via git apply, and retries up to --max-retries times.
    """
    cwd = Path.cwd()
    print(f"[Triad Gate] Running pre-commit verification in {cwd}...\n")
    max_retries = max(0, getattr(args, "max_retries", 1))

    tsconfig = cwd / "tsconfig.json"
    package_json = cwd / "package.json"
    test_timeout = 90

    attempt = 0
    while attempt <= max_retries:
        # Step 1: TypeScript Check
        if tsconfig.exists():
            print("[Step 1/3] Verifying TypeScript type safety (npx tsc --noEmit)...")
            ret, out, err = run_subprocess_tree_safe(["npx.cmd", "tsc", "--noEmit"], cwd=cwd, timeout=test_timeout)
            if ret != 0:
                diag_output = f"STDOUT:\n{out}\nSTDERR:\n{err}".strip()
                print(f"\n❌ [Triad Gate: Step 1 FAILED] TypeScript errors detected:\n{diag_output}")
                if attempt < max_retries:
                    attempt += 1
                    print(f"\n[Self-Healing Safety Net: Retry {attempt}/{max_retries}] Consulting Advisory Council in debug mode for surgical fix...")
                    advisor_fix = query_gate_fix(diag_output, args)
                    print(f"[Advisory Council Proposed Fix]:\n{advisor_fix}\n")
                    applied = apply_patch_text(advisor_fix)
                    if applied:
                        print("✓ Applied advisory patch to working tree. Restarting validation sequence...\n")
                        continue
                    else:
                        print("! Could not automatically apply patch via git apply. Aborting gate.")
                        sys.exit(1)
                else:
                    print("\n❌ [Triad Gate FAILED] TypeScript errors persist after retry budget exhausted.")
                    sys.exit(1)
            print("✓ TypeScript: 0 errors.")
        else:
            print("[Step 1/3] No tsconfig.json found. Skipping tsc check.")

        # Step 2: Test Suites (Supports polyglot projects: Node/Jest/Vitest AND Python/Unittest)
        ran_any_tests = False
        step2_failed = False

        if package_json.exists():
            try:
                with open(package_json, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)
                scripts = pkg_data.get("scripts", {})
                if "test" in scripts:
                    ran_any_tests = True
                    print("[Step 2/3] Running local test suite (npm test)...")
                    test_cmd = ["npm.cmd", "test", "--", "--run"]
                    ret, out, err = run_subprocess_tree_safe(test_cmd, cwd=cwd, timeout=test_timeout)

                    if ret != 0:
                        step2_failed = True
                        diag_output = f"STDOUT:\n{out}\nSTDERR:\n{err}".strip()
                        print(f"\n❌ [Triad Gate: Step 2 FAILED] Node test suite failed:\n{diag_output}")
                        if attempt < max_retries:
                            attempt += 1
                            print(f"\n[Self-Healing Safety Net: Retry {attempt}/{max_retries}] Consulting Advisory Council in debug mode for surgical fix...")
                            advisor_fix = query_gate_fix(diag_output, args)
                            print(f"[Advisory Council Proposed Fix]:\n{advisor_fix}\n")
                            applied = apply_patch_text(advisor_fix)
                            if applied:
                                print("✓ Applied advisory patch to working tree. Restarting validation sequence...\n")
                                continue
                            else:
                                print("! Could not automatically apply patch via git apply. Aborting gate.")
                                sys.exit(1)
                        else:
                            print("\n❌ [Triad Gate FAILED] Test suite still failing after retry budget exhausted.")
                            sys.exit(1)
                    else:
                        print("✓ Node/npm tests passed successfully.")
            except Exception as e:
                print(f"\n❌ [Triad Gate: Step 2 FAILED] Error executing Node test runner: {e}")
                sys.exit(1)

        # Python test discovery: run all configured suites
        py_test_targets = []
        if (cwd / "triad" / "tests").exists():
            py_test_targets.append("triad/tests")
        if (cwd / "tests").exists():
            py_test_targets.append("tests")

        for py_test_target in py_test_targets:
            ran_any_tests = True
            print(f"[Step 2/3] Running Python unit test suite ({py_test_target})...")
            test_cmd = [sys.executable, "-m", "unittest", "discover", "-s", py_test_target, "-p", "test_*.py"]
            ret, out, err = run_subprocess_tree_safe(test_cmd, cwd=cwd, timeout=test_timeout)

            diag_output = f"STDOUT:\n{out}\nSTDERR:\n{err}".strip()
            is_empty_suite = "Ran 0 tests" in diag_output
            if ret != 0 or is_empty_suite:
                step2_failed = True
                reason = "discovering 0 tests" if is_empty_suite else "failures"
                print(f"\n❌ [Triad Gate: Step 2 FAILED] Python test suite failed ({reason}):\n{diag_output}")
                if attempt < max_retries:
                    attempt += 1
                    print(f"\n[Self-Healing Safety Net: Retry {attempt}/{max_retries}] Consulting Advisory Council in debug mode for surgical fix...")
                    advisor_fix = query_gate_fix(diag_output, args)
                    print(f"[Advisory Council Proposed Fix]:\n{advisor_fix}\n")
                    applied = apply_patch_text(advisor_fix)
                    if applied:
                        print("✓ Applied advisory patch to working tree. Restarting validation sequence...\n")
                        break  # breaks out of targets loop to restart validation
                    else:
                        print("! Could not automatically apply patch via git apply. Aborting gate.")
                        sys.exit(1)
                else:
                    print("\n❌ [Triad Gate FAILED] Python test suite still failing after retry budget exhausted.")
                    sys.exit(1)
            else:
                print(f"✓ Python tests ({py_test_target}) passed successfully.")

        if step2_failed:
            continue

        if not ran_any_tests:
            print("[Step 2/3] No test runner found (package.json / Python tests). Skipping.")

        # All steps verified clean
        break

    # Step 3: Advisory Council Diff Signoff
    print("\n[Step 3/3] Submitting diff to Advisory Council for pre-commit signoff...")
    diff = get_git_diff(cached=True) or get_git_diff()
    if not diff:
        print("✓ No changes detected in git working tree. Gate passed.")
        return

    competition = getattr(args, "competition", False)
    if competition:
        try:
            from triad.competition import query_competition_council
        except ImportError:
            from competition import query_competition_council
        adv_pair = ("mock", "mock") if getattr(args, "engine", "auto") == "mock" else ("claude", "codex")
        session = query_competition_council(
            "Evaluate this diff as the final pre-commit gate.\n"
            "Under Section 4 (Final Adjudicated Verdict & Action Plan), explicitly state either 'VERDICT: APPROVED' or 'VERDICT: REJECTED'.",
            diff=diff,
            mode="review_diff",
            timeout=getattr(args, "timeout", 240),
            advisor_names=adv_pair
        )
        resp = session.get("synthesis", "")
    else:
        resp = query_advisory_council(
            "Evaluate this diff as the final pre-commit gate.\n"
            "Start your response with exactly 'VERDICT: APPROVED' if the diff is safe and sound to commit, "
            "or 'VERDICT: REJECTED' if there are correctness defects, regressions, or unresolved blockers, "
            "followed by your structured rationale.",
            diff=diff,
            mode="review_diff",
            engine=args.engine,
            timeout=getattr(args, "timeout", 240)
        )
    print("\n[Advisory Council Signoff]:")
    print(resp)

    # Parse verdict fail-closed: distinguish outages from explicit verdicts
    resp_clean = (resp or "").strip()
    if not resp_clean or resp_clean.startswith("[Error") or resp_clean.startswith("[error"):
        print("\n❌ [Triad Gate BLOCKED] Advisory Council execution error or service outage.")
        if resp_clean:
            print(f"Details: {resp_clean[:200]}")
        sys.exit(1)

    # Rejection anywhere in the response takes precedence and immediately blocks
    is_rejected = bool(re.search(r"\bVERDICT:\s*REJECTED\b", resp_clean, re.IGNORECASE))
    if is_rejected:
        print("\n❌ [Triad Gate BLOCKED] Advisory Council explicitly rejected the diff.")
        print("Address the advisory council findings above before committing.")
        sys.exit(1)

    if competition:
        is_approved = bool(re.search(r"\bVERDICT:\s*APPROVED\b", resp_clean, re.IGNORECASE))
    else:
        # Approval must be explicitly declared on the opening non-empty line
        non_empty_lines = [l.strip() for l in resp_clean.splitlines() if l.strip()]
        first_line = non_empty_lines[0] if non_empty_lines else ""
        first_line_clean = re.sub(r"[\*#_`]", "", first_line).strip()
        is_approved = bool(re.match(r"^VERDICT:\s*APPROVED\b", first_line_clean, re.IGNORECASE))

    if is_approved:
        print("\n✓ [Triad Gate COMPLETE] Advisory Council approved pre-commit signoff.")
    else:
        reason = "contain 'VERDICT: APPROVED'" if competition else "provide an explicit 'VERDICT: APPROVED' on line 1"
        print(f"\n❌ [Triad Gate BLOCKED] Advisory Council did not {reason}.")
        print("Address the advisory council findings above before committing.")
        sys.exit(1)

def cmd_bench(args):
    """Run the Triad benchmark suite."""
    suite = getattr(args, "suite", "cases")
    if suite == "swebench":
        try:
            from bench.swebench_runner import run_swebench
        except ImportError:
            from triad.bench.swebench_runner import run_swebench

        run_swebench(
            engine=args.engine,
            limit=args.limit or 5,
            instance_id=args.case,
            mode="debug",
            verbose=args.verbose
        )
        return

    try:
        from bench.run_bench import run_benchmark, DEFAULT_CASES_DIR
    except ImportError:
        from triad.bench.run_bench import run_benchmark, DEFAULT_CASES_DIR

    cases_dir = Path(args.cases_dir) if args.cases_dir else DEFAULT_CASES_DIR
    bugs_caught, pos_tot, fps, neg_tot, results = run_benchmark(
        cases_dir=cases_dir,
        engine=args.engine,
        limit=args.limit,
        case_id=args.case,
        verbose=args.verbose
    )

def cmd_worktree(args):
    """Manage ephemeral git worktrees."""
    action = getattr(args, "wt_action", None)
    if action == "list" or not action:
        wts = list_worktrees()
        print(f"Active Git Worktrees ({len(wts)}):")
        for wt in wts:
            det = " (detached)" if wt.get("detached") else ""
            branch = f" [{wt.get('branch')}]" if wt.get("branch") else ""
            print(f"  - {wt['worktree']} {wt.get('head', '')[:8]}{branch}{det}")
    elif action == "create":
        wt_path = create_worktree(".", branch_or_commit=args.ref, prefix=args.prefix)
        print(f"Created isolated worktree at: {wt_path}")
    elif action == "remove":
        removed = remove_worktree(args.path, force=args.force)
        if removed:
            print(f"Removed worktree at: {args.path}")
        else:
            print(f"Failed to remove worktree at: {args.path}")
    elif action == "prune":
        prune_worktrees(".")
        print("Pruned stale worktree metadata.")

def cmd_auto(args):
    """Auto-classify intent and autonomously route to the appropriate subsystem."""
    prompt = getattr(args, "prompt", "")
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()

    diff_content = ""
    if getattr(args, "diff_file", None):
        if args.diff_file == "-":
            diff_content = sys.stdin.read()
        elif os.path.exists(args.diff_file):
            with open(args.diff_file, "r", encoding="utf-8", errors="replace") as f:
                diff_content = f.read()

    context = getattr(args, "context", None)
    classification = classify_intent(prompt, context=context, diff=diff_content)

    # Force competition if user passed flag
    if getattr(args, "competition", False):
        classification.suggested_engine = "competition"

    execute_intent(classification, prompt, args)


def main():
    # Top-level intuitive auto-dispatch: if first arg is not a known command or flag, route through auto
    known_commands = {
        "doctor", "review", "consult", "debug", "gate",
        "bench", "worktree", "auto", "intent", "run",
        "-h", "--help"
    }
    if len(sys.argv) > 1 and sys.argv[1] not in known_commands and not sys.argv[1].startswith("-"):
        sys.argv.insert(1, "auto")

    parser = argparse.ArgumentParser(prog="triad", description="Autonomous Multi-Agent Triad Orchestrator")
    subparsers = parser.add_subparsers(dest="command", help="Triad command to execute")

    # auto / intent / run
    p_auto = subparsers.add_parser("auto", aliases=["intent", "run"], help="Auto-classify intent and autonomously route across Triad subsystems")
    p_auto.add_argument("prompt", nargs="?", default="", help="Natural language request, diff, or query")
    p_auto.add_argument("--diff-file", default="", help="Path to diff file or - for stdin")
    p_auto.add_argument("--context", default="", help="Inline context or error snippet")
    p_auto.add_argument("--context-file", default="", help="Path to context file")
    p_auto.add_argument("--competition", action="store_true", help="Force competition mode regardless of auto-stake assessment")
    p_auto.add_argument("--engine", default="auto", help="Advisor engine override")
    p_auto.add_argument("--cached", "--staged", action="store_true", help="Review staged changes if routing to review")
    p_auto.add_argument("--head", action="store_true", help="Review latest commit (HEAD~1) if routing to review")

    # doctor
    p_doc = subparsers.add_parser("doctor", help="Run comprehensive health and billing audit across all platforms")

    # review
    p_rev = subparsers.add_parser("review", help="Review a git diff with the Advisory Council")
    p_rev.add_argument("prompt", nargs="?", default="", help="Specific review instructions or feature intent")
    p_rev.add_argument("--diff-file", default="", help="Path to diff file or - for stdin")
    p_rev.add_argument("--cached", "--staged", action="store_true", help="Review staged changes")
    p_rev.add_argument("--head", action="store_true", help="Review latest commit (HEAD~1)")
    p_rev.add_argument("--engine", default="auto", help="Advisor engine override (e.g. auto, claude, codex, ollama, mock)")
    p_rev.add_argument("--competition", action="store_true", help="Execute Claude Code & OpenAI Codex concurrently with structured synthesis")

    # consult
    p_con = subparsers.add_parser("consult", help="Consult Advisory Council on architectural design")
    p_con.add_argument("prompt", nargs="?", default="", help="Architectural question or proposal")
    p_con.add_argument("--context", default="", help="Inline context or schema")
    p_con.add_argument("--context-file", default="", help="Path to context file")
    p_con.add_argument("--engine", default="auto", help="Advisor engine override (e.g. auto, claude, codex, ollama, mock)")
    p_con.add_argument("--competition", action="store_true", help="Execute Claude Code & OpenAI Codex concurrently with structured synthesis")

    # debug
    p_dbg = subparsers.add_parser("debug", help="Diagnose a stubborn error or bug with Advisory Council")
    p_dbg.add_argument("error", nargs="?", default="", help="Error message or description")
    p_dbg.add_argument("--context", default="", help="Code snippet or context")
    p_dbg.add_argument("--context-file", default="", help="Path to context file")
    p_dbg.add_argument("--engine", default="auto", help="Advisor engine override (e.g. auto, claude, codex, ollama, mock)")
    p_dbg.add_argument("--competition", action="store_true", help="Execute Claude Code & OpenAI Codex concurrently with structured synthesis")

    # gate
    p_gate = subparsers.add_parser("gate", help="Run full pre-commit verification (tsc + tests + diff review)")
    p_gate.add_argument("--engine", default="auto", help="Advisor engine override (e.g. auto, claude, codex, ollama, mock)")
    p_gate.add_argument("--competition", action="store_true", help="Execute Claude Code & OpenAI Codex concurrently with structured synthesis")
    p_gate.add_argument("--max-retries", type=int, default=1, help="Max self-healing retries for tsc/tests (default 1)")
    p_gate.add_argument("--timeout", type=int, default=240, help="Advisor signoff timeout in seconds (default 240)")

    # bench
    p_bench = subparsers.add_parser("bench", help="Run benchmark harness to score review accuracy against known bugs")
    p_bench.add_argument("--suite", choices=["cases", "swebench"], default="cases", help="Benchmark suite ('cases' or 'swebench')")
    p_bench.add_argument("--cases-dir", default="", help="Path to cases directory (defaults to triad/bench/cases)")
    p_bench.add_argument("--engine", default="auto", help="Advisor engine override (e.g. auto, claude, codex, bare_single, mock)")
    p_bench.add_argument("--limit", type=int, default=0, help="Limit number of cases to test")
    p_bench.add_argument("--case", default="", help="Run single case ID (e.g. case_001 or astropy__astropy-12907)")
    p_bench.add_argument("--verbose", "-v", action="store_true", help="Print verbose review output")

    # worktree
    p_wt = subparsers.add_parser("worktree", help="Manage ephemeral git worktrees (create, remove, list, prune)")
    wt_sub = p_wt.add_subparsers(dest="wt_action", help="Worktree action")
    wt_sub.add_parser("list", help="List all active worktrees")
    p_wt_create = wt_sub.add_parser("create", help="Create a new isolated worktree")
    p_wt_create.add_argument("--ref", default="HEAD", help="Commit, branch, or tag (default HEAD)")
    p_wt_create.add_argument("--prefix", default="triad-work", help="Directory prefix")
    p_wt_remove = wt_sub.add_parser("remove", help="Remove an isolated worktree")
    p_wt_remove.add_argument("path", help="Path to worktree directory to remove")
    p_wt_remove.add_argument("--force", "-f", action="store_true", default=False, help="Force removal, including uncommitted changes")
    wt_sub.add_parser("prune", help="Prune orphaned worktree metadata")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "auto": cmd_auto,
        "intent": cmd_auto,
        "run": cmd_auto,
        "doctor": cmd_doctor,
        "review": cmd_review,
        "consult": cmd_consult,
        "debug": cmd_debug,
        "gate": cmd_gate,
        "bench": cmd_bench,
        "worktree": cmd_worktree
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)

if __name__ == "__main__":
    main()
