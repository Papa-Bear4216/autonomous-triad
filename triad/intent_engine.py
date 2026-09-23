"""
Autonomous Multi-Agent Triad: Intent Engine (intent_engine.py).
Zero-cost, ultra-fast intent classification and autonomous routing across:
- Advisory Council: Review (review_diff), Architect (consult), Debug (fix errors)
- High-Stakes Dual-Engine: Concurrent Competition Mode (Claude + Codex)
- Verification Gates: Ground-Truth pre-commit verification (tsc + tests + diff signoff)
- Hermes Agent: Android phone automation & device bridge
- Local Memory: PiecesOS (Port 39300) & Mem0 Semantic Recall
- System Health: Triad Doctor audit
"""

import sys
import os
import re
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List

# Ensure UTF-8 console output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

@dataclass
class IntentClassification:
    intent: str               # GATE, REVIEW, DEBUG, ARCHITECT, DEVICE, MEMORY, DOCTOR, GENERAL
    confidence: float         # 0.0 to 1.0
    reason: str               # Explanatory rationale for the classification
    suggested_mode: str       # review_diff, architect, debug, gate, doctor, general
    suggested_engine: str     # auto, competition, hermes, pieces, memory
    high_stakes: bool = False # Flagged if touching auth, security, crypto, migrations
    metadata: Dict[str, Any] = field(default_factory=dict)

# Regex Patterns for Deterministic Classification
DIFF_PATTERNS = [
    re.compile(r"^diff --git\s+a/.+\s+b/", re.MULTILINE),
    re.compile(r"^@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@", re.MULTILINE),
    re.compile(r"^---\s+(a/|\S+)\s*\n\+\+\+\s+(b/|\S+)", re.MULTILINE),
    re.compile(r"^index [0-9a-f]{7,}\.\.[0-9a-f]{7,}", re.MULTILINE),
]

STACK_TRACE_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE),
    re.compile(r"\b(TypeError|ReferenceError|SyntaxError|NullPointerException|IndexError|ValueError|AttributeError|KeyError):\s*.+", re.MULTILINE),
    re.compile(r"^\s+at\s+([a-zA-Z0-9_\.<>]+)\s+\((.+:\d+:\d+)\)", re.MULTILINE),
    re.compile(r"\berror TS\d+:", re.IGNORECASE),
    re.compile(r"\bFAILED\s*\(failures=\d+", re.IGNORECASE),
    re.compile(r"\b(npm|yarn|pnpm) ERR!", re.IGNORECASE),
    re.compile(r"panic:\s*.+", re.MULTILINE),
    re.compile(r"failed with exit code [1-9]\d*", re.IGNORECASE),
]

HIGH_STAKES_KEYWORDS = {
    "auth", "authentication", "authorization", "oauth", "jwt", "crypto",
    "password", "secret", "private key", "database migration", "schema migration",
    "rls", "row level security", "concurrency", "deadlock", "race condition",
    "stripe", "billing", "payment", "pci", "data loss", "irreversible"
}

GATE_KEYWORDS = [
    "pre-commit", "ready to commit", "commit check", "verify build",
    "run gate", "triad gate", "typecheck and test", "check tests and types",
    "precommit", "verification pipeline"
]

DEVICE_KEYWORDS = [
    "phone", "android", "sms", "text message", "notification",
    "device bridge", "mobile relay", "port 8766", "galaxy s26",
    "tap screen", "launch app on phone", "read notification", "send text"
]

MEMORY_KEYWORDS = [
    "what did i do on", "what was done", "past timeline", "recall",
    "search pieces", "pieces memory", "workstream summary", "historical log",
    "mem0 query", "what was worked on", "past work"
]

DOCTOR_KEYWORDS = [
    "doctor", "health", "system audit", "subsystem status",
    "check connections", "audit subscriptions", "verify platforms"
]

ARCHITECT_KEYWORDS = [
    "should we use", "should i use", "compare", "tradeoffs of",
    "architecture", "architectural", "system design", "pattern recommendation",
    "database schema", "scaling strategy", "evaluating approach", "pros and cons"
]

REVIEW_KEYWORDS = [
    "review this", "review diff", "code review", "critique changes",
    "spot bugs in", "audit diff", "check changes", "review my code"
]

DEBUG_KEYWORDS = [
    "why is this failing", "why did this fail", "debug this",
    "fix this error", "diagnose error", "fix crash", "how to solve this bug",
    "what does this error mean", "stack trace"
]

