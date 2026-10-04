#!/usr/bin/env python3
"""Unit tests for diff bloat stripping, marker anchoring, idempotency, and code/doc classification."""

import unittest

from triad.procutil import (
    strip_diff_bloat,
    is_doc_or_asset_file,
    clean_git_env,
    LOCKFILE_NAMES,
    MINIFIED_EXTENSIONS,
    BINARY_ASSET_EXTENSIONS,
    DOC_EXTENSIONS,
    ASSET_EXTENSIONS,
)
from triad.triad_engine import _affects_typescript, _affects_code


class TestDiffBloatStripper(unittest.TestCase):
    def test_constants_defined(self):
        self.assertIn("uv.lock", LOCKFILE_NAMES)
        self.assertIn("bun.lockb", LOCKFILE_NAMES)
        self.assertIn("go.sum", LOCKFILE_NAMES)
        self.assertIn(".min.js", MINIFIED_EXTENSIONS)
        self.assertIn(".png", BINARY_ASSET_EXTENSIONS)
        self.assertIn(".md", DOC_EXTENSIONS)
        self.assertIn(".pdf", ASSET_EXTENSIONS)

    def test_clean_git_env_exported_and_functional(self):
        env = clean_git_env({"FOO": "BAR"})
        self.assertIsInstance(env, dict)
        self.assertEqual(env.get("FOO"), "BAR")

    def test_empty_or_none_diff(self):
        self.assertEqual(strip_diff_bloat(""), "")
        self.assertEqual(strip_diff_bloat(None), "")
        self.assertEqual(strip_diff_bloat("   \n\t  "), "")

    def test_preserves_normal_code_diff(self):
        normal_diff = (
            "diff --git a/triad/procutil.py b/triad/procutil.py\n"
            "index 1234567..89abcdef 100644\n"
            "--- a/triad/procutil.py\n"
            "+++ b/triad/procutil.py\n"
            "@@ -10,3 +10,4 @@\n"
            " def existing():\n"
            "+def new_function():\n"
            "+    return 42\n"
        )
        result = strip_diff_bloat(normal_diff)
        self.assertIn("def new_function():", result)
        self.assertIn("def existing():", result)
        self.assertNotIn("[Diff omitted", result)

    def test_strips_lockfile_diff(self):
        lockfile_diff = (
            "diff --git a/uv.lock b/uv.lock\n"
            "index 1111111..2222222 100644\n"
            "--- a/uv.lock\n"
            "+++ b/uv.lock\n"
            "@@ -50,6 +50,7 @@\n"
            "+[[package]]\n"
            '+name = "pytest-xdist"\n'
            '+version = "3.8.0"\n'
            '+dependencies = [\n'
            '+    { name = "execnet" },\n'
            "+]\n"
        )
        result = strip_diff_bloat(lockfile_diff)
        self.assertIn("diff --git a/uv.lock b/uv.lock", result)
        self.assertIn("+++ b/uv.lock", result)
        self.assertIn("[Diff omitted: lockfile update (7 lines omitted to preserve LLM context)]", result)
        self.assertNotIn('name = "pytest-xdist"', result)

    def test_strips_minified_file_diff(self):
        min_diff = (
            "diff --git a/dist/bundle.min.js b/dist/bundle.min.js\n"
            "index aaaaaaa..bbbbbbb 100644\n"
            "--- a/dist/bundle.min.js\n"
            "+++ b/dist/bundle.min.js\n"
            "@@ -1,1 +1,1 @@\n"
            "-var a=1;\n"
            "+var a=2;\n"
        )
        result = strip_diff_bloat(min_diff)
        self.assertIn("diff --git a/dist/bundle.min.js b/dist/bundle.min.js", result)
        self.assertIn("[Diff omitted: minified / generated asset (3 lines omitted to preserve LLM context)]", result)
        self.assertNotIn("var a=2;", result)

    def test_strips_binary_diff(self):
        bin_diff = (
            "diff --git a/assets/logo.png b/assets/logo.png\n"
            "index 0000000..1111111 100644\n"
            "Binary files a/assets/logo.png and b/assets/logo.png differ\n"
            "diff-raw-bytes-here\n"
        )
        result = strip_diff_bloat(bin_diff)
        self.assertIn("diff --git a/assets/logo.png b/assets/logo.png", result)
        self.assertIn("[Diff omitted: binary / asset file", result)

    def test_code_mentioning_binary_or_markers_is_not_treated_as_binary(self):
        code_diff = (
            "diff --git a/src/checker.py b/src/checker.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/checker.py\n"
            "+++ b/src/checker.py\n"
            "@@ -1,2 +1,4 @@\n"
            " def check():\n"
            '+    pattern = "Binary files a/foo and b/foo differ"\n'
            '+    comment = "[Diff omitted: lockfile update]"\n'
            '+    truncated = "[... 10 lines truncated to protect LLM context ...]"\n'
        )
        result = strip_diff_bloat(code_diff)
        self.assertIn('pattern = "Binary files', result)
        self.assertIn('comment = "[Diff omitted', result)
        self.assertNotIn("lines omitted to preserve LLM context", result)

    def test_paths_with_spaces_and_quotes(self):
        diff_with_spaces = (
            'diff --git "a/path with space/file.min.js" "b/path with space/file.min.js"\n'
            'index 111..222 100644\n'
            '--- "a/path with space/file.min.js"\n'
            '+++ "b/path with space/file.min.js"\n'
            "@@ -1 +1 @@\n"
            "-foo\n"
            "+bar\n"
        )
        result = strip_diff_bloat(diff_with_spaces)
        self.assertIn("[Diff omitted: minified / generated asset", result)

    def test_truncates_huge_file_diff_and_keeps_specified_limit(self):
        large_hunk = "\n".join(f"+line_{i} = {i}" for i in range(120))
        huge_diff = (
            "diff --git a/src/big.py b/src/big.py\n"
            "index 111..222 100644\n"
            "--- a/src/big.py\n"
            "+++ b/src/big.py\n"
            "@@ -1,1 +1,120 @@\n"
            f"{large_hunk}\n"
        )
        result = strip_diff_bloat(huge_diff, max_lines_per_file=50)
        self.assertIn("+line_0 = 0", result)
        self.assertIn("+line_48 = 48", result)
        self.assertNotIn("+line_49 = 49", result)
        self.assertIn("[... 71 lines truncated to protect LLM context ...]", result)

    def test_multi_chunk_strict_idempotency(self):
        multi_diff = (
            "diff --git a/uv.lock b/uv.lock\n"
            "index 1111111..2222222 100644\n"
            "--- a/uv.lock\n"
            "+++ b/uv.lock\n"
            "@@ -50,6 +50,7 @@\n"
            "+[[package]]\n"
            '+name = "pytest-xdist"\n'
            "diff --git a/src/app.py b/src/app.py\n"
            "index 3333333..4444444 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,2 +1,3 @@\n"
            "+print('hello')\n"
            "diff --git a/assets/icon.png b/assets/icon.png\n"
            "Binary files a/assets/icon.png and b/assets/icon.png differ\n"
        )
        once = strip_diff_bloat(multi_diff)
        twice = strip_diff_bloat(once)
        thrice = strip_diff_bloat(twice)
        self.assertEqual(once, twice)
        self.assertEqual(twice, thrice)


