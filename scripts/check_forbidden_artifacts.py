from __future__ import annotations

import sys
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def is_forbidden(path: Path) -> bool:
    path_str = str(path)
    if path.name == ".DS_Store":
        return True
    if path.suffix in {".pyc", ".pyo"}:
        return True
    forbidden_parts = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "target"}
    if any(part in forbidden_parts for part in path.parts):
        return True
    if "bin" in path.parts and "java-kgraph" in path.parts:
        return True
    if any(part.endswith(".egg-info") for part in path.parts):
        return True
    return False


def run(paths: list[str]) -> int:
    candidates = [Path(p) for p in paths if p]
    explicit_paths = bool(candidates)
    using_git_tracked_files = False
    if not candidates:
        git_files = git_tracked_files()
        if git_files:
            candidates = git_files
            using_git_tracked_files = True
        else:
            candidates = [p for p in ROOT.rglob("*") if p.is_file()]

    ignored_roots = {".git", ".venv", "venv", "node_modules", ".cache", ".pytest_cache", "__pycache__"}
    if not using_git_tracked_files and not explicit_paths:
        ignored_roots = ignored_roots | {"target", "bin"}

    forbidden = []
    for path in candidates:
        resolved = path if path.is_absolute() else (ROOT / path)
        if not resolved.exists() or not resolved.is_file():
            continue
        rel = resolved.relative_to(ROOT)
        if any(part in ignored_roots for part in rel.parts):
            continue
        if is_forbidden(rel):
            forbidden.append(str(rel))

    if forbidden:
        print("[forbidden-artifacts] FAILED")
        for item in sorted(set(forbidden)):
            print(f"- {item}")
        return 1

    print("[forbidden-artifacts] PASS")
    return 0


def git_tracked_files() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    files: list[Path] = []
    for line in output.stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        files.append(ROOT / rel)
    return files


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
