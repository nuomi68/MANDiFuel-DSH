#!/usr/bin/env python3
"""Read or replace an existing OpenFOAM entry with the native dictionary parser."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from .geometry_angle import TransformError, validated_case_file


class FoamEditError(RuntimeError):
    """The native parser could not read or replace the declared entry."""


def _native(path: Path, entry: str, *args: str, executable: str) -> str:
    command = [executable, str(path), '-disableFunctionEntries', '-precision', '17',
               '-no-libs', '-noFunctionObjects', '-entry', entry, *args]
    try:
        result = subprocess.run(command, cwd=path.parent, capture_output=True, text=True,
                                check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FoamEditError(f'foamDictionary is unavailable or failed; use the initialized OpenFOAM environment: {exc}') from exc
    if result.returncode:
        raise FoamEditError(f'foamDictionary could not process entry {entry}: {result.stderr.strip()}')
    return result.stdout.strip()


def get_foam_entry(case: Path, file: str, entry: str, *, executable: str = 'foamDictionary') -> str:
    """Read one literal entry; includes and macros remain unexpanded."""
    path = validated_case_file(Path(case).resolve(), file)
    return _native(path, entry, '-value', executable=executable)


def set_foam_entry(case: Path, file: str, entry: str, value: str | float | int,
                   *, executable: str = 'foamDictionary') -> dict:
    """Replace an existing entry and return its native readback after one staged edit.

    The native writer normalizes formatting. Use task-local editing when the
    request requires preserving unselected text byte for byte.
    """
    case = Path(case)
    if case.is_symlink() or not case.is_dir():
        raise FoamEditError('case must be an isolated regular directory')
    path = validated_case_file(case.resolve(), file)
    # Native -set also adds missing entries. Reading first keeps a resolved
    # replacement from silently becoming an unrelated new key after a typo.
    _native(path, entry, '-value', executable=executable)
    descriptor, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(path.read_bytes())
        os.chmod(staged, stat.S_IMODE(path.stat().st_mode))
        _native(staged, entry, '-set', str(value), executable=executable)
        observed = _native(staged, entry, '-value', executable=executable)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)
    return {'file': file, 'entry': entry, 'value': observed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, type=Path)
    parser.add_argument('--file', required=True)
    parser.add_argument('--entry', required=True, help='Resolved slash-separated entry path')
    replacement = parser.add_mutually_exclusive_group()
    replacement.add_argument('--set', dest='value', help='Replacement in native OpenFOAM syntax')
    replacement.add_argument('--set-file', type=Path, help='UTF-8 file containing only the replacement value')
    args = parser.parse_args()
    if args.set_file is not None:
        args.value = args.set_file.read_text(encoding='utf-8')
    if args.value is None:
        result = {'file': args.file, 'entry': args.entry,
                  'value': get_foam_entry(args.case, args.file, args.entry)}
    else:
        result = set_foam_entry(args.case, args.file, args.entry, args.value)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (FoamEditError, TransformError, OSError) as exc:
        raise SystemExit(f'error: {exc}') from exc