class TestDocOrAssetClassification(unittest.TestCase):
    def test_recognizes_docs(self):
        self.assertTrue(is_doc_or_asset_file("README.md"))
        self.assertTrue(is_doc_or_asset_file("docs/architecture.md"))
        self.assertTrue(is_doc_or_asset_file("docs/guide.txt"))
        self.assertTrue(is_doc_or_asset_file("CHANGELOG.md"))
        self.assertTrue(is_doc_or_asset_file("LICENSE"))
        self.assertTrue(is_doc_or_asset_file(".gitignore"))

    def test_recognizes_assets(self):
        self.assertTrue(is_doc_or_asset_file("assets/image.png"))
        self.assertTrue(is_doc_or_asset_file("static/icons/app.ico"))
        self.assertTrue(is_doc_or_asset_file("diagram.pdf"))

    def test_rejects_code_and_config_files(self):
        self.assertFalse(is_doc_or_asset_file("triad/triad_engine.py"))
        self.assertFalse(is_doc_or_asset_file("src/components/App.tsx"))
        self.assertFalse(is_doc_or_asset_file("package.json"))
        self.assertFalse(is_doc_or_asset_file("pyproject.toml"))
        self.assertFalse(is_doc_or_asset_file("tsconfig.json"))
        self.assertFalse(is_doc_or_asset_file("requirements.txt"))
        self.assertFalse(is_doc_or_asset_file("requirements-dev.txt"))
        self.assertFalse(is_doc_or_asset_file("CMakeLists.txt"))
        self.assertFalse(is_doc_or_asset_file("docs/conf.py"))
        self.assertFalse(is_doc_or_asset_file("docs/schema.json"))
        self.assertFalse(is_doc_or_asset_file("tests/fixtures/data.txt"))
        self.assertFalse(is_doc_or_asset_file("bench/cases/case_001/prompt.txt"))

    def test_affects_code(self):
        self.assertFalse(_affects_code(["README.md", "docs/architecture.md", "LICENSE"]))
        self.assertTrue(_affects_code(["README.md", "requirements.txt"]))
        self.assertTrue(_affects_code(["docs/conf.py"]))
        self.assertTrue(_affects_code(["triad/procutil.py"]))

    def test_affects_typescript(self):
        self.assertTrue(_affects_typescript(["src/index.ts"]))
        self.assertTrue(_affects_typescript(["src/App.tsx"]))
        self.assertTrue(_affects_typescript(["src/App.vue"]))
        self.assertTrue(_affects_typescript(["src/App.svelte"]))
        self.assertTrue(_affects_typescript(["src/types/index.d.ts"]))
        self.assertTrue(_affects_typescript(["tsconfig.app.json"]))
        self.assertTrue(_affects_typescript(["tsconfig.node.json"]))
        self.assertTrue(_affects_typescript(["package.json"]))
        self.assertTrue(_affects_typescript(["bun.lockb"]))
        self.assertFalse(_affects_typescript(["README.md"]))
        self.assertFalse(_affects_typescript(["triad/triad_engine.py"]))
        self.assertFalse(_affects_typescript(["pyproject.toml"]))


if __name__ == "__main__":
    unittest.main()
