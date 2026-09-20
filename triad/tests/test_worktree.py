#!/usr/bin/env python3
"""
Unit tests for Triad Git Worktree Isolation (triad/worktree.py).
Verifies:
- Ephemeral worktree creation from HEAD or specific commits
- File writes, modifications, and dirty working trees inside worktrees
- Safe removal under Windows with locked handles and read-only attributes
- Clean state verification via `git worktree list`
- Context manager automatic cleanup and exception handling
"""

import os
import stat
import unittest
from pathlib import Path
from triad.worktree import (
    create_worktree,
    remove_worktree,
    isolated_worktree,
    list_worktrees,
    get_repo_root,
    prune_worktrees,
)

REPO_ROOT = get_repo_root(Path(__file__).resolve())


class TestGitWorktreeIsolation(unittest.TestCase):
    def setUp(self):
        # Ensure any leftover test worktrees are pruned before each test
        prune_worktrees(REPO_ROOT)
        self.initial_worktrees = list_worktrees(REPO_ROOT)
        self.initial_count = len(self.initial_worktrees)

    def tearDown(self):
        # Clean up and verify worktree list returns to initial state
        prune_worktrees(REPO_ROOT)
        current_worktrees = list_worktrees(REPO_ROOT)
        self.assertEqual(
            len(current_worktrees),
            self.initial_count,
            f"TearDown detected unpruned worktrees: {current_worktrees}"
        )

    def test_create_write_and_remove_worktree(self):
        """Verify creating, writing files inside, and explicitly removing a worktree."""
        wt = create_worktree(REPO_ROOT, branch_or_commit="HEAD", prefix="triad-test-cwr")
        self.assertTrue(wt.exists(), f"Worktree directory {wt} was not created")

        # Verify git tracks the new worktree
        wts_after_create = list_worktrees(REPO_ROOT)
        self.assertEqual(len(wts_after_create), self.initial_count + 1)
        self.assertTrue(any(w["worktree"] == wt for w in wts_after_create))

        # Write inside the worktree (simulating agent code generation)
        sub_dir = wt / "generated_module"
        sub_dir.mkdir(parents=True, exist_ok=True)
        code_file = sub_dir / "service.py"
        code_file.write_text("def run_task():\n    return 'success'\n", encoding="utf-8")
        self.assertTrue(code_file.exists())

        # Remove the worktree
        removed = remove_worktree(wt, force=True, repo_path=REPO_ROOT)
        self.assertTrue(removed, "remove_worktree did not return True")
        self.assertFalse(wt.exists(), "Worktree directory still exists on disk")

        # Verify git worktree list is completely clean
        wts_after_remove = list_worktrees(REPO_ROOT)
        self.assertEqual(len(wts_after_remove), self.initial_count)
        self.assertFalse(any(w["worktree"] == wt for w in wts_after_remove))

    def test_isolated_worktree_context_manager(self):
        """Verify isolated_worktree context manager cleans up automatically on exit."""
        target_path = None
        with isolated_worktree(REPO_ROOT, prefix="triad-test-cm") as wt:
            target_path = wt
            self.assertTrue(wt.exists())

            # Verify worktree registered in git
            wts = list_worktrees(REPO_ROOT)
            self.assertEqual(len(wts), self.initial_count + 1)

            # Create dirty uncommitted state
            (wt / "scratch.txt").write_text("uncommitted edits", encoding="utf-8")

        # After exiting context block, directory and git registration must be gone
        self.assertFalse(target_path.exists())
        wts_final = list_worktrees(REPO_ROOT)
        self.assertEqual(len(wts_final), self.initial_count)

    def test_isolated_worktree_with_exception_cleanup(self):
        """Verify isolated_worktree cleans up even if an exception is raised inside the block."""
        target_path = None
        with self.assertRaises(RuntimeError):
            with isolated_worktree(REPO_ROOT, prefix="triad-test-err") as wt:
                target_path = wt
                (wt / "broken.py").write_text("raise Exception()", encoding="utf-8")
                raise RuntimeError("Simulated agent pipeline failure")

        self.assertFalse(target_path.exists())
        self.assertEqual(len(list_worktrees(REPO_ROOT)), self.initial_count)

    def test_isolated_worktree_keep_worktree(self):
        """Verify keep_worktree=True preserves the worktree directory on exit."""
        target_path = None
        with isolated_worktree(REPO_ROOT, prefix="triad-test-keep", keep_worktree=True) as wt:
            target_path = wt
            (wt / "kept.txt").write_text("preserve me", encoding="utf-8")

        # Worktree should still exist because keep_worktree was True
        self.assertTrue(target_path.exists())
        self.assertEqual(len(list_worktrees(REPO_ROOT)), self.initial_count + 1)

        # Explicit manual cleanup
        remove_worktree(target_path, force=True, repo_path=REPO_ROOT)
        self.assertFalse(target_path.exists())

    def test_isolated_worktree_cd_mode(self):
        """Verify isolated_worktree with cd=True switches CWD and restores it without locking."""
        original_cwd = Path.cwd().resolve()
        target_path = None

        with isolated_worktree(REPO_ROOT, prefix="triad-test-cd", cd=True) as wt:
            target_path = wt
            current_cwd = Path.cwd().resolve()
            self.assertEqual(current_cwd, wt.resolve())

            # Perform file writes relative to CWD
            Path("relative_file.txt").write_text("written in worktree", encoding="utf-8")

        # Verify CWD restored and worktree deleted cleanly
        self.assertEqual(Path.cwd().resolve(), original_cwd)
        self.assertFalse(target_path.exists())

    def test_remove_worktree_with_readonly_files(self):
        """Verify remove_worktree handles Windows read-only file attributes cleanly."""
        wt = create_worktree(REPO_ROOT, prefix="triad-test-ro")
        ro_file = wt / "locked_file.txt"
        ro_file.write_text("read-only content", encoding="utf-8")

        # Set read-only attribute on Windows
        os.chmod(ro_file, stat.S_IREAD)

        # Removal must still succeed without PermissionError
        removed = remove_worktree(wt, force=True, repo_path=REPO_ROOT)
        self.assertTrue(removed)
        self.assertFalse(wt.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
