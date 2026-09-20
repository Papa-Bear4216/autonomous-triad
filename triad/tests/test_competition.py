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

if __name__ == "__main__":
    unittest.main()