def is_high_stakes(text: str) -> bool:
    """Detect if prompt or context involves sensitive security/database/concurrency domains."""
    lowered = text.lower()
    return any(re.search(r"\b" + re.escape(kw) + r"\b", lowered) for kw in HIGH_STAKES_KEYWORDS)

def classify_intent(prompt: str, context: Optional[str] = None, diff: Optional[str] = None) -> IntentClassification:
    """
    Classifies raw developer input into a concrete Triad subsystem intent.
    Executes in <1ms with deterministic rule engines and zero external API calls.
    """
    combined_text = f"{prompt or ''}\n{context or ''}\n{diff or ''}".strip()
    lowered_prompt = (prompt or "").lower().strip()
    high_stakes = is_high_stakes(combined_text)

    # 1. Explicit / Embedded Git Diff Check
    has_diff = bool(diff and diff.strip()) or any(p.search(combined_text) for p in DIFF_PATTERNS)
    if has_diff:
        # If diff is paired with an explicit gate request, gate takes precedence
        if any(kw in lowered_prompt for kw in GATE_KEYWORDS):
            return IntentClassification(
                intent="GATE",
                confidence=0.98,
                reason="Pre-commit verification keywords detected alongside git diff",
                suggested_mode="gate",
                suggested_engine="competition" if high_stakes else "auto",
                high_stakes=high_stakes,
                metadata={"has_diff": True}
            )
        return IntentClassification(
            intent="REVIEW",
            confidence=0.97,
            reason="Unified git diff syntax detected in prompt or context",
            suggested_mode="review_diff",
            suggested_engine="competition" if high_stakes else "auto",
            high_stakes=high_stakes,
            metadata={"has_diff": True}
        )

    # 2. Stack Trace / Compiler Error Check
    has_stack_trace = any(p.search(combined_text) for p in STACK_TRACE_PATTERNS)
    if has_stack_trace or any(kw in lowered_prompt for kw in DEBUG_KEYWORDS):
        return IntentClassification(
            intent="DEBUG",
            confidence=0.96 if has_stack_trace else 0.88,
            reason="Runtime exception, compiler diagnostics, or debugging keywords detected",
            suggested_mode="debug",
            suggested_engine="competition" if high_stakes else "auto",
            high_stakes=high_stakes,
            metadata={"has_stack_trace": has_stack_trace}
        )

    # 3. Pre-Commit Gate / Verification Check
    if any(kw in lowered_prompt for kw in GATE_KEYWORDS):
        return IntentClassification(
            intent="GATE",
            confidence=0.95,
            reason="Ground-truth verification gate keywords detected",
            suggested_mode="gate",
            suggested_engine="competition" if high_stakes else "auto",
            high_stakes=high_stakes
        )

    # 4. Historical Memory & Workstream Recall Check
    if any(kw in lowered_prompt for kw in MEMORY_KEYWORDS):
        return IntentClassification(
            intent="MEMORY",
            confidence=0.93,
            reason="Historical timeline, workstream query, or memory recall keywords detected",
            suggested_mode="memory",
            suggested_engine="pieces",
            high_stakes=False
        )

    # 5. Mobile / Phone Device Automation Check
    if any(kw in lowered_prompt for kw in DEVICE_KEYWORDS):
        return IntentClassification(
            intent="DEVICE",
            confidence=0.92,
            reason="Mobile phone, SMS, or Android relay bridge keywords detected",
            suggested_mode="device",
            suggested_engine="hermes",
            high_stakes=False
        )

    # 6. Triad Doctor / Platform Health Check
    if any(kw in lowered_prompt for kw in DOCTOR_KEYWORDS):
        return IntentClassification(
            intent="DOCTOR",
            confidence=0.94,
            reason="System health, platform audit, or doctor keywords detected",
            suggested_mode="doctor",
            suggested_engine="auto",
            high_stakes=False
        )

    # 7. Code Review without Embedded Diff (e.g. asking to review working tree)
    if any(kw in lowered_prompt for kw in REVIEW_KEYWORDS):
        return IntentClassification(
            intent="REVIEW",
            confidence=0.86,
            reason="Code review requested (will extract current git diff)",
            suggested_mode="review_diff",
            suggested_engine="competition" if high_stakes else "auto",
            high_stakes=high_stakes,
            metadata={"needs_git_diff": True}
        )

    # 8. Architecture / System Design / Consult Check
    if any(kw in lowered_prompt for kw in ARCHITECT_KEYWORDS) or "?" in lowered_prompt:
        return IntentClassification(
            intent="ARCHITECT",
            confidence=0.88,
            reason="Architectural design inquiry or comparative decision dilemma detected",
            suggested_mode="architect",
            suggested_engine="competition" if high_stakes else "auto",
            high_stakes=high_stakes
        )

    # 9. General Fallback
    return IntentClassification(
        intent="GENERAL",
        confidence=0.70,
        reason="General development query routed to primary advisory council",
        suggested_mode="general",
        suggested_engine="auto",
        high_stakes=high_stakes
    )

