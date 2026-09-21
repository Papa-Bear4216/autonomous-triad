#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hardened Benchmark Harness for Autonomous Multi-Agent Triad.
Uses model-as-a-judge scoring (replacing keyword matching) and negative controls.
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Ensure UTF-8 output on Windows consoles and redirected streams
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure parent triad directory is importable
TRIAD_ROOT = Path(__file__).resolve().parent.parent
if str(TRIAD_ROOT) not in sys.path:
    sys.path.insert(0, str(TRIAD_ROOT))

from triad_engine import query_advisory_council, query_claude, query_codex

DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"

def judge_catch(bug_description: str, review_response: str) -> bool:
    """
    Ask a model whether the review response specifically and correctly identifies
    the seeded bug anywhere in its findings, rather than relying on presentation order.
    """
    judge_prompt = (
        "You are scoring a code review for accuracy, not presentation order.\n\n"
        f"THE ACTUAL BUG: {bug_description}\n\n"
        f"THE REVIEW RESPONSE TO SCORE:\n{review_response}\n\n"
        "Does this review, ANYWHERE in its findings (not just the first/headline finding), "
        "correctly and specifically identify this bug? A thorough review often finds multiple "
        "issues and ranks them by severity — the planted bug may be item #2 or #3, or folded "
        "into a broader finding, rather than the top-billed item. That still counts as a catch. "
        "It does NOT count if the review only mentions adjacent-sounding concerns without "
        "actually identifying this specific defect. "
        "Score the reviewer's final verdict, not exploratory or retracted hypotheses.\n"
        "Answer with exactly one word: YES or NO."
    )
    verdict = query_claude(judge_prompt, mode="general", timeout=30)
    if not verdict or "[error" in verdict.lower() or "limit" in verdict.lower():
        verdict = query_codex(judge_prompt, mode="general", timeout=30)

    first_word = verdict.strip().upper().split()[0] if (verdict and verdict.strip()) else ""
    return first_word.startswith("YES")

def judge_false_positive(review_response: str) -> bool:
    """
    Ask a model whether the review claimed to find a bug/defect in a clean, benign diff.
    """
    judge_prompt = (
        "You are evaluating a code review of a completely correct, benign diff with no bugs.\n\n"
        f"THE REVIEW RESPONSE TO SCORE:\n{review_response}\n\n"
        "Did this review assert or flag that the diff itself introduces an actual defect, logic bug, syntax error, or security vulnerability? "
        "Score the reviewer's final verdict, not exploratory or retracted hypotheses that the reviewer subsequently disproved or dismissed. "
        "Answer NO if the review considers the diff sound/clean, approves the change, states it is safe to merge, or only mentions style/docs or pre-existing code outside the diff. "
        "Answer YES only if the review's final verdict asserts that the diff itself introduces an actual defect, bug, or vulnerability.\n"
        "Answer with exactly one word: YES or NO."
    )
    verdict = query_claude(judge_prompt, mode="general", timeout=30)
    if not verdict or "[error" in verdict.lower() or "limit" in verdict.lower():
        verdict = query_codex(judge_prompt, mode="general", timeout=30)

    first_word = verdict.strip().upper().split()[0] if verdict.strip() else ""
    return first_word.startswith("YES")

