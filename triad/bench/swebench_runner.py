#!/usr/bin/env python3
"""
SWE-bench Verified Runner for Autonomous Multi-Agent Triad.
Evaluates the Triad Advisory Council (Antigravity <-> Claude Code <-> OpenAI Codex)
against public SWE-bench Verified instances with $0 incremental API cost.

Key Capabilities:
- Loads curated SWE-bench Verified instances (astropy, django, pytest, etc.).
- Multi-engine support: auto (Claude -> Codex failover), claude, codex, bare_single (single baseline).
- Mode selection: 'debug' (surgical error diagnosis) or 'architect' (system design & refactoring).
- Extract unified diff patches and code solutions from model responses.
- Worktree Isolation (Phase C): Every patch application and test evaluation runs inside
  an isolated git worktree via triad.worktree.isolated_worktree, automatically pruned on exit.
- Real Git Patch Application:
    1. Downloads & caches target base files from repo at base_commit.
    2. Initializes base git state inside the isolated worktree.
    3. Runs 'git apply --check' and 'git apply' to verify syntactic & context alignment.
    4. Applies instance's real test_patch via 'git apply'.
- Real Test Execution & Multi-Metric Evaluation:
    Runs the instance's real FAIL_TO_PASS tests inside the isolated worktree.
    Strictly scores 'Real Test-Verified' based on actual passing tests (code 0).
    Separately tracks 'Git Apply Succeeded' and 'Semantic Judge Match' diagnostic metrics.
- Zero Lingering Worktrees: Guarantees 'git worktree list' is clean after execution.
- Logs per-instance outcomes and outputs the verified benchmark score.
"""

