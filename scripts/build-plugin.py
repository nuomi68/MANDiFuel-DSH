#!/usr/bin/env python3
"""Build a Linux MANDiFuel Skill plugin artifact from a clean Git worktree or an explicit source snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

SKILLS = frozenset(
    {
        "conduct-offbeat-study",
        "execute-offbeat-case",
        "extract-offbeat-results",
        "orchestrate-offbeat-study",
        "prepare-offbeat-case",
    }
)
RELEASE_FILES = frozenset(
    {
        "mandifuel.json",
        "LICENSE",
        "NOTICE",
        "THIRD_PARTY_NOTICES.md",
        "CONTRIBUTING.md",
        "requirements-examples.txt",
        "scripts/build-plugin.py",
        "scripts/package-source.py",
        "CHANGELOG.md",
        "README.md",
        "STUDY_PROTOCOL.md",
        "configs/launcher.env.example",
        "scripts/prepare-agent.sh",
        "scripts/resolve-node.sh",
        "scripts/start-dsh.sh",
    }
)
# Release modes are product metadata, not worktree metadata. DrvFS commonly reports every
# file as executable, so carrying either its mode or a first Git-add mode into the artifact is
# not reproducible. Only the public shell entry points need an executable bit.
EXECUTABLE_RELEASE_FILES = frozenset(
    {
        "scripts/prepare-agent.sh",
        "scripts/resolve-node.sh",
        "scripts/start-dsh.sh",
    }
)
RELEASE_PREFIXES = (
    "dsh/",
    "lib/mandifuel_prepare/",
    "lib/mandifuel_run/",
    "rag/",
    "skills/",
)
DEVELOPMENT_ONLY_FILES = frozenset(
    {
        "rag/audit_case_cards.py",
        "rag/rebuild_case_cards.py",
    }
)


class BuildError(RuntimeError):
    """Raised when a release invariant is not satisfied."""


def _run(arguments: list[str], root: Path) -> str:
    completed = subprocess.run(
        arguments,
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise BuildError(
            f"command failed ({arguments[0]}): {completed.stderr.strip() or completed.returncode}"
        )
    return completed.stdout


def _git(root: Path, *arguments: str) -> str:
    return _run(["git", *arguments], root)


def _version(root: Path) -> str:
    path = root / "mandifuel.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    version = manifest.get("version", "")
    if (manifest.get("name") != "mandifuel" or manifest.get("runtime") != "deepseek-dsh"
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z]+\.[0-9]+)?", version)):
        raise BuildError("DSH product metadata is invalid")
    return version


def _release_sources(root: Path, snapshot: bool = False) -> list[str]:
    example_manifest = json.loads((root / "examples/manifest.json").read_text(encoding="utf-8"))
    example_paths = {"examples/manifest.json"}
    for record in example_manifest["files"]:
        relative = record["path"]
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] != "examples" or ".." in parts or any(part.startswith(".") for part in parts):
            raise BuildError("unsafe example manifest path")
        source = root / relative
        if not source.resolve().is_relative_to(root / "examples") or not source.is_file() or source.is_symlink() or _sha256(source) != record["sha256"]:
            raise BuildError(f"example input hash mismatch: {relative}")
        example_paths.add(relative)
    tracked = ({p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
               if snapshot else set(_git(root, "ls-files", "-z").split("\0")) - {""})
    tracked = {p for p in tracked if p in RELEASE_FILES or p in example_paths or (all(
        not part.startswith(".") and part not in {"__pycache__", "node_modules"}
        for part in PurePosixPath(p).parts
    ) and Path(p).suffix in {".py", ".md", ".json", ".mjs", ".yml", ".sh", ".txt", ".example"})}
    tracked.discard("configs/launcher.env")

    sources = (
        {path for path in tracked if path.startswith(RELEASE_PREFIXES)}
        | set(RELEASE_FILES) | example_paths
    ) - DEVELOPMENT_ONLY_FILES
    missing = sorted(path for path in sources if path not in tracked)
    if missing:
        raise BuildError(
            f"required release files are not tracked: {', '.join(missing)}"
        )
    canonical = {
        PurePosixPath(path).parts[1] for path in sources if path.startswith("skills/")
    }
    if canonical != SKILLS:
        raise BuildError("canonical root must contain exactly five Skills")
    for relative in sources:
        source = root / Path(*PurePosixPath(relative).parts)
        if source.is_symlink() or not source.is_file():
            raise BuildError(f"release source must be a regular file: {relative}")
    return sorted(sources)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(root: Path, version: str, commit: str | None) -> tuple[int, str]:
    files = []
    for path in sorted(
        candidate for candidate in root.rglob("*") if candidate.is_file()
    ):
        relative = path.relative_to(root).as_posix()
        files.append(
            {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}
        )
    manifest = {
        "schema_version": 1,
        "artifact": "mandifuel-dsh-skill-plugin",
        "source_mode": "git" if commit else "snapshot",
        "version": version,
        "source_commit": commit,
        "file_count": len(files),
        "files": files,
    }
    target = root / "artifact-manifest.json"
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(files), _sha256(target)


def build(root: Path, output: Path, snapshot: bool = False) -> dict[str, object]:
    if sys.platform != "linux":
        raise BuildError("MANDiFuel release builds are supported on Linux only")
    root = root.resolve(strict=True)
    if snapshot:
        commit = None
    else:
        if Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
            raise BuildError("product root must be the Git worktree root")
        if _git(root, "status", "--porcelain=v1", "--untracked-files=all").strip():
            raise BuildError("release builds require a clean Git worktree")
        commit = _git(root, "rev-parse", "HEAD").strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise BuildError("Git commit identity is invalid")
    version = _version(root)
    sources = _release_sources(root, snapshot)
    if not EXECUTABLE_RELEASE_FILES.issubset(sources):
        raise BuildError("declared executable release files are missing")

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".mandifuel-{version}-", dir=output))
    artifact = staging / f"mandifuel-plugin-{version}"
    try:
        for relative in sources:
            target = artifact / Path(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / Path(*PurePosixPath(relative).parts), target)
            os.chmod(target, 0o755 if relative in EXECUTABLE_RELEASE_FILES else 0o644)
        file_count, manifest_hash = _write_manifest(artifact, version, commit)
        destination = output / artifact.name
        if destination.exists():
            raise BuildError(f"artifact already exists: {destination}")
        os.replace(artifact, destination)
        return {
            "artifact_root": str(destination),
            "file_count": file_count,
            "manifest_sha256": manifest_hash,
            "source_commit": commit,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--product-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--snapshot", action="store_true", help="Build an uncommitted source snapshot; manifest records no Git commit")
    args = parser.parse_args()
    try:
        result = build(args.product_root, args.output_dir or args.product_root / "dist", args.snapshot)
    except (BuildError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