def execute_intent(classification: IntentClassification, raw_prompt: str, args: Any = None) -> None:
    """
    Executes the action corresponding to the classified intent by delegating
    directly to the appropriate subsystem or command handler.
    """
    intent = classification.intent
    stakes_label = " [HIGH STAKES - DUAL ADVISOR ADJUDICATION]" if classification.high_stakes else ""
    print(f"\n[Triad Intent Engine]: {intent}{stakes_label}")
    print(f"  Confidence: {int(classification.confidence * 100)}% | Rationale: {classification.reason}")
    print(f"  Target Mode: {classification.suggested_mode} | Recommended Engine: {classification.suggested_engine}\n")

    # Import triad engine dispatchers lazily to avoid circular dependencies
    try:
        from triad import triad_engine
    except ImportError:
        import triad_engine

    if intent == "DOCTOR":
        triad_engine.cmd_doctor(args)
        return

    if intent == "GATE":
        # Pass competition flag if suggested or explicitly set
        if classification.suggested_engine == "competition" and hasattr(args, "competition"):
            args.competition = True
        triad_engine.cmd_gate(args)
        return

    if intent == "REVIEW":
        if not getattr(args, "prompt", None):
            setattr(args, "prompt", raw_prompt)
        if classification.suggested_engine == "competition":
            setattr(args, "competition", True)
        triad_engine.cmd_review(args)
        return

    if intent == "DEBUG":
        if not getattr(args, "error", None):
            setattr(args, "error", raw_prompt)
        if not getattr(args, "prompt", None):
            setattr(args, "prompt", raw_prompt)
        if classification.suggested_engine == "competition":
            setattr(args, "competition", True)
        triad_engine.cmd_debug(args)
        return

    if intent == "ARCHITECT" or intent == "GENERAL":
        if not getattr(args, "prompt", None):
            setattr(args, "prompt", raw_prompt)
        if classification.suggested_engine == "competition":
            setattr(args, "competition", True)
        triad_engine.cmd_consult(args)
        return

    if intent == "DEVICE":
        print("[Triad -> Hermes Android Bridge]:")
        bridge_alive = triad_engine.is_port_open("127.0.0.1", 8766)
        if not bridge_alive:
            print("❌ Android Relay port 8766 is STANDBY (Phone app com.hermesandroid.bridge not dialed in).")
            print("Ensure android_relay_runner.py is active in C:\\Users\\micha\\android-relay-env\\")
        else:
            print("✓ Android Relay port 8766 is ONLINE.")
        print(f"Forwarding device task to Hermes: {raw_prompt}")
        if triad_engine.HERMES_PATH.exists():
            cmd = [str(triad_engine.HERMES_PATH), "-p", raw_prompt]
            subprocess.run(cmd)
        else:
            print(f"Hermes binary not found at {triad_engine.HERMES_PATH}")
        return

    if intent == "MEMORY":
        print(f"[Triad -> Local Memory Hub]: Recalling context for '{raw_prompt}'...")
        mem0_script = Path(r"C:\Users\micha\.agents\skills\mem0\mem0.js")
        if mem0_script.exists():
            print("\n--- Mem0 Long-Term Memory Recall ---")
            subprocess.run(["node", str(mem0_script), "search", raw_prompt])
        print("\n--- PiecesOS Timeline Context ---")
        print(f"Querying PiecesOS on port 39300 for relevant events...")
        try:
            import urllib.request
            req = urllib.request.urlopen("http://127.0.0.1:39300/workstream_events", timeout=3)
            data = json.loads(req.read().decode("utf-8"))
            events = data.get("iterable", [])
            print(f"Found {len(events)} workstream events recorded in PiecesOS.")
        except Exception as e:
            print(f"PiecesOS query note: {e}")
        return
