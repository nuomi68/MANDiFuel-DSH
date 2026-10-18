#!/usr/bin/env python3
"""Common geometry edits in physical metres, using explicit existing topology."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .geometry_angle import (
    FLOAT, CoordinateOccurrence, EdgeRecord, Payload, TransformError, commit,
    finite_float, lexical_view, parenthesized_block, parse_edges, parse_vertices,
    replace_coordinates, require_object, validated_case_file, verify_edge_endpoints,
    validation_certificate,
)


@dataclass
class Block:
    vertices: list[int]
    name: str | None
    counts: tuple[int, int, int]
    count_span: tuple[int, int]


@dataclass
class Geometry:
    path: Path
    before: bytes
    text: str
    format: str
    scale: float
    vertices: list[CoordinateOccurrence]
    edges: list[EdgeRecord]
    blocks: list[Block]
    connections: list[list[int]]
    patches: dict[str, set[int]]

    @property
    def points(self) -> list[tuple[float, float, float]]:
        return [tuple(x * self.scale for x in v.point) for v in self.vertices]


def _vector(value: object, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise TransformError(f"{label} must contain three numbers")
    return tuple(finite_float(x, label) for x in value)


def _balanced(view: str, opening: int, left: str, right: str) -> tuple[int, int]:
    depth = 0
    for i in range(opening, len(view)):
        depth += (view[i] == left) - (view[i] == right)
        if depth == 0:
            return opening, i + 1
    raise TransformError(f"unterminated {left}{right} section")


def _ascii_list(text: str) -> tuple[int, tuple[int, int]]:
    view = lexical_view(text, "OpenFOAM list")
    header = re.search(r"\bFoamFile\s*\{", view)
    if header is None:
        raise TransformError("expected an OpenFOAM list header")
    hs = _balanced(view, header.end() - 1, "{", "}")
    if not re.search(r"\bformat\s+ascii\s*;", view[hs[0]:hs[1]]):
        raise TransformError("this adapter reads ASCII OpenFOAM lists")
    count = re.match(r"\s*(\d+)\s*\(", view[hs[1]:])
    if count is None:
        raise TransformError("expected a counted OpenFOAM list")
    opening = hs[1] + count.end() - 1
    return int(count.group(1)), _balanced(view, opening, "(", ")")


def _faces(text: str, span: tuple[int, int], *, counted: bool) -> list[list[int]]:
    view = lexical_view(text, "faces")
    pattern = re.compile(r"\s*(?:(\d+)\s*)?\(\s*([\d\s]+)\)")
    faces = []
    pos = span[0] + 1
    while view[pos:span[1] - 1].strip():
        m = pattern.match(view, pos, span[1] - 1)
        if m is None:
            raise TransformError("expected explicit face vertex labels")
        labels = [int(v) for v in m.group(2).split()]
        if len(labels) < 3 or (counted and (m.group(1) is None or int(m.group(1)) != len(labels))):
            raise TransformError("face vertex count disagrees with its labels")
        faces.append(labels)
        pos = m.end()
    return faces


def _patches(text: str, span: tuple[int, int], faces: list[list[int]] | None) -> dict[str, set[int]]:
    view = lexical_view(text, "boundary")
    pos, end = span[0] + 1, span[1] - 1
    result = {}
    while view[pos:end].strip():
        m = re.match(r"\s*([\w.-]+)\s*\{", view[pos:end])
        if m is None:
            raise TransformError("expected a literal patch name and dictionary")
        opening = pos + m.end() - 1
        _, stop = _balanced(view, opening, "{", "}")
        body = text[opening + 1:stop - 1]
        if faces is None:
            face_span = parenthesized_block(body, "faces", "patch")
            selected = _faces(body, face_span, counted=False)
        else:
            body_view = lexical_view(body, "patch")
            start = re.search(r"\bstartFace\s+(\d+)\s*;", body_view)
            count = re.search(r"\bnFaces\s+(\d+)\s*;", body_view)
            if start is None or count is None:
                raise TransformError("mesh patch needs startFace and nFaces")
            a, n = int(start.group(1)), int(count.group(1))
            if a + n > len(faces):
                raise TransformError("patch range exceeds the face list")
            selected = faces[a:a + n]
        if m.group(1) in result:
            raise TransformError("duplicate patch name")
        result[m.group(1)] = {v for face in selected for v in face}
        pos = stop
    return result


def _blocks(text: str) -> list[Block]:
    span = parenthesized_block(text, "blocks", "block mesh")
    view = lexical_view(text, "blocks")
    pattern = re.compile(
        r"\bhex\s*\((?P<ids>(?:\s*\d+){8}\s*)\)\s*"
        r"(?:(?P<name>[A-Za-z_]\w*)\s*)?\((?P<counts>(?:\s*\d+){3}\s*)\)"
    )
    matches = list(pattern.finditer(view, *span))
    if not matches or len(matches) != len(re.findall(r"\bhex\b", view[span[0]:span[1]])):
        raise TransformError("expected explicit hex vertices and cell counts")
    blocks = [Block([int(v) for v in m['ids'].split()], m['name'],
                    tuple(int(v) for v in m['counts'].split()), m.span('counts')) for m in matches]
    if any(min(b.counts) <= 0 for b in blocks):
        raise TransformError("block cell counts must be positive")
    return blocks


def read_geometry(case: Path, artifact: dict, *, topology: bool = True) -> Geometry:
    """Read declared coordinates and available topology; do not modify the case."""
    require_object(artifact, "artifact", allowed={"path", "format", "selection"}, required={"path", "format"})
    path = validated_case_file(case.resolve(), artifact['path'])
    before = path.read_bytes()
    try:
        text = before.decode('ascii')
    except UnicodeDecodeError as exc:
        raise TransformError(f"{path}: this adapter requires ASCII geometry") from exc
    fmt = artifact['format']
    edges, blocks, connections, patches = [], [], [], {}
    scale = 1.0
    if fmt == 'openfoam-block-mesh':
        vertices = parse_vertices(text, parenthesized_block(text, 'vertices', str(path)), str(path))
        span = parenthesized_block(text, 'edges', str(path), required=False)
        edges = parse_edges(text, span, str(path)) if span else []
        verify_edge_endpoints(len(vertices), edges, str(path))
        blocks = _blocks(text)
        connections = [b.vertices for b in blocks]
        span = parenthesized_block(text, 'boundary', str(path), required=False)
        patches = _patches(text, span, None) if span else {}
        view = lexical_view(text, str(path))
        units = re.findall(rf"(?m)^\s*(?:convertToMeters|scale)\s+({FLOAT})\s*;", view)
        declared = re.findall(r"(?m)^\s*(?:convertToMeters|scale)\s+", view)
        if len(units) != len(declared) or len(units) > 1:
            raise TransformError("expected one literal scalar mesh scale")
        scale = finite_float(units[0], 'mesh scale') if units else 1.0
        if scale <= 0:
            raise TransformError("mesh scale must be positive")
    elif fmt == 'openfoam-points':
        count, span = _ascii_list(text)
        vertices = parse_vertices(text, span, str(path))
        if len(vertices) != count:
            raise TransformError("points count disagrees with the coordinate list")
        face_path = path.with_name('faces')
        if topology and face_path.exists():
            face_path = validated_case_file(case.resolve(), str(face_path.relative_to(case.resolve())))
            face_text = face_path.read_text(encoding='ascii')
            count, span = _ascii_list(face_text)
            connections = _faces(face_text, span, counted=True)
            if count != len(connections):
                raise TransformError("faces count disagrees with the face list")
            boundary_path = path.with_name('boundary')
            if boundary_path.exists():
                boundary_path = validated_case_file(case.resolve(), str(boundary_path.relative_to(case.resolve())))
                boundary_text = boundary_path.read_text(encoding='ascii')
                count, span = _ascii_list(boundary_text)
                patches = _patches(boundary_text, span, connections)
                if count != len(patches):
                    raise TransformError("boundary count disagrees with the patch list")
    else:
        raise TransformError(f"unsupported geometry format: {fmt}")
    if any(v < 0 or v >= len(vertices) for group in connections + list(patches.values()) for v in group):
        raise TransformError("topology references a missing point")
    return Geometry(path, before, text, fmt, scale, vertices, edges, blocks, connections, patches)


def _components(g: Geometry) -> list[set[int]]:
    if not g.connections:
        raise TransformError("component selection needs existing block or faces connectivity")
    parents = list(range(len(g.vertices)))
    def root(i: int) -> int:
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for group in g.connections:
        for v in group[1:]:
            parents[root(v)] = root(group[0])
    groups = {}
    for i in range(len(parents)):
        groups.setdefault(root(i), set()).add(i)
    return sorted(groups.values(), key=min)


def _selection(g: Geometry, selection: dict | None) -> set[int]:
    if selection is None:
        return set(range(len(g.vertices)))
    require_object(selection, 'selection', allowed={'points', 'blocks', 'patch', 'component', 'connected_to_patch'}, required=set())
    if len(selection) != 1:
        raise TransformError("choose one point, block, patch, or component selection")
    kind, value = next(iter(selection.items()))
    if kind == 'points':
        if not isinstance(value, list) or any(type(v) is not int or not 0 <= v < len(g.vertices) for v in value):
            raise TransformError("point selection needs valid zero-based point IDs")
        selected = set(value)
    elif kind == 'blocks':
        if not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value):
            raise TransformError("block selection needs existing block-zone names")
        if set(value) - {b.name for b in g.blocks}:
            raise TransformError("selected block-zone name is absent")
        selected = {v for b in g.blocks if b.name in value for v in b.vertices}
    elif kind in {'patch', 'connected_to_patch'}:
        if not isinstance(value, str) or value not in g.patches:
            raise TransformError("selected patch is absent")
        selected = g.patches[value]
        if kind == 'connected_to_patch':
            selected = set().union(*(c for c in _components(g) if c & selected))
    else:
        if type(value) is not int or not 0 <= value < len(g.vertices):
            raise TransformError("component needs a point ID from that component")
        selected = next(c for c in _components(g) if value in c)
    if not selected:
        raise TransformError("geometry selection is empty")
    return selected


def _bounds(points: list[tuple[float, float, float]]) -> list[list[float]]:
    return [[min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)]]


def describe(case: Path, artifact: dict) -> dict:
    """Return a compact selection map instead of printing coordinate tables."""
    g = read_geometry(case, artifact)
    points = g.points
    return {'path': artifact['path'], 'format': g.format, 'coordinate_scale_m': g.scale,
            'points': len(points), 'bounds_m': _bounds(points),
            'blocks': [{'name': b.name, 'cells': b.counts} for b in g.blocks],
            'patches': {k: len(v) for k, v in g.patches.items()},
            'components': [{'id': min(c), 'points': len(c),
                            'radius_from_origin_m': [min(math.dist(points[i], (0, 0, 0)) for i in c),
                                                     max(math.dist(points[i], (0, 0, 0)) for i in c)]}
                           for c in _components(g)] if g.connections else []}


def _mapping(operation: dict, points: list[tuple[float, float, float]]):
    kind = operation.get('type')
    if kind == 'box-resize':
        require_object(operation, 'operation', allowed={'type', 'size_m', 'origin_m', 'cell_size_m'}, required={'type', 'size_m'})
        size = _vector(operation['size_m'], 'size_m')
        lower, upper = _bounds(points)
        origin = _vector(operation.get('origin_m', lower), 'origin_m')
        if min(size) <= 0 or any(a == b for a, b in zip(lower, upper)):
            raise TransformError("box dimensions must be positive in all three axes")
        ratios = tuple(s / (b - a) for s, a, b in zip(size, lower, upper))
        return lambda p: tuple(o + (x - a) * r for o, x, a, r in zip(origin, p, lower, ratios)), ratios
    if kind != 'radial-map':
        raise TransformError("operation type must be box-resize or radial-map")
    require_object(operation, 'operation', allowed={'type', 'space', 'origin_m', 'axis', 'radii_m', 'radius_tolerance_m'}, required={'type', 'space', 'radii_m'})
    space = operation['space']
    if space not in {'spherical', 'cylindrical'}:
        raise TransformError("radial space must be spherical or cylindrical")
    axis = operation.get('axis', 'z')
    if axis not in {'x', 'y', 'z'}:
        raise TransformError("axis must be x, y, or z")
    origin = _vector(operation.get('origin_m', [0, 0, 0]), 'origin_m')
    raw = operation['radii_m']
    if not isinstance(raw, list) or len(raw) < 2 or any(not isinstance(v, list) or len(v) != 2 for v in raw):
        raise TransformError("radii_m needs at least two [source, target] radius pairs")
    pairs = [(finite_float(a, 'source radius'), finite_float(b, 'target radius')) for a, b in raw]
    if min(min(p) for p in pairs) < 0 or any(b[0] <= a[0] or b[1] <= a[1] for a, b in zip(pairs, pairs[1:])):
        raise TransformError("source and target radii must be nonnegative and strictly increasing")
    tolerance = finite_float(operation.get('radius_tolerance_m', max(1e-12, pairs[-1][0] * 1e-5)), 'radius tolerance')
    if tolerance < 0:
        raise TransformError("radius tolerance must be nonnegative")
    axes = [i for i in range(3) if space == 'spherical' or i != 'xyz'.index(axis)]
    def mapping(p):
        d = [p[i] - origin[i] for i in range(3)]
        radius = math.sqrt(sum(d[i] ** 2 for i in axes))
        if radius < pairs[0][0] - tolerance or radius > pairs[-1][0] + tolerance:
            raise TransformError("selected point is outside the declared source radius interval")
        r = min(max(radius, pairs[0][0]), pairs[-1][0])
        j = next((i for i in range(len(pairs) - 1) if r <= pairs[i + 1][0]), len(pairs) - 2)
        (a, b), (c, d1) = pairs[j:j + 2]
        target = b + (r - a) * (d1 - b) / (c - a)
        if radius == 0:
            if target != 0:
                raise TransformError("a point at the radial origin has no outward direction")
            return p
        return tuple(origin[i] + d[i] * target / radius if i in axes else p[i] for i in range(3))
    return mapping, None


def _cell_counts(g: Geometry, mapped: list[tuple[float, float, float]], size: object) -> tuple[int, int, int]:
    if len(g.blocks) != 1 or len(g.vertices) != 8:
        raise TransformError("automatic box cell counts require one explicit eight-vertex block")
    widths = _vector(size if isinstance(size, (list, tuple)) else [size] * 3, 'cell_size_m')
    if min(widths) <= 0:
        raise TransformError("cell_size_m must be positive")
    ids = g.blocks[0].vertices
    lower, upper = _bounds(mapped)
    if len(set(mapped)) != 8 or any(p[i] not in (lower[i], upper[i]) for p in mapped for i in range(3)):
        raise TransformError("automatic box counts require axis-aligned corners")
    axes, counts = [], []
    for end in (1, 3, 4):
        delta = [abs(mapped[ids[end]][i] - mapped[ids[0]][i]) for i in range(3)]
        nonzero = [i for i, d in enumerate(delta) if d > 0]
        if len(nonzero) != 1:
            raise TransformError("hex local directions must follow the box axes")
        axis = nonzero[0]
        axes.append(axis)
        ratio = delta[axis] / widths[axis]
        nearest = round(ratio)
        counts.append(max(1, nearest if math.isclose(ratio, nearest, rel_tol=1e-12) else math.ceil(ratio)))
    if len(set(axes)) != 3:
        raise TransformError("hex local directions are not independent")
    return tuple(counts)


def _payload(g: Geometry, operation: dict, selection: dict | None) -> Payload:
    selected = _selection(g, selection)
    if operation.get('type') == 'box-resize' and len(selected) != len(g.vertices):
        raise TransformError("box-resize uses all vertices; use a radial map for selected layers")
    points = g.points
    mapping, ratios = _mapping(operation, [points[i] for i in sorted(selected)])
    mapped = [mapping(p) if i in selected else p for i, p in enumerate(points)]
    occurrences, coordinates = [], []
    for i in sorted(selected):
        occurrences.append(g.vertices[i])
        coordinates.append(tuple(x / g.scale for x in mapped[i]))
    for edge in g.edges:
        flags = [edge.start_index in selected, edge.end_index in selected]
        if not any(flags):
            continue
        if not all(flags):
            raise TransformError("a curved edge crosses the selection; include its complete mapping")
        if edge.kind == 'arc' and ratios and not all(math.isclose(r, ratios[0], rel_tol=1e-12) for r in ratios):
            raise TransformError("anisotropic scaling of a circular arc requires a different edge representation")
        if edge.kind == 'arc' and operation['type'] == 'radial-map':
            origin = _vector(operation.get('origin_m', [0, 0, 0]), 'origin_m')
            axes = [i for i in range(3) if operation['space'] == 'spherical' or i != 'xyz'.index(operation.get('axis', 'z'))]
            arc_points = [points[edge.start_index], points[edge.end_index]] + [tuple(x * g.scale for x in c.point) for c in edge.controls]
            radii = [math.sqrt(sum((p[i] - origin[i]) ** 2 for i in axes)) for p in arc_points]
            if not all(math.isclose(r, radii[0], rel_tol=1e-8, abs_tol=1e-12) for r in radii):
                raise TransformError("radial arc mapping requires a concentric arc")
        for control in edge.controls:
            occurrences.append(control)
            coordinates.append(tuple(x / g.scale for x in mapping(tuple(v * g.scale for v in control.point))))
    if any(not math.isfinite(x) for p in coordinates for x in p):
        raise TransformError("coordinate mapping produced a non-finite value")
    changed = replace_coordinates(g.text, occurrences, coordinates, str(g.path),
                                  formatter=lambda x: format(x, '.17g'))
    counts = None
    if operation['type'] == 'box-resize' and 'cell_size_m' in operation:
        counts = _cell_counts(g, mapped, operation['cell_size_m'])
        # Reparse offsets after replacing coordinates, whose text lengths change.
        start, end = _blocks(changed)[0].count_span
        changed = changed[:start] + ' '.join(map(str, counts)) + changed[end:]
    span = (parenthesized_block(changed, 'vertices', str(g.path)) if g.format == 'openfoam-block-mesh' else _ascii_list(changed)[1])
    readback = parse_vertices(changed, span, str(g.path))
    if len(readback) != len(mapped) or any(not math.isclose(x * g.scale, y, rel_tol=1e-12, abs_tol=1e-15 * g.scale)
                                         for v, p in zip(readback, mapped) for x, y in zip(v.point, p)):
        raise TransformError("coordinate readback differs from the requested mapping")
    checks = ['coordinate_mapping', 'point_count_and_order']
    if g.edges:
        edge_span = parenthesized_block(changed, 'edges', str(g.path))
        observed_edges = parse_edges(changed, edge_span, str(g.path))
        expected_controls = [mapping(tuple(x * g.scale for x in c.point))
                             if e.start_index in selected else tuple(x * g.scale for x in c.point)
                             for e in g.edges for c in e.controls]
        observed_controls = [c.point for e in observed_edges for c in e.controls]
        if len(observed_controls) != len(expected_controls) or any(
            not math.isclose(x * g.scale, y, rel_tol=1e-12, abs_tol=1e-15 * g.scale)
            for p, q in zip(observed_controls, expected_controls) for x, y in zip(p, q)
        ):
            raise TransformError('edge control readback differs from the requested mapping')
        checks.append('edge_control_mapping')
    summary = {'format': g.format, 'selected_points': len(selected), 'bounds_m': _bounds(mapped)}
    if counts is not None:
        if _blocks(changed)[0].counts != counts:
            raise TransformError('cell count readback differs from the requested counts')
        summary['cells'] = counts
        checks.append('cell_counts')
    return Payload(g.path, g.before, changed.encode('ascii'), summary, tuple(checks))


def apply(case: Path, plan: dict) -> dict:
    """Apply one declared operation to its files, reusing the existing commit path."""
    case = Path(case)
    if case.is_symlink() or not case.is_dir():
        raise TransformError("case must be an isolated regular directory")
    require_object(plan, 'plan', allowed={'operation', 'artifacts'}, required={'operation', 'artifacts'})
    if not isinstance(plan['operation'], dict) or not isinstance(plan['artifacts'], list) or not plan['artifacts']:
        raise TransformError("plan needs one operation and a nonempty artifacts list")
    payloads = []
    for artifact in plan['artifacts']:
        selection = artifact.get('selection') if isinstance(artifact, dict) else None
        need_topology = isinstance(selection, dict) and bool(set(selection) & {'patch', 'component', 'connected_to_patch'})
        g = read_geometry(case, artifact, topology=need_topology)
        payloads.append(_payload(g, plan['operation'], selection))
    if len({p.path for p in payloads}) != len(payloads):
        raise TransformError("a geometry path occurs more than once")
    commit([p for p in payloads if p.before != p.after])
    return {'operation': plan['operation'],
            'files': {str(p.path.relative_to(case.resolve())): p.summary for p in payloads},
            'validation': validation_certificate(case.resolve(), payloads)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--plan', type=Path, help='JSON operation and declared artifacts')
    action.add_argument('--describe', help='Relative path; return compact geometry and selection information')
    parser.add_argument('--format', choices=['openfoam-block-mesh', 'openfoam-points'])
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
