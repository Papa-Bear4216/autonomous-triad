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
import subprocess
import tempfile
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

    def test_cmd_auto_with_worktree_flag(self):
        """Verify cmd_auto --worktree executes inside ephemeral worktree and cleans up."""
        import argparse
        import io
        from unittest.mock import patch
        from triad.triad_engine import cmd_auto

        args = argparse.Namespace(
            prompt=["doctor"],
            worktree=True,
            ref="HEAD",
            diff_file="",
            context="",
            competition=False,
            engine="mock",
            cached=False,
            head=False
        )

        with patch("sys.stdout", new=io.StringIO()):
            cmd_auto(args)

        current_worktrees = list_worktrees(REPO_ROOT)
        self.assertEqual(len(current_worktrees), self.initial_count)

    def test_cmd_gate_with_worktree_flag(self):
        """Verify cmd_gate --worktree executes pre-commit gate in ephemeral worktree and cleans up."""
        import argparse
        import io
        from unittest.mock import patch
        from triad.triad_engine import cmd_gate

        args = argparse.Namespace(
            worktree=True,
            ref="HEAD",
            engine="mock",
            competition=False,
            max_retries=0,
            timeout=30
        )

        def fake_tree_safe(cmd, *a, **kw):
            cmd_str = " ".join(cmd)
            if "diff" in cmd_str or "status" in cmd_str or "read-tree" in cmd_str:
                return (0, "", "")
            if "write-tree" in cmd_str or "rev-parse" in cmd_str:
                return (0, "tree_123\n", "")
            return (0, "Ran 5 tests in 0.1s\nOK", "")

        with patch("sys.stdout", new=io.StringIO()):
            with patch("triad.triad_engine.run_subprocess_tree_safe", side_effect=fake_tree_safe):
                with patch("triad.triad_engine._verify_checkout_representation", return_value=[]):
                    cmd_gate(args)

        current_worktrees = list_worktrees(REPO_ROOT)
        self.assertEqual(len(current_worktrees), self.initial_count)

    def test_provision_deleted_candidate_workspace_package_fails_closed(self):
        """Verify that when a workspace package is deleted in candidate, it is never linked to parent source."""
        from triad.worktree import provision_worktree_dependencies, deprovision_worktree_dependencies
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            repo_root.mkdir()
            wt_root = Path(td) / "wt"
            wt_root.mkdir()

            # Parent has packages/foo and packages/bar
            (repo_root / "packages" / "foo").mkdir(parents=True)
            (repo_root / "packages" / "foo" / "index.js").write_text("parent foo", encoding="utf-8")
            (repo_root / "packages" / "bar").mkdir(parents=True)
            (repo_root / "packages" / "bar" / "index.js").write_text("parent bar", encoding="utf-8")

            # Parent node_modules links to workspace packages
            (repo_root / "node_modules").mkdir()
            os.symlink(str(repo_root / "packages" / "foo"), str(repo_root / "node_modules" / "foo"), target_is_directory=True)
            os.symlink(str(repo_root / "packages" / "bar"), str(repo_root / "node_modules" / "bar"), target_is_directory=True)

            # Candidate worktree ONLY has packages/bar (packages/foo is deleted in candidate!)
            (wt_root / "packages" / "bar").mkdir(parents=True)
            (wt_root / "packages" / "bar" / "index.js").write_text("candidate bar", encoding="utf-8")

            provisioned = provision_worktree_dependencies(repo_root, wt_root)

            # wt/node_modules/bar should be retargeted to candidate packages/bar
            cand_bar_link = wt_root / "node_modules" / "bar"
            self.assertTrue(cand_bar_link.exists())
            self.assertEqual((cand_bar_link / "index.js").read_text(encoding="utf-8"), "candidate bar")

            # wt/node_modules/foo MUST NOT EXIST (fail closed on deleted workspace package!)
            cand_foo_link = wt_root / "node_modules" / "foo"
            self.assertFalse(cand_foo_link.exists(), "Deleted workspace package must never fall through to parent source!")

            # Deprovision safely
            deprovision_worktree_dependencies(wt_root)
            self.assertFalse(cand_bar_link.exists())

    def test_bin_provisioning_deleted_package_fails_closed(self):
        """Verify that .bin executables for deleted workspace packages are not provisioned into candidate."""
        from triad.worktree import provision_worktree_dependencies, deprovision_worktree_dependencies
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            repo_root.mkdir()
            wt_root = Path(td) / "wt"
            wt_root.mkdir()

            (repo_root / "packages" / "cli-tool").mkdir(parents=True)
            (repo_root / "packages" / "cli-tool" / "cli.js").write_text("console.log('hi')", encoding="utf-8")
            (repo_root / "node_modules" / ".bin").mkdir(parents=True)
            try:
                os.symlink(str(repo_root / "packages" / "cli-tool" / "cli.js"), str(repo_root / "node_modules" / ".bin" / "my-cli"))
            except OSError:
                self.skipTest("Symlinks not permitted in this environment")

            # Candidate does NOT have packages/cli-tool (deleted in candidate)
            provision_worktree_dependencies(repo_root, wt_root)

            # .bin/my-cli must NOT exist in candidate worktree
            cand_bin_cli = wt_root / "node_modules" / ".bin" / "my-cli"
            self.assertFalse(cand_bin_cli.exists(), "CLI wrapper for deleted workspace package must not be provisioned!")

            deprovision_worktree_dependencies(wt_root)

    def test_pnpm_layout_provisioning_order_and_external_manifest(self):
        """Verify .pnpm stores are provisioned first and manifest is stored strictly outside worktree checkout."""
        from triad.worktree import provision_worktree_dependencies, deprovision_worktree_dependencies, _get_provisioned_manifest_path
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            repo_root.mkdir()
            wt_root = Path(td) / "wt"
            wt_root.mkdir()

            parent_nm = repo_root / "node_modules"
            parent_nm.mkdir()

            # Set up .pnpm store with an unpacked package
            store_pkg = parent_nm / ".pnpm" / "fast-glob@3.0.0" / "node_modules" / "fast-glob"
            store_pkg.mkdir(parents=True)
            (store_pkg / "index.js").write_text("module.exports = 'fast-glob';", encoding="utf-8")
            (store_pkg / "cli.js").write_text("#!/usr/bin/env node\nconsole.log('fast');\n", encoding="utf-8")

            # Top-level symlink pointing into .pnpm store
            top_symlink = parent_nm / "fast-glob"
            try:
                os.symlink(str(store_pkg), str(top_symlink), target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks not permitted in this environment")

            # .bin symlink pointing into .pnpm store
            bin_dir = parent_nm / ".bin"
            bin_dir.mkdir()
            os.symlink(str(store_pkg / "cli.js"), str(bin_dir / "fast-glob"))

            prov = provision_worktree_dependencies(repo_root, wt_root)
            self.assertTrue(any("node_modules" in p for p in prov))

            # 1. Manifest must NOT exist inside the worktree checkout
            checkout_manifest = wt_root / ".triad_provisioned_manifest.json"
            self.assertFalse(checkout_manifest.exists(), "Manifest must NEVER be written to the worktree checkout tree!")

            # 2. Manifest file exists in external storage path
            ext_manifest = _get_provisioned_manifest_path(wt_root)
            self.assertTrue(ext_manifest.exists(), f"External manifest must exist at {ext_manifest}")

            # 3. Top-level fast-glob was successfully provisioned and resolves into candidate worktree
            wt_fast_glob = wt_root / "node_modules" / "fast-glob"
            self.assertTrue(wt_fast_glob.exists())
            self.assertEqual((wt_fast_glob / "index.js").read_text(encoding="utf-8"), "module.exports = 'fast-glob';")

            # 4. .bin/fast-glob was successfully provisioned
            wt_bin = wt_root / "node_modules" / ".bin" / "fast-glob"
            self.assertTrue(wt_bin.exists())

            # 5. Deprovision cleans up completely
            deprovision_worktree_dependencies(wt_root)
            self.assertFalse(wt_fast_glob.exists())
            self.assertFalse(ext_manifest.exists())

    def test_deprovision_untrusted_manifest_containment_and_rejection(self):
        """Verify deprovisioning rejects untrusted manifest paths escaping the worktree dependency folder."""
        import json
        from triad.worktree import deprovision_worktree_dependencies, _get_provisioned_manifest_path
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            repo_root.mkdir()
            wt_root = Path(td) / "wt"
            wt_root.mkdir()

            sensitive_file = repo_root / "critical_data.txt"
            sensitive_file.write_text("vital user content", encoding="utf-8")

            # Write forged manifest targeting the parent repo file
            manifest_file = _get_provisioned_manifest_path(wt_root)
            manifest_file.parent.mkdir(parents=True, exist_ok=True)
            forged_payload = {
                "version": 1,
                "worktree": str(wt_root.resolve()),
                "entries": [
                    str(sensitive_file.resolve()),
                    str(Path(td).resolve())
                ]
            }
            manifest_file.write_text(json.dumps(forged_payload), encoding="utf-8")

            # Run deprovisioning: must reject escaping entries
            deprovision_worktree_dependencies(wt_root)

            # Sensitive file MUST still exist intact!
            self.assertTrue(sensitive_file.exists())
            self.assertEqual(sensitive_file.read_text(encoding="utf-8"), "vital user content")

    def test_node_provisioning_to_gate_integration(self):
        """Verify provisioned dependencies pass pre-validation checks without untracked manifest errors."""
        from triad.worktree import provision_worktree_dependencies, deprovision_worktree_dependencies
        from triad.triad_engine import _check_no_uncommitted_source_dependencies, clean_git_env

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], check=True)

            (repo / "package.json").write_text('{"name": "test-pkg"}', encoding="utf-8")
            (repo / "index.js").write_text("console.log('hi');\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

            # Parent node_modules
            parent_nm = repo / "node_modules"
            parent_nm.mkdir()
            (parent_nm / "dep-pkg").mkdir()
            (parent_nm / "dep-pkg" / "index.js").write_text("dep content", encoding="utf-8")

            # Create worktree
            wt = Path(td) / "wt"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(wt), "HEAD"], check=True, capture_output=True)

            # Provision dependencies
            prov = provision_worktree_dependencies(repo, wt)
            self.assertTrue(len(prov) > 0)

            # Verify no untracked manifest in checkout
            self.assertFalse((wt / ".triad_provisioned_manifest.json").exists())

            # Run pre-validation source dependency check inside worktree: MUST PASS!
            exec_env = clean_git_env()
            _check_no_uncommitted_source_dependencies(wt, exec_env, in_worktree=True, stage_name="pre-validation")

            # Deprovision
            deprovision_worktree_dependencies(wt)
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
