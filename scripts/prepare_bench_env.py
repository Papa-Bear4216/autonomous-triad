#!/usr/bin/env python3
"""Pin a local, checkable environment for the 30-instance SWE-bench slice.

Clones astropy and django, confirms every base commit is present, and writes
triad/bench/.cache/ENV_READY.json. Does not query advisors and does not run tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTANCES = REPO_ROOT / "triad" / "bench" / "swebench_instances.json"
CACHE = REPO_ROOT / "triad" / "bench" / ".cache"
REPOS = CACHE / "repos"
READY = CACHE / "ENV_READY.json"

REMOTE = {
    "astropy/astropy": "https://github.com/astropy/astropy.git",
    "django/django": "https://github.com/django/django.git",
}


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=127,
            stdout="",
            stderr=str(exc),
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_repo(name: str, url: str) -> Path:
    dest = REPOS / (name.split("/")[-1] + ".git")
    if not (dest / "HEAD").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"cloning {name} -> {dest}")
        result = run(["git", "clone", "--bare", "--filter=blob:none", url, str(dest)])
        if result.returncode != 0:
            raise SystemExit(result.stderr.strip() or f"clone failed for {name}")
    return dest


def ensure_commit(repo_dir: Path, commit: str) -> str:
    probe = run(["git", "cat-file", "-t", commit], cwd=repo_dir)
    if probe.returncode == 0 and probe.stdout.strip() == "commit":
        return "present"
    print(f"fetching {commit[:12]} into {repo_dir.name}")
    fetched = run(["git", "fetch", "--filter=blob:none", "origin", commit], cwd=repo_dir)
    if fetched.returncode != 0:
        raise SystemExit(fetched.stderr.strip() or f"fetch failed for {commit}")
    probe = run(["git", "cat-file", "-t", commit], cwd=repo_dir)
    if probe.returncode != 0 or probe.stdout.strip() != "commit":
        raise SystemExit(f"commit {commit} still missing in {repo_dir}")
    return "fetched"


def python311() -> str:
    found = run(["uv", "python", "find", "3.11"])
    if found.returncode == 0 and found.stdout.strip():
        return found.stdout.strip()
    print("installing CPython 3.11 via uv")
    installed = run(["uv", "python", "install", "3.11"])
    if installed.returncode != 0:
        raise SystemExit(installed.stderr.strip() or "uv python install 3.11 failed")
    found = run(["uv", "python", "find", "3.11"])
    if found.returncode != 0 or not found.stdout.strip():
        raise SystemExit("Python 3.11 was installed but uv cannot find it")
    return found.stdout.strip()


def main() -> None:
    # Invalidate any existing readiness artifact immediately so a failure never leaves a stale READY status
    if READY.exists():
        try:
            READY.unlink()
        except OSError:
            pass

    if not INSTANCES.exists():
        raise SystemExit(f"missing dataset: {INSTANCES}")
    instances = json.loads(INSTANCES.read_text(encoding="utf-8"))
    dataset_hash = sha256_file(INSTANCES)

    by_repo: dict[str, list[str]] = {}
    for item in instances:
        by_repo.setdefault(item["repo"], []).append(item["base_commit"])

    commit_status = []
    for repo_name, commits in by_repo.items():
        repo_dir = ensure_repo(repo_name, REMOTE[repo_name])
        for commit in commits:
            state = ensure_commit(repo_dir, commit)
            commit_status.append({"repo": repo_name, "base_commit": commit, "state": state})

    py311 = python311()
    docker_probe = run(["docker", "info"])
    docker_status = "running" if docker_probe.returncode == 0 else "not running"

    report = {
        "status": "READY",
        "tests_started": False,
        "prepared_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": str(INSTANCES),
        "dataset_sha256": dataset_hash,
        "instance_count": len(instances),
        "repos": {name: str(REPOS / (name.split("/")[-1] + ".git")) for name in by_repo},
        "commits_verified": len(commit_status),
        "python311": py311,
        "git": run(["git", "--version"]).stdout.strip(),
        "uv": run(["uv", "--version"]).stdout.strip(),
        "docker": docker_status,
        "note": "Checkouts are pinned. No advisor calls and no tests have been run.",
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp_ready = READY.with_suffix(f".tmp.{os.getpid()}")
    try:
        tmp_ready.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp_ready), str(READY))
    except Exception:
        if tmp_ready.exists():
            try:
                tmp_ready.unlink()
            except OSError:
                pass
        raise
    print(json.dumps({k: report[k] for k in ("status", "instance_count", "commits_verified", "dataset_sha256", "python311")}, indent=2))
    print(f"wrote {READY}")


if __name__ == "__main__":
    main()
