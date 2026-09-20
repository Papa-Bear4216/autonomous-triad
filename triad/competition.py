"""
Competition Mode: Concurrent Dual-Advisor Execution & Structured Synthesis.
Runs Claude Code and OpenAI Codex concurrently, synthesizes agreements,
isolated points, and contradictions, and logs full telemetry.
"""

import sys
import os
import json
import time
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Tuple

try:
    from triad.advisor_manager import query_configured_advisor
except ImportError:
    from advisor_manager import query_configured_advisor

# Ensure logs directory exists
LOGS_DIR = Path(__file__).resolve().parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
COUNCIL_SESSIONS_LOG = LOGS_DIR / "council_sessions.jsonl"

def hash_content(text: str) -> str:
    """Generate MD5 hash of diff or prompt for session correlation."""
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()[:12]

def build_synthesis_prompt(prompt: str, claude_resp: str, codex_resp: str, context: str = None, diff: str = None) -> str:
    """Constructs rigorous 4-part synthesis prompt."""
    return (
        "You are the Chief Adjudicator of an elite Multi-Agent Advisory Council.\n"
        "Two independent premier AI models evaluated the same task. Your goal is NOT to average their answers, "
        "but to conduct a rigorous, evidence-based adjudication.\n\n"
        f"ORIGINAL TASK / QUERY:\n{prompt}\n\n"
        + (f"DIFF:\n```\n{diff}\n```\n\n" if diff else "")
        + (f"CONTEXT:\n```\n{context}\n```\n\n" if context else "")
        + f"--- ADVISOR 1 (Claude Code) REVIEW ---\n{claude_resp}\n\n"
        f"--- ADVISOR 2 (OpenAI Codex) REVIEW ---\n{codex_resp}\n\n"
        "Provide your adjudication in exactly these 4 structured sections:\n"
        "### 1. Points of Unanimous Agreement\n"
        "List all high-confidence findings, approvals, or bugs that BOTH advisors independently caught.\n\n"
        "### 2. Points Raised by Only One Advisor\n"
        "Itemize points raised by only one model. Adjudicate each: is it genuinely valid, a false positive, or speculative?\n\n"
        "### 3. Direct Contradictions\n"
        "Identify anywhere the advisors directly contradicted each other on facts, types, or correctness. If none, explicitly write 'None'.\n\n"
        "### 4. Final Adjudicated Verdict & Action Plan\n"
        "Give the single authoritative verdict. State which advisor's reasoning was more accurate and why, with the definitive fix/recommendation."
    )

def query_competition_council(
    prompt: str,
    context: str = None,
    diff: str = None,
    mode: str = "review_diff",
    timeout: int = 120,
    advisor_names: Tuple[str, str] = ("claude", "codex")
) -> Dict[str, Any]:
    """
    Executes two advisors concurrently and synthesizes their assessments.
    Returns structured session dictionary containing raw outputs and synthesis.
    """
    start_time = time.time()
    adv1_name, adv2_name = advisor_names
    results = {}

    # 1. Run advisors concurrently
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_adv1 = executor.submit(
            query_configured_advisor,
            adv1_name,
            prompt,
            context=context,
            diff=diff,
            mode=mode,
            timeout=timeout
        )
        future_adv2 = executor.submit(
            query_configured_advisor,
            adv2_name,
            prompt,
            context=context,
            diff=diff,
            mode=mode,
            timeout=timeout
        )

        try:
            results[adv1_name] = future_adv1.result()
        except Exception as e:
            results[adv1_name] = f"[Error from {adv1_name}: {e}]"

        try:
            results[adv2_name] = future_adv2.result()
        except Exception as e:
            results[adv2_name] = f"[Error from {adv2_name}: {e}]"

    resp1 = results.get(adv1_name, "")
    resp2 = results.get(adv2_name, "")

    # 2. Synthesize using primary advisor
    synth_prompt = build_synthesis_prompt(prompt, resp1, resp2, context=context, diff=diff)
    synthesis = query_configured_advisor(adv1_name, synth_prompt, mode="general", timeout=timeout)
    if not synthesis or "[error" in synthesis.lower() or "limit" in synthesis.lower():
        # Failover synthesis to second advisor
        synthesis = query_configured_advisor(adv2_name, synth_prompt, mode="general", timeout=timeout)

    elapsed = time.time() - start_time
    session_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "content_hash": hash_content((diff or "") + (prompt or "")),
        "advisors": [adv1_name, adv2_name],
        "responses": {
            adv1_name: resp1,
            adv2_name: resp2
        },
        "synthesis": synthesis,
        "elapsed_seconds": round(elapsed, 2)
    }

    # 3. Log to telemetry file
    try:
        with open(COUNCIL_SESSIONS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(session_data) + "\n")
    except Exception as e:
        print(f"[Warning: Failed to log council session: {e}]", file=sys.stderr)

    return session_data
