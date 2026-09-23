"""Unit tests for Triad Intent Engine (intent_engine.py)."""

import sys
import unittest
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from triad.intent_engine import classify_intent, is_high_stakes, IntentClassification

class TestIntentEngine(unittest.TestCase):

    def test_classify_unified_diff(self):
        sample_diff = (
            "diff --git a/src/auth.ts b/src/auth.ts\n"
            "index abcdef1..1234567 100644\n"
            "--- a/src/auth.ts\n"
            "+++ b/src/auth.ts\n"
            "@@ -10,4 +10,5 @@\n"
            "+ const userToken = jwt.sign();\n"
        )
        res = classify_intent("Check these modifications", diff=sample_diff)
        self.assertEqual(res.intent, "REVIEW")
        self.assertGreaterEqual(res.confidence, 0.90)
        self.assertEqual(res.suggested_mode, "review_diff")
        self.assertTrue(res.high_stakes) # auth + jwt
        self.assertEqual(res.suggested_engine, "competition")

    def test_classify_stack_trace(self):
        err_msg = (
            "Traceback (most recent call last):\n"
            "  File \"main.py\", line 42, in <module>\n"
            "    res = process_payment(order)\n"
            "TypeError: Cannot read properties of undefined (reading 'amount')"
        )
        res = classify_intent(err_msg)
        self.assertEqual(res.intent, "DEBUG")
        self.assertGreaterEqual(res.confidence, 0.90)
        self.assertEqual(res.suggested_mode, "debug")

    def test_classify_gate(self):
        res = classify_intent("Run pre-commit verification before pushing")
        self.assertEqual(res.intent, "GATE")
        self.assertEqual(res.suggested_mode, "gate")
        self.assertGreaterEqual(res.confidence, 0.90)

    def test_classify_device(self):
        res = classify_intent("Send an SMS from my phone to check status")
        self.assertEqual(res.intent, "DEVICE")
        self.assertEqual(res.suggested_engine, "hermes")
        self.assertGreaterEqual(res.confidence, 0.90)

    def test_classify_memory(self):
        res = classify_intent("What did I do on the Pieces Android companion yesterday?")
        self.assertEqual(res.intent, "MEMORY")
        self.assertEqual(res.suggested_engine, "pieces")
        self.assertGreaterEqual(res.confidence, 0.85)

    def test_classify_doctor(self):
        res = classify_intent("triad doctor check system health and subscriptions")
        self.assertEqual(res.intent, "DOCTOR")
        self.assertEqual(res.suggested_mode, "doctor")

    def test_classify_architect_comparison(self):
        res = classify_intent("Should we use optimistic UI or server-confirmed state for this queue?")
        self.assertEqual(res.intent, "ARCHITECT")
        self.assertEqual(res.suggested_mode, "architect")

    def test_high_stakes_detection(self):
        self.assertTrue(is_high_stakes("Need to execute database migration with row level security"))
        self.assertTrue(is_high_stakes("Fixing race condition and deadlock in pool"))
        self.assertFalse(is_high_stakes("Change background color of button to blue"))

if __name__ == "__main__":
    unittest.main()
