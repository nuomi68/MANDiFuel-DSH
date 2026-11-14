#!/usr/bin/env python3
"""Create a portable source archive without local configuration or Git history."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

SOURCE_FILES = {
    ".editorconfig", ".gitattributes", ".gitignore", ".python-version",
    ".github/pull_request_template.md", ".github/workflows/check.yml",
    "CONTRIBUTING.md", "requirements-examples.txt", "scripts/package-source.py",
    "rag/audit_case_cards.py", "rag/rebuild_case_cards.py",
}


def source_files(root: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location("mandifuel_builder", root / "scripts/build-plugin.py")
    if spec is None or spec.loader is None:
        raise ValueError("release builder unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = set(module._release_sources(root, snapshot=True)) | SOURCE_FILES
    for name in sorted(files):
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required source must be a regular file: {name}")
        if any(parent.is_symlink() for parent in path.parents if parent != root.parent):
            raise ValueError(f"symlink source boundary: {name}")
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.product_root.resolve(strict=True)
    names = source_files(root)
    output = args.output.resolve()
    if output.exists():
        raise ValueError("output already exists; select a new archive path")
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            data = (root / name).read_bytes()
            info = zipfile.ZipInfo("MANDiFuel-DSH/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
            records.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"schema_version": 1, "artifact": "mandifuel-dsh-source",
                    "source_mode": "snapshot", "source_commit": None,
                    "version": json.loads((root / "mandifuel.json").read_text())["version"],
                    "file_count": len(records), "files": records}
        info = zipfile.ZipInfo("MANDiFuel-DSH/source-manifest.json", date_time=(2026, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({"status": "ok", "files": len(records),
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