def run_benchmark(
    cases_dir: Path = DEFAULT_CASES_DIR,
    engine: str = "auto",
    limit: int = 0,
    case_id: str = "",
    verbose: bool = False
) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    """
    Runs the benchmark suite across all case JSONs in cases_dir.
    Returns (bugs_caught, positive_total, false_positives, negative_total, detailed_results).
    """
    case_files = sorted(list(cases_dir.glob("case_*.json")))
    if case_id:
        case_files = [f for f in case_files if case_id in f.stem]

    if not case_files:
        print(f"[Benchmark] No case files found in {cases_dir}")
        return 0, 0, 0, 0, []

    if limit > 0:
        case_files = case_files[:limit]

    total = len(case_files)
    positive_total = 0
    bugs_caught = 0
    negative_total = 0
    false_positives = 0
    results = []

    print("================================================================================")
    print(f"TRIAD ADVISORY BENCHMARK HARNESS (engine={engine}, cases={total})")
    print("Scoring: Model-as-Judge verification (No keyword matching)")
    print("================================================================================")

    for idx, case_path in enumerate(case_files, 1):
        with open(case_path, "r", encoding="utf-8") as f:
            case = json.load(f)

        cid = case.get("id", case_path.stem)
        expected = case.get("expected_catch", True)
        desc = case.get("bug_description", "")
        diff = case.get("diff", "")

        label = desc[:50] if desc else "[Negative Control - Clean Diff]"
        print(f"[{idx:02d}/{total:02d}] {cid}: {label}...", end=" ", flush=True)

        prompt = (
            "Review this git diff carefully. Identify any bugs, race conditions, type errors, "
            "security vulnerabilities, or unintended regressions. If none exist, state that the diff is sound."
        )

        try:
            # 1. Get raw review from advisory engine
            review = query_advisory_council(
                prompt=prompt,
                diff=diff,
                mode="review_diff",
                engine=engine
            )

            # 2. Judge review response
            if expected:
                positive_total += 1
                is_caught = judge_catch(desc, review)
                if is_caught:
                    bugs_caught += 1
                    print("✓ CAUGHT")
                else:
                    print("✗ MISSED")

                results.append({
                    "id": cid,
                    "type": "positive",
                    "description": desc,
                    "caught": is_caught,
                    "review_sample": review[:200]
                })
            else:
                negative_total += 1
                is_fp = judge_false_positive(review)
                if is_fp:
                    false_positives += 1
                    print("✗ FALSE POSITIVE")
                else:
                    print("✓ CLEAN PASS")

                results.append({
                    "id": cid,
                    "type": "negative_control",
                    "false_positive": is_fp,
                    "review_sample": review[:200]
                })

            if verbose:
                print(f"\n--- [FULL REVIEW: {cid}] ---\n{review.strip()}\n-------------------------------------------------\n")

        except Exception as e:
            print(f"ERROR ({e})")
            results.append({
                "id": cid,
                "error": str(e)
            })

    catch_rate = (bugs_caught / positive_total * 100) if positive_total > 0 else 0.0
    fp_rate = (false_positives / negative_total * 100) if negative_total > 0 else 0.0

    print("================================================================================")
    print(f"BENCHMARK RESULT: {bugs_caught}/{positive_total} bugs caught ({catch_rate:.1f}%) | "
          f"{false_positives}/{negative_total} false positives ({fp_rate:.1f}%) | engine={engine}")
    print("================================================================================\n")

    return bugs_caught, positive_total, false_positives, negative_total, results

def main():
    parser = argparse.ArgumentParser(description="Triad Benchmark Runner")
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR), help="Directory of test cases")
    parser.add_argument("--engine", choices=["auto", "claude", "codex"], default="auto", help="Advisor engine")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of cases to run")
    parser.add_argument("--case", default="", help="Run single case ID")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print verbose review output")
    parser.add_argument("--output", default="", help="Save JSON report to file")

    args = parser.parse_args()
    cases_dir = Path(args.cases_dir)
    bugs_caught, pos_tot, fps, neg_tot, results = run_benchmark(
        cases_dir=cases_dir,
        engine=args.engine,
        limit=args.limit,
        case_id=args.case,
        verbose=args.verbose
    )

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "bugs_caught": bugs_caught,
                "positive_total": pos_tot,
                "catch_rate": (bugs_caught / pos_tot * 100) if pos_tot > 0 else 0,
                "false_positives": fps,
                "negative_total": neg_tot,
                "false_positive_rate": (fps / neg_tot * 100) if neg_tot > 0 else 0,
                "engine": args.engine,
                "results": results
            }, f, indent=2)
        print(f"Report saved to {out_path}")

    sys.exit(0)

if __name__ == "__main__":
    main()