import sys
import os
import re
import json
import argparse
import tempfile
import subprocess
import urllib.request
import urllib.error
import shutil
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Ensure repo root and triad directory are importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRIAD_DIR = Path(__file__).resolve().parent.parent
for p in [str(REPO_ROOT), str(TRIAD_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from triad_engine import query_advisory_council, query_claude, query_codex
from triad.worktree import isolated_worktree, list_worktrees, get_repo_root

DEFAULT_INSTANCES_FILE = Path(__file__).resolve().parent / "swebench_instances.json"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"


def load_instances(file_path: Path) -> List[Dict[str, Any]]:
    """Loads SWE-bench instances from JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Instances file not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_files_from_diff(diff_text: str) -> List[str]:
    """Extracts target file paths mentioned in a unified diff or patch."""
    files = set()
    for line in diff_text.splitlines():
        m_git = re.match(r"^diff\s+--git\s+[a-z]/(.*?)\s+[a-z]/(.*)", line)
        if m_git:
            f1, f2 = m_git.group(1), m_git.group(2)
            if not f1.endswith("dev/null"):
                files.add(f1)
            if not f2.endswith("dev/null"):
                files.add(f2)
            continue
        m_minus = re.match(r"^---\s+(?:[a-z]/)?(\S+)", line)
        if m_minus and not m_minus.group(1).endswith("dev/null"):
            files.add(m_minus.group(1))
            continue
        m_plus = re.match(r"^\+\+\+\s+(?:[a-z]/)?(\S+)", line)
        if m_plus and not m_plus.group(1).endswith("dev/null"):
            files.add(m_plus.group(1))
            continue
    return sorted(list(files))


def normalize_unified_diff(patch_text: str) -> str:
    """
    Normalizes LLM-generated unified diffs for git apply compatibility:
    1. Ensures empty context lines inside hunks have the mandatory leading space.
    2. Converts CRLF to LF.
    3. Preserves exact line contents (including code indentation and trailing spaces).
    """
    if not patch_text:
        return ""

    text = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")

    # Trim purely empty lines from the very start and end of the patch payload
    start = 0
    while start < len(raw_lines) and raw_lines[start] == "":
        start += 1
    end = len(raw_lines)
    while end > start and raw_lines[end - 1] == "":
        end -= 1
    lines = raw_lines[start:end]

    fixed = []
    in_hunk = False
    for line in lines:
        if line.startswith("@@") and "@@" in line[2:]:
            in_hunk = True
            fixed.append(line)
        elif line.startswith(("diff ", "--- ", "+++ ", "index ")):
            in_hunk = False
            fixed.append(line)
        elif in_hunk:
            if line == "":
                fixed.append(" ")
            elif not line.startswith(("+", "-", " ", "\\")):
                fixed.append(" " + line)
            else:
                fixed.append(line)
        else:
            fixed.append(line)
    return "\n".join(fixed) + "\n"



def extract_proposed_patch(response: str, expected_files: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Extracts the proposed unified diff patch or code replacement from model output.
    Returns dictionary with raw patch, parsed files, hunks, and validity status.
    """
    patch_text = ""
    code_snippets = []

    # 1. Search for fenced code blocks with diff or patch tags
    diff_blocks = re.findall(r"```(?:diff|patch)\s*\n(.*?)```", response, re.DOTALL)
    if diff_blocks:
        patch_text = "\n\n".join(b.strip() for b in diff_blocks)

    # 2. Search for unfenced diff blocks (starts with diff --git or --- a/)
    if not patch_text:
        raw_diff_match = re.search(r"((?:diff\s+--git|---\s+[ab]/).*?(?:\n\n\n|\Z))", response, re.DOTALL)
        if raw_diff_match:
            patch_text = raw_diff_match.group(1).strip()

    # 3. Fallback: Search for generic python or unlabeled code blocks
    other_blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", response, re.DOTALL)
    if other_blocks:
        code_snippets = [b.strip() for b in other_blocks]

    # Normalize diff for git apply compatibility
    if patch_text:
        patch_text = normalize_unified_diff(patch_text)

    # Target files extracted from patch
    target_files = extract_files_from_diff(patch_text) if patch_text else []

    # If no files found from diff headers, look for expected file mentions in text/code
    if not target_files and expected_files:
        for f in expected_files:
            if f in response:
                target_files.append(f)

    added_lines = []
    deleted_lines = []
    for line in patch_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            deleted_lines.append(line[1:].strip())

    return {
        "patch_text": patch_text,
        "code_snippets": code_snippets,
        "target_files": target_files,
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
        "has_diff": bool(patch_text),
    }


def verify_git_patch_syntax(patch_text: str) -> Tuple[bool, str]:
    """
    Dry-run git patch syntax verification.
    Verifies that the extracted patch is a syntactically coherent unified diff.
    """
    if not patch_text.strip():
        return False, "No unified diff found"

    lines = [l for l in patch_text.splitlines() if l.strip()]
    has_header = any(l.startswith("---") or l.startswith("diff --git") for l in lines)
    has_hunk = any(re.match(r"^@@\s+.*?\s+@@", l) for l in lines)
    has_diff_op = any(l.startswith("+") or l.startswith("-") for l in lines)

    if not has_header:
        return False, "Missing diff headers ('---' or 'diff --git')"
    if not has_hunk and not has_diff_op:
        return False, "Missing hunk header or +/- changes"

    # Test git apply --stat dry-run using git command if git is available
    temp_patch = None
    try:
        temp_fd, temp_patch = tempfile.mkstemp(suffix=".patch", prefix="swebench_")
        with os.fdopen(temp_fd, "w", encoding="utf-8", errors="replace") as f:
            f.write(patch_text + "\n")

        proc = subprocess.run(
            ["git", "apply", "--recount", "--stat", temp_patch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5
        )
        if proc.returncode == 0:
            return True, "Valid unified diff (git apply parsed successfully)"
    except Exception:
        pass
    finally:
        if temp_patch and os.path.exists(temp_patch):
            try:
                os.remove(temp_patch)
            except Exception:
                pass

    if has_header and (has_hunk or has_diff_op):
        return True, "Valid unified diff format (headers and hunks present)"
    return False, "Malformed diff structure"


def ensure_base_file(repo: str, base_commit: str, rel_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """
    Fetches base file from GitHub at base_commit and caches locally.
    Enforces path containment and atomic write.
    Returns (cached_path, error_description).
    """
    clean_rel = Path(rel_path)
    if clean_rel.is_absolute() or ".." in clean_rel.parts:
        return None, "Invalid path or traversal"

    cache_path = (CACHE_DIR / repo / base_commit / clean_rel).resolve()
    if not cache_path.is_relative_to(CACHE_DIR.resolve()):
        return None, "Path traversal attempt"

    if cache_path.exists():
        return cache_path, None

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://raw.githubusercontent.com/{repo}/{base_commit}/{rel_path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TriadBench/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().replace(b"\r\n", b"\n")
            fd, tmp_path = tempfile.mkstemp(dir=str(cache_path.parent), prefix="tmp_cache_")
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            os.replace(tmp_path, str(cache_path))
            return cache_path, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP_{e.code}"
    except Exception as e:
        return None, f"Network_error_{e}"


def verify_semantic_resolution(
    instance: Dict[str, Any],
    proposed_patch: str,
    full_response: str,
    engine: str = "auto"
) -> Tuple[bool, str]:
    """
    Semantic resolution check using Model-as-a-Judge against gold patch and SWE-bench test criteria.
    Enforces scoring of final proposed fix and allows bug identification anywhere in findings.
    """
    gold_patch = instance.get("patch", "")
    fail_to_pass = instance.get("FAIL_TO_PASS", [])
    problem = instance.get("problem_statement", "")[:1200]

    # Fast path: Check for direct token / logic containment with gold patch
    gold_additions = [l[1:].strip() for l in gold_patch.splitlines() if l.startswith("+") and not l.startswith("+++") and l.strip()[1:].strip()]
    if gold_additions:
        solution_blob = (proposed_patch + "\n" + full_response).lower()
        matched_additions = sum(1 for add in gold_additions if add.lower() in solution_blob)
        if matched_additions == len(gold_additions) and len(gold_additions) > 0:
            return True, f"Exact gold-patch match ({matched_additions}/{len(gold_additions)} key changes verified)"

    fail_tests_str = "\n".join(f"- {t}" for t in fail_to_pass[:6])
    judge_prompt = (
        "You are an automated SWE-bench test harness simulation evaluator.\n"
        "Determine if the proposed code patch or solution resolves the issue and satisfies the test criteria.\n\n"
        f"ISSUE:\n{problem}\n\n"
        f"FAILING TESTS THAT MUST PASS:\n{fail_tests_str}\n\n"
        f"REFERENCE GOLD PATCH:\n```diff\n{gold_patch[:1500]}\n```\n\n"
        f"PROPOSED SOLUTION TO EVALUATE:\n```\n{proposed_patch or full_response[:2000]}\n```\n\n"
        "CRITERIA:\n"
        "1. Does the proposed patch directly target the root cause of the issue?\n"
        "2. Does it apply the correct functional fix matching or equivalent to the reference gold patch?\n"
        "3. Would this fix make the specified failing tests pass without introducing syntax errors or regressions?\n"
        "Score the reviewer's final verdict and proposed code, not exploratory or retracted hypotheses.\n\n"
        "Answer with exactly 'VERDICT: RESOLVED' or 'VERDICT: UNRESOLVED' on the first line, "
        "followed by a 1-sentence rationale on the second line."
    )

    try:
        if engine == "codex":
            judge_verdict = query_codex(judge_prompt, mode="general", timeout=40)
        else:
            judge_verdict = query_claude(judge_prompt, mode="general", timeout=40)
            if not judge_verdict or "[error" in judge_verdict.lower() or "limit" in judge_verdict.lower():
                judge_verdict = query_codex(judge_prompt, mode="general", timeout=40)

        raw_verdict = (judge_verdict or "").strip()
        if not raw_verdict or "[error" in raw_verdict.lower() or "timeout" in raw_verdict.lower():
            return False, f"Judge error: {raw_verdict or 'No response'}"

        lines = raw_verdict.splitlines()
        first_line = lines[0].strip() if lines else ""
        rationale = lines[1].strip() if len(lines) > 1 else raw_verdict[:120]

        is_resolved = bool(re.search(r"\bVERDICT:\s*RESOLVED\b", first_line, re.IGNORECASE))
        is_unresolved = bool(re.search(r"\bVERDICT:\s*UNRESOLVED\b", first_line, re.IGNORECASE))

        if is_resolved and not is_unresolved:
            return True, f"Verified: {rationale}"
        else:
            return False, f"Unresolved: {rationale}"
    except Exception as e:
        return False, f"Judge exception ({e})"


def evaluate_in_worktree(
    instance: Dict[str, Any],
    extracted_patch: Dict[str, Any],
    full_response: str,
    repo_root: Path,
    engine: str = "auto"
) -> Dict[str, Any]:
    """
    Evaluates instance patch inside an isolated git worktree via triad.worktree.isolated_worktree.
    Applies the actual patch with git apply, applies test_patch, and attempts real test execution.
    """
    cid = instance.get("instance_id", "instance")
    repo = instance.get("repo", "unknown")
    base_commit = instance.get("base_commit", "HEAD")
    gold_patch = instance.get("patch", "")
    test_patch = instance.get("test_patch", "")
    raw_fail_to_pass = instance.get("FAIL_TO_PASS", [])
    if isinstance(raw_fail_to_pass, str):
        try:
            fail_to_pass = json.loads(raw_fail_to_pass)
        except Exception:
            fail_to_pass = [t.strip().strip("'\"") for t in raw_fail_to_pass.strip("[]").split(",") if t.strip()]
    elif isinstance(raw_fail_to_pass, list):
        fail_to_pass = raw_fail_to_pass
    else:
        fail_to_pass = []

    gold_files = extract_files_from_diff(gold_patch)
    test_files = extract_files_from_diff(test_patch)
    candidate_files = extracted_patch.get("target_files", [])
    all_needed_files = sorted(list(set(gold_files + test_files + candidate_files)))

    candidate_patch_text = extracted_patch.get("patch_text", "").strip()

    # 1. Syntax check
    is_valid_syntax, syntax_msg = verify_git_patch_syntax(candidate_patch_text)
    if not is_valid_syntax:
        return {
            "resolved": False,
            "test_verified": False,
            "semantic_resolved": False,
            "worktree_isolated": False,
            "patch_applied": False,
            "test_patch_applied": False,
            "tests_executed": False,
            "tests_passed": False,
            "resolution_method": "SYNTAX_INVALID",
            "message": syntax_msg,
            "dry_run_valid": False,
            "target_files_match": False,
        }

    # 2. Worktree lifecycle
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", cid)[:16]
    worktree_isolated = False
    patch_applied = False
    test_patch_applied = False
    tests_executed = False
    tests_passed = False
    semantic_resolved = False
    resolution_method = "UNKNOWN"
    exec_msg = ""

    try:
        with isolated_worktree(repo_root, prefix=f"triad-wt-{safe_id}") as wt:
            worktree_isolated = True

            # Copy base files into worktree with path containment enforcement
            infra_errors = []
            files_added_to_base = 0
            for rel in all_needed_files:
                cached_file, err = ensure_base_file(repo, base_commit, rel)
                if cached_file and cached_file.exists():
                    dest = (wt / rel).resolve()
                    if not dest.is_relative_to(wt.resolve()):
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(cached_file.read_bytes())
                    subprocess.run(["git", "-C", str(wt), "-c", "core.autocrlf=false", "add", "-f", rel], capture_output=True)
                    files_added_to_base += 1
                elif err and not rel.endswith("dev/null"):
                    infra_errors.append(f"{rel} ({err})")

            if infra_errors:
                exec_msg = f"Infrastructure error fetching base files: {', '.join(infra_errors[:3])}"
                resolution_method = "INFRA_NETWORK_ERROR"
            elif files_added_to_base == 0 and any(not f.endswith("dev/null") for f in all_needed_files):
                exec_msg = "No base files materialized in worktree"
                resolution_method = "INFRA_BASE_FILES_MISSING"
            else:
                if files_added_to_base > 0:
                    subprocess.run([
                        "git", "-C", str(wt),
                        "-c", "core.autocrlf=false",
                        "-c", "user.name=TriadBench", "-c", "user.email=bench@triad.local",
                        "commit", "-m", "Initialize base files at base_commit"
                    ], capture_output=True)

                # Apply candidate patch via git apply
                cand_patch_file = wt / "candidate.patch"
                cand_patch_file.write_bytes(normalize_unified_diff(candidate_patch_text).encode("utf-8"))

                res_apply = subprocess.run([
                    "git", "-C", str(wt),
                    "-c", "core.autocrlf=false",
                    "apply",
                    "--recount", "--ignore-space-change", "--ignore-whitespace",
                    str(cand_patch_file)
                ], capture_output=True, text=True)

                if res_apply.returncode == 0:
                    patch_applied = True
                    exec_msg = "Git apply succeeded in isolated worktree"

                    if test_patch:
                        tpatch_file = wt / "test.patch"
                        tpatch_file.write_bytes(normalize_unified_diff(test_patch).encode("utf-8"))
                        res_tpatch = subprocess.run([
                            "git", "-C", str(wt),
                            "-c", "core.autocrlf=false",
                            "apply",
                            "--recount", "--ignore-space-change", "--ignore-whitespace",
                            str(tpatch_file)
                        ], capture_output=True, text=True)
                        test_patch_applied = (res_tpatch.returncode == 0)
                    else:
                        test_patch_applied = True

                    # Attempt real test execution if tests are specified and test_patch applied cleanly
                    if fail_to_pass and test_patch_applied:
                        # Dynamically discover test runner
                        uv_bin = shutil.which("uv") or shutil.which("uv.exe") or os.environ.get("UV_PATH")

                        target_tests = list(fail_to_pass)
                        test_cmd = None
                        if uv_bin:
                            test_cmd = [uv_bin, "run", "--with", "pytest", "--python", "3.11", "pytest"] + target_tests
                        elif shutil.which("pytest"):
                            test_cmd = ["pytest"] + target_tests

                        if test_cmd:
                            env = os.environ.copy()
                            env["PYTHONPATH"] = str(wt)
                            try:
                                res_test = subprocess.run(
                                    test_cmd,
                                    cwd=str(wt),
                                    env=env,
                                    capture_output=True,
                                    text=True,
                                    timeout=45
                                )
                                if res_test.returncode == 0:
                                    tests_executed = True
                                    tests_passed = True
                                    resolution_method = "REAL_TEST_EXECUTION"
                                    exec_msg = "Real tests passed with 0 errors in worktree"
                                elif res_test.returncode == 1:
                                    tests_executed = True
                                    tests_passed = False
                                    resolution_method = "TESTS_FAILED"
                                    exec_msg = "Real tests executed and assertions failed (exit code 1)"
                                else:
                                    tests_executed = False
                                    tests_passed = False
                                    resolution_method = "TEST_COLLECTION_ERROR"
                                    exec_msg = f"Test environment/collection error (exit code {res_test.returncode})"
                            except subprocess.TimeoutExpired:
                                tests_executed = True
                                tests_passed = False
                                resolution_method = "TESTS_TIMEOUT"
                                exec_msg = "Real tests timed out after 45s"
                            except Exception as e:
                                tests_executed = False
                                tests_passed = False
                                resolution_method = "TESTS_ERROR"
                                exec_msg = f"Real tests execution error: {e}"
                    elif test_patch and not test_patch_applied:
                        resolution_method = "TEST_PATCH_FAILED"
                        exec_msg = "Authoritative test patch failed to apply in worktree"

                    # If test runner could not execute (e.g. missing dependencies or collection error)
                    # and test_patch did not explicitly fail, evaluate semantic resolution for diagnostics
                    if not tests_executed and not tests_passed:
                        is_sem_res, sem_msg = verify_semantic_resolution(
                            instance=instance,
                            proposed_patch=candidate_patch_text,
                            full_response=full_response,
                            engine=engine
                        )
                        semantic_resolved = is_sem_res
                        if not exec_msg:
                            exec_msg = f"Diagnostic semantic evaluation: {sem_msg}"
                        else:
                            exec_msg = f"{exec_msg} (Diagnostic semantic: {sem_msg})"
                else:
                    patch_applied = False
                    err_clean = (res_apply.stderr or res_apply.stdout or "patch does not apply").strip().splitlines()
                    first_err = err_clean[0] if err_clean else "git apply failed"
                    exec_msg = f"Git apply failed: {first_err}"
                    resolution_method = "GIT_APPLY_FAILED"

    except Exception as e:
        exec_msg = f"Worktree execution exception: {e}"
        resolution_method = "WORKTREE_ERROR"

    # A solution is resolved if and only if real authoritative tests execute and pass
    test_verified = bool(tests_executed and tests_passed)
    resolved = test_verified

    target_match = False
    proposed_files = extracted_patch.get("target_files", [])
    if gold_files:
        target_match = any(gf in proposed_files for gf in gold_files)
    else:
        target_match = bool(proposed_files)

    return {
        "resolved": resolved,
        "test_verified": test_verified,
        "semantic_resolved": semantic_resolved,
        "worktree_isolated": worktree_isolated,
        "patch_applied": patch_applied,
        "test_patch_applied": test_patch_applied,
        "tests_executed": tests_executed,
        "tests_passed": tests_passed,
        "resolution_method": resolution_method,
        "message": exec_msg,
        "dry_run_valid": is_valid_syntax,
        "target_files_match": target_match,
    }


def build_swebench_prompt(instance: Dict[str, Any], mode: str = "debug") -> str:
    """Builds a structured prompt for the advisory council for a SWE-bench instance."""
    inst_id = instance.get("instance_id", "Unknown")
    repo = instance.get("repo", "Unknown")
    problem = instance.get("problem_statement", "").strip()
    fail_to_pass = instance.get("FAIL_TO_PASS", [])

    failing_tests_str = ""
    if fail_to_pass:
        failing_tests_str = "TARGET FAILING TESTS TO FIX:\n" + "\n".join(f"- {t}" for t in fail_to_pass[:10]) + "\n\n"

    if mode == "architect":
        task_instructions = (
            "TASK: Analyze the architectural design flaw causing this issue in the repository.\n"
            "Provide the optimal surgical fix in unified diff format (```diff ... ```) "
            "that resolves the root cause and passes all tests without introducing regressions."
        )
    else:
        task_instructions = (
            "TASK: Diagnose the persistent bug causing this issue in the repository.\n"
            "Identify the exact root cause and provide the cleanest surgical fix in unified diff format (```diff ... ```) "
            "so that the target failing tests pass and existing behavior is preserved."
        )

    diff_format_rules = (
        "UNIFIED DIFF FORMAT (required, strictly enforced):\n"
        "- Each hunk header MUST be exactly '@@ -<start>,<count> +<start>,<count> @@' "
        "(real line numbers from the original file, not '@@ def foo(...):').\n"
        "- Every hunk line must start with '+', '-', or a single space for unchanged context — "
        "never omit the leading space on context lines.\n"
        "- Include '--- a/<path>' and '+++ b/<path>' headers before each hunk.\n"
        "- Do not truncate, abbreviate, or elide any part of the diff (no '...' placeholders).\n"
        "- Output nothing after the closing ``` — no explanation, no trailing commentary.\n"
    )

    return (
        f"SWE-bench Verified Issue: {inst_id}\n"
        f"Repository: {repo}\n\n"
        f"PROBLEM STATEMENT:\n{problem}\n\n"
        f"{failing_tests_str}"
        f"{task_instructions}\n\n"
        f"{diff_format_rules}\n"
        "Output the complete unified diff patch within a single ```diff ... ``` code block."
    )


def build_retry_prompt(instance: Dict[str, Any], mode: str, prior_error: str) -> str:
    """Builds a corrective retry prompt after a malformed/unparseable diff."""
    base_prompt = build_swebench_prompt(instance, mode=mode)
    return (
        f"{base_prompt}\n\n"
        "---\n"
        "NOTE: Your previous attempt produced a patch that failed to apply with git.\n"
        f"Error: {prior_error}\n"
        "Common causes: fabricated/approximate hunk headers instead of real line numbers, "
        "missing context lines, or omitted/abbreviated code. "
        "Re-read the problem statement and produce a corrected, complete, exact unified diff."
    )


def run_swebench(
    instances_file: Path = DEFAULT_INSTANCES_FILE,
    engine: str = "auto",
    limit: int = 5,
    instance_id: str = "",
    mode: str = "debug",
    verbose: bool = False
) -> Tuple[int, int, List[Dict[str, Any]]]:
    """
    Executes the SWE-bench runner across instances.
    Returns (resolved_count, total_count, detailed_results).
    """
    instances = load_instances(instances_file)
    repo_root = get_repo_root(REPO_ROOT)

    if instance_id:
        instances = [inst for inst in instances if instance_id.lower() in inst.get("instance_id", "").lower()]
        if not instances:
            print(f"[SWE-bench Runner] No instances found matching ID '{instance_id}'")
            return 0, 0, []

    if limit > 0:
        instances = instances[:limit]

    total = len(instances)
    resolved_count = 0
    results = []

    print("================================================================================")
    print("TRIAD SWE-BENCH VERIFIED RUNNER (Worktree Isolation & Real Patch Execution)")
    print(f"Engine: {engine} | Mode: {mode} | Instances: {total}")
    print(f"Dataset: {instances_file.resolve()}")
    print("Zero-Incremental-Cost Policy: Active ($0 token billing)")
    print("Worktree Isolation: Enabled (triad.worktree)")
    print("================================================================================")

    initial_wts = len(list_worktrees(repo_root))
    limit_hit = False

    for idx, inst in enumerate(instances, 1):
        cid = inst.get("instance_id", f"case_{idx}")
        repo = inst.get("repo", "unknown")
        prob_first_line = (inst.get("problem_statement", "").strip().splitlines() or [""])[0][:55]
        gold_files = extract_files_from_diff(inst.get("patch", ""))

        print(f"[{idx:02d}/{total:02d}] {cid} ({repo}): {prob_first_line}...", end=" ", flush=True)

        advisor_prompt = build_swebench_prompt(inst, mode=mode)

        try:
            # Query advisory council or single baseline model
            if engine == "bare_single":
                raw_response = query_claude(advisor_prompt, mode=mode, timeout=120)
            else:
                raw_response = query_advisory_council(advisor_prompt, mode=mode, engine=engine)

            # Check for error or empty responses
            if not raw_response or raw_response.startswith("[Error"):
                print(f"✗ ERROR ({raw_response[:60]})")
                results.append({
                    "instance_id": cid,
                    "repo": repo,
                    "resolved": False,
                    "error": raw_response
                })
                is_limit = raw_response and (
                    "session limit" in raw_response.lower() or "rate limit" in raw_response.lower()
                )
                if is_limit:
                    limit_hit = True
                    remaining = total - idx
                    print(
                        f"\n[Aborting] {engine} hit a session/rate limit at instance {idx}/{total}. "
                        f"Stopping sweep early — {remaining} remaining instance(s) were not evaluated "
                        "(not counted as failures)."
                    )
                    break
                continue

            # Extract patch / solution
            extracted = extract_proposed_patch(raw_response, expected_files=gold_files)

            # If the extracted patch fails basic syntax validation, retry once with a
            # corrective prompt before giving up — model diff generation is non-deterministic
            # and a single malformed attempt shouldn't sink an otherwise-solvable instance.
            retried = False
            syntax_ok, syntax_err = verify_git_patch_syntax(extracted.get("patch_text", ""))
            if not syntax_ok:
                retried = True
                retry_prompt = build_retry_prompt(inst, mode=mode, prior_error=syntax_err)
                if engine == "bare_single":
                    retry_response = query_claude(retry_prompt, mode=mode, timeout=120)
                else:
                    retry_response = query_advisory_council(retry_prompt, mode=mode, engine=engine)

                if retry_response and not retry_response.startswith("[Error"):
                    retry_extracted = extract_proposed_patch(retry_response, expected_files=gold_files)
                    retry_ok, _ = verify_git_patch_syntax(retry_extracted.get("patch_text", ""))
                    if retry_ok:
                        raw_response = retry_response
                        extracted = retry_extracted

            # Evaluate inside isolated git worktree
            eval_result = evaluate_in_worktree(
                instance=inst,
                extracted_patch=extracted,
                full_response=raw_response,
                repo_root=repo_root,
                engine=engine
            )

            is_res = eval_result["resolved"]
            if is_res:
                resolved_count += 1
                status_str = "✓ RESOLVED"
            else:
                status_str = "✗ UNRESOLVED"

            details = []
            if retried:
                details.append("retried: yes")
            if eval_result.get("worktree_isolated"):
                details.append("worktree: isolated")
            if eval_result.get("patch_applied"):
                details.append("patch: applied")
            if eval_result.get("tests_passed"):
                details.append("tests: pass")
            elif eval_result.get("semantic_resolved"):
                details.append("semantic: match")

            tag = f" ({', '.join(details)})" if details else ""
            print(f"{status_str}{tag}")

            if verbose:
                print(f"    - Method: {eval_result.get('resolution_method')}")
                print(f"    - Message: {eval_result.get('message')}")
                if extracted.get("target_files"):
                    print(f"    - Target Files: {', '.join(extracted['target_files'])}")
                print(f"    - Patch Preview: {extracted.get('patch_text', '')[:120] or 'No diff block'}...")

            results.append({
                "instance_id": cid,
                "repo": repo,
                "resolved": is_res,
                "evaluation": eval_result,
                "extracted_patch": extracted.get("patch_text", "")[:500],
                "sample_response": raw_response[:300]
            })

        except Exception as e:
            print(f"✗ EXCEPTION ({e})")
            results.append({
                "instance_id": cid,
                "repo": repo,
                "resolved": False,
                "error": str(e)
            })

    # Verify zero lingering worktrees
    final_wts = len(list_worktrees(repo_root))
    if final_wts > initial_wts:
        print(f"\n[Warning] {final_wts - initial_wts} lingering worktree(s) detected. Pruning...")
        from triad.worktree import prune_worktrees
        prune_worktrees(repo_root)

    attempted = len(results)
    pct_res = (resolved_count / attempted * 100) if attempted > 0 else 0.0
    test_verified_count = sum(1 for r in results if r.get("evaluation", {}).get("test_verified", False))
    pct_test = (test_verified_count / attempted * 100) if attempted > 0 else 0.0
    git_apply_count = sum(1 for r in results if r.get("evaluation", {}).get("patch_applied", False))
    pct_git = (git_apply_count / attempted * 100) if attempted > 0 else 0.0
    sem_count = sum(1 for r in results if r.get("evaluation", {}).get("semantic_resolved", False))
    pct_sem = (sem_count / attempted * 100) if attempted > 0 else 0.0

    print("================================================================================")
    print("SWE-BENCH VERIFIED RESULT:")
    if limit_hit:
        print(f"  - Sweep aborted early:    {attempted}/{total} instances attempted (session/rate limit hit)")
    print(f"  - Real Test-Verified:     {resolved_count}/{attempted} ({pct_res:.1f}%)")
    print(f"  - Git Apply Succeeded:    {git_apply_count}/{attempted} ({pct_git:.1f}%)")
    print(f"  - Semantic Match (Diag):  {sem_count}/{attempted} ({pct_sem:.1f}%)")
    print(f"  - Advisory Engine:        {engine}")
    print("================================================================================\n")

    return resolved_count, attempted, results


def main():
    parser = argparse.ArgumentParser(description="Triad SWE-bench Verified Runner")
    parser.add_argument(
        "--dataset", "--cases-file",
        dest="dataset",
        default=str(DEFAULT_INSTANCES_FILE),
        help="Path to swebench_instances.json"
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "claude", "codex", "bare_single"],
        default="auto",
        help="Advisory engine (auto, claude, codex, bare_single)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of instances to evaluate (default 5, up to 30)"
    )
    parser.add_argument(
        "--instance",
        default="",
        help="Filter by single instance ID (e.g. astropy__astropy-12907)"
    )
    parser.add_argument(
        "--mode",
        choices=["debug", "architect"],
        default="debug",
        help="Advisor operation mode (debug or architect)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print verbose evaluation details"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Save evaluation report to JSON file"
    )

    args = parser.parse_args()
    instances_file = Path(args.dataset)

    resolved, total, results = run_swebench(
        instances_file=instances_file,
        engine=args.engine,
        limit=args.limit,
        instance_id=args.instance,
        mode=args.mode,
        verbose=args.verbose
    )

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "resolved": resolved,
                "total": total,
                "percentage": (resolved / total * 100) if total > 0 else 0,
                "engine": args.engine,
                "mode": args.mode,
                "results": results
            }, f, indent=2)
        print(f"Report saved to {out_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
