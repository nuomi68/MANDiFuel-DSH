#!/usr/bin/env python3
"""Describe geometry or apply box, radial, and sector operations through one API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import geometry_angle as angle
from . import geometry_common as common

TransformError = angle.TransformError


def apply(case: Path, plan: dict) -> dict:
    """Apply one geometry operation; Python recipes can pass dictionaries directly."""
    angle.require_object(plan, 'plan', allowed={'schema_version', 'operation', 'artifacts', 'couplings'},
                         required={'operation', 'artifacts'})
    if 'schema_version' in plan and (type(plan['schema_version']) is not int or plan['schema_version'] != 1):
        raise TransformError('schema_version must be integer 1 when supplied')
    if not isinstance(plan['operation'], dict):
        raise TransformError('operation must be a dictionary')
    if plan['operation'].get('type') != 'cylindrical-angle-map':
        return common.apply(Path(case), {k: v for k, v in plan.items() if k != 'schema_version'})
    operation = {'axis': 'z', 'origin': [0, 0, 0],
                 'source_start_degrees': 0, 'target_start_degrees': 0,
                 'require_boundary_coverage': True, **plan['operation']}
    resolved = {**plan, 'schema_version': 1, 'operation': operation}
    return angle.apply(Path(case), angle.parse_plan(resolved))


def describe(case: Path, artifact: dict) -> dict:
    """Return selection information without printing coordinate tables."""
    angle.require_object(artifact, 'artifact', allowed={'path', 'format', 'selection'}, required={'path', 'format'})
    if artifact['format'] != 'unv-2411':
        return common.describe(Path(case), artifact)
    if 'selection' in artifact:
        raise TransformError('the UNV angle operation uses all declared nodes')
    path = angle.validated_case_file(Path(case).resolve(), artifact['path'])
    nodes = angle.parse_unv_nodes(path.read_text(encoding='ascii'), str(path))
    return {'path': artifact['path'], 'format': 'unv-2411', 'points': len(nodes.points),
            'bounds_in_stored_units': [[min(p[i] for p in nodes.points) for i in range(3)],
                                       [max(p[i] for p in nodes.points) for i in range(3)]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--apply', dest='plan', type=Path, help='JSON operation and declared artifacts')
    action.add_argument('--describe', help='Relative geometry path')
    parser.add_argument('--format', choices=['openfoam-block-mesh', 'openfoam-points', 'unv-2411'])
    args = parser.parse_args()
    if args.plan:
        report = apply(args.case, json.loads(args.plan.read_text(encoding='utf-8')))
    else:
        if not args.format:
            parser.error('--describe needs --format')
        report = describe(args.case, {'path': args.describe, 'format': args.format})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (TransformError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f'error: {exc}') from exc
