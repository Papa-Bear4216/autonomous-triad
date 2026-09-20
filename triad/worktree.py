#!/usr/bin/env python3
"""
Autonomous Multi-Agent Triad: Git Worktree Isolation (worktree.py).
Provides high-reliability ephemeral git worktree lifecycle management on Windows:
- create_worktree: allocates an isolated worktree directory from any commit or branch
- remove_worktree: cleans up worktree files, clears Windows read-only locks, and prunes git metadata
- isolated_worktree: safe context manager ensuring automatic rollback & cleanup
"""

import sys
import os
import stat
import shutil
import subprocess
import tempfile
import uuid
import time
import gc
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Union, List, Dict, Any, Generator


def _remove_readonly(func, path, exc_info):
    """Clear Windows read-only attribute and retry deletion."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def get_repo_root(path: Union[str, Path] = ".") -> Path:
    """Resolve the root directory of the enclosing git repository."""
    p = Path(path).resolve()
    target_dir = p.parent if p.is_file() else p
    cmd = ["git", "-C", str(target_dir), "rev-parse", "--show-toplevel"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise ValueError(f"'{path}' is not inside a valid git repository: {res.stderr.strip()}")
    return Path(res.stdout.strip()).resolve()


def list_worktrees(repo_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """
    List all worktrees registered in the git repository using porcelain output.
    Returns list of dicts:
      [{'worktree': Path, 'head': str, 'branch': str, 'detached': bool, 'bare': bool, 'prunable': bool}, ...]
    """
    repo_path = Path(repo_path).resolve() if repo_path else get_repo_root(".")
    cmd = ["git", "-C", str(repo_path), "worktree", "list", "--porcelain"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"git worktree list failed: {res.stderr.strip()}")

    worktrees = []
    current: Dict[str, Any] = {}

    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            if current and "worktree" in current:
                worktrees.append(current)
                current = {}
            continue

        if line.startswith("worktree "):
            wt_path = line[len("worktree "):].strip()
            current["worktree"] = Path(wt_path).resolve()
            current["detached"] = False
            current["bare"] = False
            current["prunable"] = False
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].strip()
        elif line == "detached":
            current["detached"] = True
        elif line == "bare":
            current["bare"] = True
        elif line.startswith("prunable"):
            current["prunable"] = True

    if current and "worktree" in current:
        worktrees.append(current)

    return worktrees


def prune_worktrees(repo_path: Optional[Union[str, Path]] = None) -> None:
    """Prune stale administrative worktree metadata."""
    target = Path(repo_path).resolve() if repo_path else get_repo_root(".")
    subprocess.run(
        ["git", "-C", str(target), "worktree", "prune"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )


def _discover_repo_from_worktree(worktree_path: Path) -> Optional[Path]:
    """Inspect .git file in worktree to locate main repository root."""
    git_file = worktree_path / ".git"
    if not git_file.exists() or not git_file.is_file():
        return None

    try:
        content = git_file.read_text(encoding="utf-8", errors="replace").strip()
        if content.startswith("gitdir:"):
            gitdir = content[len("gitdir:"):].strip()
            gitdir_path = Path(gitdir).resolve()
            # Standard path: <repo_root>/.git/worktrees/<name>
            if gitdir_path.parent.name == "worktrees" and gitdir_path.parent.parent.name == ".git":
                return gitdir_path.parent.parent.parent
            # Alternative: <repo_root>/.git/...
            for parent in gitdir_path.parents:
                if (parent / ".git").is_dir() or (parent / "HEAD").is_file():
                    return parent
    except Exception:
        pass

    return None


def create_worktree(
    repo_path: Union[str, Path],
    branch_or_commit: str = "HEAD",
    prefix: str = "triad-work",
    target_path: Optional[Union[str, Path]] = None,
    detach: bool = True
) -> Path:
    """
    Create a new isolated git worktree.
    
    Args:
        repo_path: Path to the root of the source git repository.
        branch_or_commit: Git commit SHA, branch name, or tag (default 'HEAD').
        prefix: Prefix for generated temporary worktree directory name.
        target_path: Optional explicit target directory path.
        detach: If True, checks out as detached HEAD to prevent branch collision.
        
    Returns:
        Path: Resolved absolute path to the newly created worktree.
    """
    root = get_repo_root(repo_path)

    if target_path:
        wt_path = Path(target_path).resolve()
    else:
        unique_name = f"{prefix}-{uuid.uuid4().hex[:8]}"
        wt_path = Path(tempfile.gettempdir()) / unique_name

    cmd = ["git", "-C", str(root), "worktree", "add"]
    if detach:
        cmd.append("--detach")
    cmd.extend([str(wt_path), str(branch_or_commit)])

    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"Failed to create git worktree at '{wt_path}': {res.stderr.strip() or res.stdout.strip()}")

    return wt_path.resolve()


def remove_worktree(
    worktree_path: Union[str, Path],
    force: bool = True,
    repo_path: Optional[Union[str, Path]] = None,
    retries: int = 5,
    retry_delay: float = 0.2
) -> bool:
    """
    Safely remove a git worktree and clean up all metadata, handling Windows file locks.
    
    Args:
        worktree_path: Path to the worktree to remove.
        force: Force removal even if there are uncommitted modifications.
        repo_path: Path to the main git repo. If None, attempts auto-discovery.
        retries: Number of deletion retries for locked files on Windows.
        retry_delay: Delay in seconds between retries.
        
    Returns:
        bool: True if worktree was successfully removed and unlinked.
    """
    wt_path = Path(worktree_path).resolve()

    # Determine main repository path
    main_repo = Path(repo_path).resolve() if repo_path else _discover_repo_from_worktree(wt_path)
    if not main_repo:
        try:
            main_repo = get_repo_root(".")
        except Exception:
            main_repo = None

    # Protect against locked CWD on Windows
    try:
        current_cwd = Path.cwd().resolve()
        if current_cwd == wt_path or wt_path in current_cwd.parents:
            safe_cwd = main_repo if (main_repo and main_repo.exists()) else Path(tempfile.gettempdir())
            os.chdir(safe_cwd)
    except Exception:
        pass

    # Collect garbage to release any unclosed file handles in Python
    gc.collect()

    # Execute git worktree remove
    if main_repo and main_repo.exists():
        cmd = ["git", "-C", str(main_repo), "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(wt_path))
        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    # If directory still persists on disk, recursively delete with read-only handler
    if wt_path.exists():
        for attempt in range(retries):
            try:
                gc.collect()
                shutil.rmtree(wt_path, onerror=_remove_readonly)
                break
            except Exception:
                if attempt < retries - 1:
                    time.sleep(retry_delay * (attempt + 1))

    # Prune git internal worktree tracking
    if main_repo and main_repo.exists():
        prune_worktrees(main_repo)

    return not wt_path.exists()


@contextmanager
def isolated_worktree(
    repo_path: Union[str, Path],
    branch_or_commit: str = "HEAD",
    prefix: str = "triad-work",
    keep_worktree: bool = False,
    cd: bool = False,
    **kwargs
) -> Generator[Path, None, None]:
    """
    Context manager creating an ephemeral git worktree, guaranteed to clean up on exit.
    
    Args:
        repo_path: Root of the source git repository.
        branch_or_commit: Commit SHA, branch, or tag to branch from (default 'HEAD').
        prefix: Directory name prefix.
        keep_worktree: If True, preserves the worktree directory and git linkage on exit.
        cd: If True, temporarily switches current working directory to worktree.
    
    Yields:
        Path: The isolated worktree directory path.
    """
    root = get_repo_root(repo_path)
    wt_path = create_worktree(root, branch_or_commit=branch_or_commit, prefix=prefix, **kwargs)

    old_cwd = None
    if cd:
        old_cwd = Path.cwd()
        os.chdir(wt_path)

    try:
        yield wt_path
    finally:
        if old_cwd:
            try:
                os.chdir(old_cwd)
            except Exception:
                pass

        if not keep_worktree:
            remove_worktree(wt_path, force=True, repo_path=root)
