"""Unit tests for Competition Mode and structured synthesis."""

import sys
import unittest
import json
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from triad.competition import build_synthesis_prompt, query_competition_council, COUNCIL_SESSIONS_LOG

class TestCompetitionMode(unittest.TestCase):
    def test_build_synthesis_prompt_structure(self):
        prompt = "Review this diff"
        c1 = "Looks good, no issues found."
        c2 = "Found potential null pointer on line 12."
        diff = "+ val = user.profile.name"
        
        synth = build_synthesis_prompt(prompt, c1, c2, diff=diff)
        self.assertIn("### 1. Points of Unanimous Agreement", synth)
        self.assertIn("### 2. Points Raised by Only One Advisor", synth)
        self.assertIn("### 3. Direct Contradictions", synth)
        self.assertIn("### 4. Final Adjudicated Verdict & Action Plan", synth)
        self.assertIn("ADVISOR 1 (Claude Code) REVIEW", synth)
        self.assertIn("ADVISOR 2 (OpenAI Codex) REVIEW", synth)

    def test_query_competition_council_mock(self):
        # Run competition with mock advisor for fast deterministic unit test
        res = query_competition_council(
            prompt="Is this diff valid?",
            diff="+ console.log('hello');",
            advisor_names=("mock", "mock")
        )
        self.assertIn("synthesis", res)
        self.assertIn("responses", res)
        self.assertEqual(res["advisors"], ["mock", "mock"])
        self.assertTrue(COUNCIL_SESSIONS_LOG.exists())

    def test_query_gate_fix_competition(self):
        from triad.triad_engine import query_gate_fix
        class Args:
            competition = True
            engine = "mock"
            timeout = 30
        
        fix = query_gate_fix("SyntaxError on line 5", Args())
        self.assertIsInstance(fix, str)
        self.assertTrue(len(fix) > 0)

    def test_advisor_skill_competition(self):
        import importlib.util
        advisor_path = REPO_ROOT / "skills" / "claude-advisor" / "advisor.py"
        spec = importlib.util.spec_from_file_location("advisor", str(advisor_path))
        advisor_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(advisor_mod)

        res = advisor_mod.query_advisor(
            "Evaluate architectural approach",
            mode="architect",
            engine="mock",
            competition=True,
            timeout=30
        )
        self.assertIsInstance(res, str)
        self.assertIn("Mock Advisor", res)

    def test_competition_gate_verdict_parsing(self):
        import re
        # Synthetic approval response under section 4
        approved_resp = (
            "### 1. Points of Unanimous Agreement\nBoth approved.\n\n"
            "### 4. Final Adjudicated Verdict & Action Plan\n"
            "VERDICT: APPROVED. The diff is sound and ready for commit."
        )
        is_rejected = bool(re.search(r"\bVERDICT:\s*REJECTED\b", approved_resp, re.IGNORECASE))
        is_approved = bool(re.search(r"\bVERDICT:\s*APPROVED\b", approved_resp, re.IGNORECASE))
        self.assertFalse(is_rejected)
        self.assertTrue(is_approved)

        # Synthetic rejection response taking precedence
        rejected_resp = (
            "### 1. Points of Unanimous Agreement\nFound bug.\n\n"
            "### 4. Final Adjudicated Verdict & Action Plan\n"
            "VERDICT: REJECTED. Found fatal race condition."
        )
        is_rejected = bool(re.search(r"\bVERDICT:\s*REJECTED\b", rejected_resp, re.IGNORECASE))
        self.assertTrue(is_rejected)

if __name__ == "__main__":
    unittest.main()
