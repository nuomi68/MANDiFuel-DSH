#!/usr/bin/env python3
"""Apply a declared, topology-preserving transform to case geometry files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
POINT_RE = re.compile(rf"\(\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*\)")
ANGLE_TOLERANCE = math.radians(1.0e-7)
RELATIVE_TOLERANCE = 1.0e-10
SUPPORTED_EDGE_KINDS = {"arc", "spline", "polyLine", "polySpline", "BSpline"}


class TransformError(RuntimeError):
    """Raised before commit when a plan or input violates an invariant."""


@dataclass(frozen=True)
class Payload:
    path: Path
    before: bytes
    after: bytes
    summary: dict[str, object]
    checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnvNodes:
    lines: list[str]
    coordinate_indices: list[int]
    identifiers: list[int]
    points: list[tuple[float, float, float]]


@dataclass(frozen=True)
class CoordinateOccurrence:
    start: int
    end: int
    point: tuple[float, float, float]


@dataclass(frozen=True)
class EdgeRecord:
    kind: str
    start_index: int
    end_index: int
    controls: tuple[CoordinateOccurrence, ...]


@dataclass(frozen=True)
class AngleMap:
    axis: str
    origin: tuple[float, float, float]
    source_start: float
    source_span: float
    target_start: float
    target_span: float
    require_boundary_coverage: bool

    @property
    def ratio(self) -> float:
        return self.target_span / self.source_span


@dataclass(frozen=True)
class ArtifactSpec:
    path: str
    format: str


@dataclass(frozen=True)
class CouplingSpec:
    path: str
    kind: str
    key: str
    preserve_terminal: float | None = None
    paired_list_key: str | None = None


@dataclass(frozen=True)
class TransformPlan:
    operation: AngleMap
    artifacts: tuple[ArtifactSpec, ...]
    couplings: tuple[CouplingSpec, ...]


def finite_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise TransformError(f"{label} must be a finite number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TransformError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise TransformError(f"{label} must be finite")
    return number


def close(left: float, right: float, scale: float = 1.0) -> bool:
    return abs(left - right) <= RELATIVE_TOLERANCE * max(abs(scale), 1.0)


def format_scalar(value: float) -> str:
    if abs(value) < 5.0e-16:
        value = 0.0
    return format(value, ".16g")


def format_unv_scalar(value: float) -> str:
    if abs(value) < 5.0e-16:
        value = 0.0
    return f"{value:25.16E}"


def newline_of(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def require_object(
    value: object,
    label: str,
    *,
    allowed: set[str],
    required: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TransformError(f"{label} must be a JSON object")
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise TransformError(f"{label} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise TransformError(f"{label} is missing fields: {', '.join(missing)}")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransformError(f"{label} must be a non-empty string")
    return value


def require_key(value: object, label: str) -> str:
    key = require_string(value, label)
    if not re.fullmatch(r"[^\s();{}]+", key):
        raise TransformError(f"{label} is not a supported dictionary key")
    return key


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TransformError(f"{label} must be a JSON array")
    return value


def load_plan(path: Path) -> TransformPlan:
    if path.is_symlink() or not path.is_file():
        raise TransformError(f"plan is not a regular file: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransformError(f"cannot read JSON plan {path}: {exc}") from exc
    return parse_plan(raw)


def parse_plan(raw: object) -> TransformPlan:
    """Parse the legacy angle plan without requiring a JSON file."""
    root = require_object(
        raw,
        "plan",
        allowed={"schema_version", "operation", "artifacts", "couplings"},
        required={"schema_version", "operation", "artifacts"},
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise TransformError("plan.schema_version must be integer 1")

    operation_raw = require_object(
        root["operation"],
        "plan.operation",
        allowed={
            "type",
            "axis",
            "origin",
            "source_start_degrees",
            "source_span_degrees",
            "target_start_degrees",
            "target_span_degrees",
            "require_boundary_coverage",
        },
        required={
            "type",
            "axis",
            "origin",
            "source_start_degrees",
            "source_span_degrees",
            "target_start_degrees",
            "target_span_degrees",
            "require_boundary_coverage",
        },
    )
    if operation_raw["type"] != "cylindrical-angle-map":
        raise TransformError(
            "plan.operation.type must be 'cylindrical-angle-map'"
        )
    axis = require_string(operation_raw["axis"], "plan.operation.axis")
    if axis not in {"x", "y", "z"}:
        raise TransformError("plan.operation.axis must be x, y, or z")
    origin_raw = require_list(operation_raw["origin"], "plan.operation.origin")
    if len(origin_raw) != 3:
        raise TransformError("plan.operation.origin must contain three numbers")
    origin = tuple(
        finite_float(value, f"plan.operation.origin[{index}]")
        for index, value in enumerate(origin_raw)
    )
    source_start = math.radians(
        finite_float(
            operation_raw["source_start_degrees"],
            "plan.operation.source_start_degrees",
        )
        % 360.0
    )
    target_start = math.radians(
        finite_float(
            operation_raw["target_start_degrees"],
            "plan.operation.target_start_degrees",
        )
        % 360.0
    )
    source_span_degrees = finite_float(
        operation_raw["source_span_degrees"],
        "plan.operation.source_span_degrees",
    )
    target_span_degrees = finite_float(
        operation_raw["target_span_degrees"],
        "plan.operation.target_span_degrees",
    )
    if not (0.0 < source_span_degrees < 360.0):
        raise TransformError("source span must be in (0, 360) degrees")
    if not (0.0 < target_span_degrees < 360.0):
        raise TransformError("target span must be in (0, 360) degrees")
    if close(source_span_degrees, target_span_degrees) and close(
        source_start, target_start
    ):
        raise TransformError("source and target angular intervals are equal")
    coverage = operation_raw["require_boundary_coverage"]
    if type(coverage) is not bool:
        raise TransformError("require_boundary_coverage must be boolean")
    operation = AngleMap(
        axis=axis,
        origin=origin,  # type: ignore[arg-type]
        source_start=source_start,
        source_span=math.radians(source_span_degrees),
        target_start=target_start,
        target_span=math.radians(target_span_degrees),
        require_boundary_coverage=coverage,
    )

    artifacts_raw = require_list(root["artifacts"], "plan.artifacts")
    if not artifacts_raw:
        raise TransformError("plan.artifacts must not be empty")
    artifacts: list[ArtifactSpec] = []
    artifact_paths: set[str] = set()
    for index, value in enumerate(artifacts_raw):
        item = require_object(
            value,
            f"plan.artifacts[{index}]",
            allowed={"path", "format"},
            required={"path", "format"},
        )
        relative = require_string(item["path"], f"plan.artifacts[{index}].path")
        file_format = require_string(
            item["format"], f"plan.artifacts[{index}].format"
        )
        if file_format not in {"unv-2411", "openfoam-block-mesh"}:
            raise TransformError(
                f"plan.artifacts[{index}].format is not supported"
            )
        if relative in artifact_paths:
            raise TransformError(f"duplicate artifact path: {relative}")
        artifact_paths.add(relative)
        artifacts.append(ArtifactSpec(relative, file_format))

    couplings_raw = require_list(root.get("couplings", []), "plan.couplings")
    couplings: list[CouplingSpec] = []
    coupling_ids: set[tuple[str, str, str]] = set()
    for index, value in enumerate(couplings_raw):
        common = require_object(
            value,
            f"plan.couplings[{index}]",
            allowed={
                "path",
                "kind",
                "key",
                "preserve_terminal",
                "paired_list_key",
            },
            required={"path", "kind", "key"},
        )
        relative = require_string(common["path"], f"plan.couplings[{index}].path")
        kind = require_string(common["kind"], f"plan.couplings[{index}].kind")
        key = require_key(common["key"], f"plan.couplings[{index}].key")
        if kind not in {"sector-fraction", "sector-normalized-list"}:
            raise TransformError(f"plan.couplings[{index}].kind is not supported")
        if kind == "sector-fraction" and (
            "preserve_terminal" in common or "paired_list_key" in common
        ):
            raise TransformError(
                f"plan.couplings[{index}] scalar coupling has list-only fields"
            )
        preserve_terminal = (
            finite_float(
                common["preserve_terminal"],
                f"plan.couplings[{index}].preserve_terminal",
            )
            if "preserve_terminal" in common
            else None
        )
        paired_list_key = (
            require_key(
                common["paired_list_key"],
                f"plan.couplings[{index}].paired_list_key",
            )
            if "paired_list_key" in common
            else None
        )
        identity = (relative, kind, key)
        if identity in coupling_ids:
            raise TransformError(
                f"duplicate coupling: {relative}:{kind}:{key}"
            )
        coupling_ids.add(identity)
        couplings.append(
            CouplingSpec(
                path=relative,
                kind=kind,
                key=key,
                preserve_terminal=preserve_terminal,
                paired_list_key=paired_list_key,
            )
        )

    return TransformPlan(operation, tuple(artifacts), tuple(couplings))


def coordinate_frame(axis: str) -> tuple[int, int, int]:
    return {
        "x": (1, 2, 0),
        "y": (2, 0, 1),
        "z": (0, 1, 2),
    }[axis]


def local_coordinates(
    point: tuple[float, float, float], operation: AngleMap
) -> tuple[float, float, float]:
    first, second, axial = coordinate_frame(operation.axis)
    shifted = tuple(
        coordinate - origin
        for coordinate, origin in zip(point, operation.origin, strict=True)
    )
    return shifted[first], shifted[second], shifted[axial]


def global_coordinates(
    radial_first: float,
    radial_second: float,
    axial_value: float,
    operation: AngleMap,
) -> tuple[float, float, float]:
    first, second, axial = coordinate_frame(operation.axis)
    shifted = [0.0, 0.0, 0.0]
    shifted[first] = radial_first
    shifted[second] = radial_second
    shifted[axial] = axial_value
    return tuple(
        coordinate + origin
        for coordinate, origin in zip(shifted, operation.origin, strict=True)
    )  # type: ignore[return-value]


def interval_delta(
    first: float,
    second: float,
    start: float,
    span: float,
    label: str,
) -> float:
    delta = (math.atan2(second, first) - start) % math.tau
    if abs(delta - math.tau) <= ANGLE_TOLERANCE or delta <= ANGLE_TOLERANCE:
        delta = 0.0
    elif abs(delta - span) <= ANGLE_TOLERANCE:
        delta = span
    if delta < 0.0 or delta > span:
        raise TransformError(
            f"{label}: point angle is outside the declared angular interval"
        )
    return delta


def transform_point(
    point: tuple[float, float, float],
    operation: AngleMap,
    axis_tolerance: float,
    label: str,
) -> tuple[float, float, float]:
    first, second, axial = local_coordinates(point, operation)
    radius = math.hypot(first, second)
    if radius <= axis_tolerance:
        return global_coordinates(0.0, 0.0, axial, operation)
    delta = interval_delta(
        first,
        second,
        operation.source_start,
        operation.source_span,
        label,
    )
    mapped = operation.target_start + delta * operation.ratio
    return global_coordinates(
        radius * math.cos(mapped),
        radius * math.sin(mapped),
        axial,
        operation,
    )


def verify_point_mapping(
    before: list[tuple[float, float, float]],
    after: list[tuple[float, float, float]],
    operation: AngleMap,
    axis_tolerance: float,
    label: str,
) -> None:
    if len(before) != len(after):
        raise TransformError(f"{label}: point count changed")
    source_deltas: list[float] = []
    target_deltas: list[float] = []
    for index, (old, new) in enumerate(zip(before, after, strict=True), 1):
        old_first, old_second, old_axial = local_coordinates(old, operation)
        new_first, new_second, new_axial = local_coordinates(new, operation)
        old_radius = math.hypot(old_first, old_second)
        new_radius = math.hypot(new_first, new_second)
        if old_radius <= axis_tolerance:
            if new_radius > axis_tolerance or not close(old_axial, new_axial, old_axial):
                raise TransformError(f"{label}: axis point {index} changed physically")
            continue
        if not close(old_radius, new_radius, old_radius):
            raise TransformError(f"{label}: radius changed at point {index}")
        if not close(old_axial, new_axial, old_axial):
            raise TransformError(f"{label}: axial coordinate changed at point {index}")
        old_delta = interval_delta(
            old_first,
            old_second,
            operation.source_start,
            operation.source_span,
            f"{label}: source point {index}",
        )
        new_delta = interval_delta(
            new_first,
            new_second,
            operation.target_start,
            operation.target_span,
            f"{label}: transformed point {index}",
        )
        if abs(new_delta - old_delta * operation.ratio) > ANGLE_TOLERANCE:
            raise TransformError(f"{label}: angle mapping failed at point {index}")
        source_deltas.append(old_delta)
        target_deltas.append(new_delta)
    if not source_deltas:
        raise TransformError(f"{label}: no non-axis points")
    if operation.require_boundary_coverage:
        if min(source_deltas) > ANGLE_TOLERANCE or abs(
            max(source_deltas) - operation.source_span
        ) > ANGLE_TOLERANCE:
            raise TransformError(f"{label}: source does not cover both boundaries")
        if min(target_deltas) > ANGLE_TOLERANCE or abs(
            max(target_deltas) - operation.target_span
        ) > ANGLE_TOLERANCE:
            raise TransformError(f"{label}: result does not cover both boundaries")


def parse_unv_nodes(text: str, label: str) -> UnvNodes:
    lines = text.splitlines(keepends=True)
    headers = [index for index, line in enumerate(lines) if line.strip() == "2411"]
    if len(headers) != 1:
        raise TransformError(
            f"{label}: expected one UNV 2411 dataset, found {len(headers)}"
        )
    header = headers[0]
    if header == 0 or lines[header - 1].strip() != "-1":
        raise TransformError(f"{label}: malformed 2411 dataset boundary")

    identifiers: list[int] = []
    coordinate_indices: list[int] = []
    points: list[tuple[float, float, float]] = []
    index = header + 1
    while index < len(lines) and lines[index].strip() != "-1":
        if index + 1 >= len(lines):
            raise TransformError(f"{label}: truncated 2411 node record")
        header_fields = lines[index].split()
        coordinate_fields = lines[index + 1].split()
        if len(header_fields) != 4:
            raise TransformError(f"{label}: invalid node header at line {index + 1}")
        try:
            header_numbers = [int(value) for value in header_fields]
        except ValueError as exc:
            raise TransformError(
                f"{label}: non-integer node header at line {index + 1}"
            ) from exc
        if len(coordinate_fields) != 3:
            raise TransformError(
                f"{label}: invalid coordinate record at line {index + 2}"
            )
        point = tuple(
            finite_float(value, f"{label}: coordinate at line {index + 2}")
            for value in coordinate_fields
        )
        identifiers.append(header_numbers[0])
        coordinate_indices.append(index + 1)
        points.append(point)  # type: ignore[arg-type]
        index += 2

    if index >= len(lines) or not points:
        raise TransformError(f"{label}: unterminated or empty 2411 dataset")
    if len(set(identifiers)) != len(identifiers):
        raise TransformError(f"{label}: duplicate node identifiers")
    return UnvNodes(lines, coordinate_indices, identifiers, points)


def radial_extent(
    points: list[tuple[float, float, float]], operation: AngleMap
) -> float:
    return max(
        math.hypot(*local_coordinates(point, operation)[:2]) for point in points
    )


def transform_unv(path: Path, operation: AngleMap) -> Payload:
    before = path.read_bytes()
    try:
        text = before.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TransformError(f"{path}: UNV input is not ASCII") from exc
    parsed = parse_unv_nodes(text, str(path))
    axis_tolerance = max(radial_extent(parsed.points, operation) * 1.0e-12, 1.0e-14)
    mapped = [
        transform_point(point, operation, axis_tolerance, str(path))
        for point in parsed.points
    ]

    lines = list(parsed.lines)
    for line_index, point in zip(parsed.coordinate_indices, mapped, strict=True):
        lines[line_index] = "".join(format_unv_scalar(value) for value in point) + newline_of(
            lines[line_index]
        )
    after_text = "".join(lines)
    reparsed = parse_unv_nodes(after_text, f"{path} transformed")
    if reparsed.identifiers != parsed.identifiers:
        raise TransformError(f"{path}: node identifiers or order changed")
    coordinate_set = set(parsed.coordinate_indices)
    for index, (old_line, new_line) in enumerate(
        zip(parsed.lines, reparsed.lines, strict=True)
    ):
        if index not in coordinate_set and old_line != new_line:
            raise TransformError(f"{path}: non-coordinate UNV content changed")
    verify_point_mapping(
        parsed.points,
        reparsed.points,
        operation,
        axis_tolerance,
        str(path),
    )
    return Payload(
        path=path,
        before=before,
        after=after_text.encode("ascii"),
        summary={"format": "unv-2411", "nodes": len(parsed.points)},
        checks=("coordinate_mapping", "node_ids_and_order", "non_coordinate_content"),
    )


def lexical_view(text: str, label: str) -> str:
    """Return an offset-preserving view with comments and strings neutralized."""
    view = list(text)
    index = 0
    while index < len(text):
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            if end < 0:
                end = len(text)
            for offset in range(index, end):
                view[offset] = " "
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise TransformError(f"{label}: unterminated block comment")
            for offset in range(index, end + 2):
                if text[offset] not in "\r\n":
                    view[offset] = " "
            index = end + 2
            continue
        if text[index] in {'"', "'"}:
            quote = text[index]
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    if text[index] not in "\r\n":
                        view[index] = " "
                    index += 1
                    if index < len(text) and text[index] not in "\r\n":
                        view[index] = " "
                    index += 1
                    continue
                if text[index] == quote:
                    index += 1
                    break
                if text[index] not in "\r\n":
                    view[index] = " "
                index += 1
            else:
                raise TransformError(f"{label}: unterminated quoted string")
            continue
        index += 1
    return "".join(view)


def parenthesized_block(
    text: str, keyword: str, label: str, *, required: bool = True
) -> tuple[int, int] | None:
    view = lexical_view(text, label)
    pattern = re.compile(
        rf"(?m)^[ \t]*{re.escape(keyword)}[ \t]*(?:\r?\n[ \t]*)?\("
    )
    matches = list(pattern.finditer(view))
    if not matches:
        if required:
            raise TransformError(f"{label}: missing {keyword} block")
        return None
    if len(matches) != 1:
        raise TransformError(f"{label}: repeated {keyword} block")
    match = matches[0]
    opening = view.rfind("(", match.start(), match.end())
    depth = 0
    for index in range(opening, len(view)):
        if view[index] == "(":
            depth += 1
        elif view[index] == ")":
            depth -= 1
            if depth == 0:
                return opening, index + 1
    raise TransformError(f"{label}: unterminated {keyword} block")


def skip_whitespace(view: str, index: int, limit: int) -> int:
    while index < limit and view[index].isspace():
        index += 1
    return index


def coordinate_at(
    view: str, index: int, limit: int, label: str
) -> CoordinateOccurrence | None:
    match = POINT_RE.match(view, index, limit)
    if match is None:
        return None
    point = tuple(finite_float(value, label) for value in match.groups())
    return CoordinateOccurrence(index, match.end(), point)  # type: ignore[arg-type]


def parse_vertices(
    text: str, span: tuple[int, int], label: str
) -> list[CoordinateOccurrence]:
    view = lexical_view(text, label)
    index = span[0] + 1
    limit = span[1] - 1
    vertices: list[CoordinateOccurrence] = []
    while True:
        index = skip_whitespace(view, index, limit)
        if index == limit:
            break
        coordinate = coordinate_at(view, index, limit, label)
        if coordinate is None:
            raise TransformError(
                f"{label}: vertices must contain only explicit coordinate tuples"
            )
        vertices.append(coordinate)
        index = skip_whitespace(view, coordinate.end, limit)
        if index < limit and view[index] == ";":
            index += 1
    if not vertices:
        raise TransformError(f"{label}: no coordinate tuples")
    return vertices


def replace_coordinates(
    text: str,
    occurrences: list[CoordinateOccurrence],
    mapped: list[tuple[float, float, float]],
    label: str,
    *,
    formatter: Callable[[float], str] = format_scalar,
) -> str:
    if len(occurrences) != len(mapped):
        raise TransformError(f"{label}: coordinate occurrence count changed")
    chunks: list[str] = []
    cursor = 0
    pairs = sorted(
        zip(occurrences, mapped, strict=True), key=lambda pair: pair[0].start
    )
    for occurrence, point in pairs:
        if occurrence.start < cursor:
            raise TransformError(f"{label}: overlapping coordinate occurrences")
        chunks.append(text[cursor : occurrence.start])
        chunks.append("(" + " ".join(formatter(value) for value in point) + ")")
        cursor = occurrence.end
    chunks.append(text[cursor:])
    return "".join(chunks)


def parse_index(view: str, index: int, limit: int, label: str) -> tuple[int, int]:
    index = skip_whitespace(view, index, limit)
    match = re.compile(r"\d+\b").match(view, index, limit)
    if match is None:
        raise TransformError(f"{label}: edge endpoint must be a non-negative index")
    return int(match.group()), match.end()


def parse_control_list(
    view: str, index: int, limit: int, label: str
) -> tuple[tuple[CoordinateOccurrence, ...], int]:
    index = skip_whitespace(view, index, limit)
    if index >= limit or view[index] != "(":
        raise TransformError(f"{label}: edge control list must start with '('")
    index += 1
    controls: list[CoordinateOccurrence] = []
    while True:
        index = skip_whitespace(view, index, limit)
        if index >= limit:
            raise TransformError(f"{label}: unterminated edge control list")
        if view[index] == ")":
            return tuple(controls), index + 1
        coordinate = coordinate_at(view, index, limit, label)
        if coordinate is None:
            raise TransformError(
                f"{label}: edge control list must contain only coordinate tuples"
            )
        controls.append(coordinate)
        index = skip_whitespace(view, coordinate.end, limit)
        if index < limit and view[index] == ";":
            index += 1


def parse_edges(
    text: str, span: tuple[int, int], label: str
) -> list[EdgeRecord]:
    view = lexical_view(text, label)
    index = span[0] + 1
    limit = span[1] - 1
    records: list[EdgeRecord] = []
    word = re.compile(r"[A-Za-z][A-Za-z0-9]*\b")
    while True:
        index = skip_whitespace(view, index, limit)
        if index == limit:
            break
        kind_match = word.match(view, index, limit)
        if kind_match is None:
            raise TransformError(f"{label}: unrecognized syntax in edges block")
        kind = kind_match.group()
        if kind not in SUPPORTED_EDGE_KINDS:
            raise TransformError(f"{label}: unsupported edge kind: {kind}")
        start_index, index = parse_index(view, kind_match.end(), limit, label)
        end_index, index = parse_index(view, index, limit, label)
        index = skip_whitespace(view, index, limit)
        if kind == "arc":
            control = coordinate_at(view, index, limit, label)
            if control is None:
                raise TransformError(
                    f"{label}: arc must contain exactly one control coordinate"
                )
            controls = (control,)
            index = control.end
        else:
            controls, index = parse_control_list(view, index, limit, label)
            if not controls:
                raise TransformError(
                    f"{label}: {kind} must contain at least one control coordinate"
                )
        index = skip_whitespace(view, index, limit)
        if index < limit and view[index] == ";":
            index += 1
        records.append(EdgeRecord(kind, start_index, end_index, controls))
    return records


def arc_records(
    records: list[EdgeRecord],
) -> list[tuple[int, int, tuple[float, float, float]]]:
    return [
        (record.start_index, record.end_index, record.controls[0].point)
        for record in records
        if record.kind == "arc"
    ]


def verify_edge_endpoints(
    vertex_count: int, records: list[EdgeRecord], label: str
) -> None:
    for record in records:
        if record.start_index >= vertex_count or record.end_index >= vertex_count:
            raise TransformError(
                f"{label}: {record.kind} endpoint is outside vertices"
            )


def verify_arcs(
    vertices: list[tuple[float, float, float]],
    records: list[tuple[int, int, tuple[float, float, float]]],
    operation: AngleMap,
    *,
    transformed: bool,
    label: str,
) -> None:
    start = operation.target_start if transformed else operation.source_start
    span = operation.target_span if transformed else operation.source_span
    for start_index, end_index, control in records:
        if start_index >= len(vertices) or end_index >= len(vertices):
            raise TransformError(f"{label}: arc endpoint is outside vertices")
        points = [vertices[start_index], control, vertices[end_index]]
        local = [local_coordinates(point, operation) for point in points]
        radii = [math.hypot(point[0], point[1]) for point in local]
        if max(radii) - min(radii) > 1.0e-8 * max(max(radii), 1.0):
            raise TransformError(f"{label}: arc control radius disagrees with endpoints")
        deltas = [
            interval_delta(point[0], point[1], start, span, label) for point in local
        ]
        lower, upper = sorted((deltas[0], deltas[2]))
        if deltas[1] < lower - ANGLE_TOLERANCE or deltas[1] > upper + ANGLE_TOLERANCE:
            raise TransformError(f"{label}: arc control point is outside endpoint angles")


def transform_block_mesh(path: Path, operation: AngleMap) -> Payload:
    before = path.read_bytes()
    try:
        text = before.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransformError(f"{path}: block mesh input is not UTF-8") from exc
    vertex_span = parenthesized_block(text, "vertices", str(path))
    assert vertex_span is not None
    edge_span = parenthesized_block(text, "edges", str(path), required=False)
    vertex_occurrences = parse_vertices(text, vertex_span, f"{path}: vertices")
    edge_records = parse_edges(text, edge_span, str(path)) if edge_span is not None else []
    edge_occurrences = [
        control for record in edge_records for control in record.controls
    ]
    vertices = [occurrence.point for occurrence in vertex_occurrences]
    controls = [occurrence.point for occurrence in edge_occurrences]
    verify_edge_endpoints(len(vertices), edge_records, str(path))
    records = arc_records(edge_records)
    verify_arcs(
        vertices,
        records,
        operation,
        transformed=False,
        label=str(path),
    )
    axis_tolerance = max(
        radial_extent(vertices + controls, operation) * 1.0e-12,
        1.0e-14,
    )
    mapped_vertices = [
        transform_point(point, operation, axis_tolerance, str(path))
        for point in vertices
    ]
    mapped_controls = [
        transform_point(point, operation, axis_tolerance, str(path))
        for point in controls
    ]

    changed = replace_coordinates(
        text,
        vertex_occurrences + edge_occurrences,
        mapped_vertices + mapped_controls,
        str(path),
    )

    new_vertex_span = parenthesized_block(changed, "vertices", str(path))
    assert new_vertex_span is not None
    new_edge_span = parenthesized_block(
        changed, "edges", str(path), required=False
    )
    new_vertex_occurrences = parse_vertices(
        changed, new_vertex_span, f"{path}: transformed vertices"
    )
    new_edge_records = (
        parse_edges(changed, new_edge_span, f"{path}: transformed")
        if new_edge_span is not None
        else []
    )
    new_vertices = [occurrence.point for occurrence in new_vertex_occurrences]
    new_controls = [
        control.point for record in new_edge_records for control in record.controls
    ]
    verify_edge_endpoints(
        len(new_vertices), new_edge_records, f"{path}: transformed"
    )
    verify_point_mapping(
        vertices + controls,
        new_vertices + new_controls,
        operation,
        axis_tolerance,
        str(path),
    )
    new_records = arc_records(new_edge_records)
    verify_arcs(
        new_vertices,
        new_records,
        operation,
        transformed=True,
        label=f"{path}: transformed",
    )
    for keyword in ("blocks", "boundary"):
        old_span = parenthesized_block(text, keyword, str(path))
        new_span = parenthesized_block(changed, keyword, str(path))
        assert old_span is not None and new_span is not None
        if text[old_span[0] : old_span[1]] != changed[new_span[0] : new_span[1]]:
            raise TransformError(f"{path}: {keyword} topology changed")
    return Payload(
        path=path,
        before=before,
        after=changed.encode("utf-8"),
        summary={
            "format": "openfoam-block-mesh",
            "vertices": len(vertices),
            "edge_coordinates": len(controls),
        },
        checks=("coordinate_mapping", "edge_control_mapping", "arc_geometry", "blocks_and_boundary"),
    )


def one_match(pattern: re.Pattern[str], text: str, label: str) -> re.Match[str]:
    matches = list(pattern.finditer(lexical_view(text, label)))
    if len(matches) != 1:
        raise TransformError(f"{label}: expected one occurrence, found {len(matches)}")
    return matches[0]


def scalar_pattern(key: str) -> re.Pattern[str]:
    return re.compile(rf"(?m)^([ \t]*{re.escape(key)}[ \t]+)({FLOAT})([ \t]*;)")


def list_pattern(key: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?ms)^([ \t]*{re.escape(key)}[ \t\r\n]*)\(([^()]*)\)([ \t]*;)"
    )


def parse_scalar_list(value: str, label: str) -> list[float]:
    tokens = value.split()
    if not tokens:
        raise TransformError(f"{label}: empty list")
    return [finite_float(token, label) for token in tokens]


def list_value_replacements(
    text: str,
    start: int,
    end: int,
    values: list[float],
    label: str,
) -> list[tuple[int, int, str]]:
    view = lexical_view(text, label)
    tokens = list(re.finditer(r"\S+", view[start:end]))
    if len(tokens) != len(values):
        raise TransformError(f"{label}: list token count changed")
    replacements: list[tuple[int, int, str]] = []
    for token, value in zip(tokens, values, strict=True):
        if re.fullmatch(FLOAT, token.group()) is None:
            raise TransformError(f"{label}: list contains a non-numeric token")
        replacements.append(
            (start + token.start(), start + token.end(), format_scalar(value))
        )
    return replacements


def transform_metadata(
    path: Path, specs: list[CouplingSpec], operation: AngleMap
) -> Payload:
    before = path.read_bytes()
    try:
        text = before.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransformError(f"{path}: metadata input is not UTF-8") from exc
    old_fraction = operation.source_span / math.tau
    new_fraction = operation.target_span / math.tau
    replacements: list[tuple[int, int, str]] = []
    expected_values: dict[str, object] = {}

    for spec in specs:
        label = f"{path}: {spec.key}"
        if spec.kind == "sector-fraction":
            pattern = scalar_pattern(spec.key)
            match = one_match(pattern, text, label)
            observed = finite_float(match.group(2), label)
            if not close(observed, old_fraction):
                raise TransformError(
                    f"{label} does not match the declared source sector"
                )
            replacements.append(
                (match.start(2), match.end(2), format_scalar(new_fraction))
            )
            expected_values[spec.key] = new_fraction
            continue

        pattern = list_pattern(spec.key)
        match = one_match(pattern, text, label)
        locations = parse_scalar_list(match.group(2), label)
        active = locations
        terminal: float | None = None
        if spec.preserve_terminal is not None:
            if len(locations) < 3 or not close(
                locations[-1], spec.preserve_terminal, spec.preserve_terminal
            ):
                raise TransformError(f"{label}: terminal value does not match plan")
            active = locations[:-1]
            terminal = locations[-1]
        if len(active) < 2 or not close(active[0], 0.0):
            raise TransformError(f"{label}: sector locations must start at zero")
        if not close(active[-1], old_fraction):
            raise TransformError(f"{label}: locations do not reach source fraction")
        if any(right <= left for left, right in zip(locations, locations[1:])):
            raise TransformError(f"{label}: locations are not strictly increasing")
        if any(value < 0.0 or value > old_fraction + RELATIVE_TOLERANCE for value in active):
            raise TransformError(f"{label}: location lies outside source sector")
        mapped = [value * operation.ratio for value in active]
        if terminal is not None:
            mapped.append(terminal)
        if any(right <= left for left, right in zip(mapped, mapped[1:])):
            raise TransformError(
                f"{label}: transformed locations are not strictly increasing"
            )
        if spec.paired_list_key is not None:
            paired_match = one_match(
                list_pattern(spec.paired_list_key),
                text,
                f"{path}: {spec.paired_list_key}",
            )
            paired = parse_scalar_list(
                paired_match.group(2), f"{path}: {spec.paired_list_key}"
            )
            if len(paired) != len(locations):
                raise TransformError(
                    f"{path}: {spec.paired_list_key} length differs from {spec.key}"
                )
        replacements.extend(
            list_value_replacements(
                text,
                match.start(2),
                match.end(2),
                mapped,
                label,
            )
        )
        expected_values[spec.key] = mapped

    changed = text
    for start, end, replacement in sorted(replacements, reverse=True):
        changed = changed[:start] + replacement + changed[end:]

    for spec in specs:
        if spec.kind == "sector-fraction":
            match = one_match(
                scalar_pattern(spec.key), changed, f"{path}: transformed {spec.key}"
            )
            observed = finite_float(match.group(2), f"{path}: {spec.key}")
            if not close(observed, float(expected_values[spec.key])):
                raise TransformError(f"{path}: transformed {spec.key} is incorrect")
        else:
            match = one_match(
                list_pattern(spec.key), changed, f"{path}: transformed {spec.key}"
            )
            observed = parse_scalar_list(match.group(2), f"{path}: {spec.key}")
            expected = expected_values[spec.key]
            assert isinstance(expected, list)
            if len(observed) != len(expected) or any(
                not close(left, right) for left, right in zip(observed, expected, strict=True)
            ):
                raise TransformError(f"{path}: transformed {spec.key} is incorrect")

    return Payload(
        path=path,
        before=before,
        after=changed.encode("utf-8"),
        summary={"format": "openfoam-dictionary", "keys": [spec.key for spec in specs]},
        checks=("declared_metadata_values",),
    )


def validated_case_file(case_root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise TransformError(f"case path must be canonical and relative: {relative}")
    candidate = case_root
    for part in relative_path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise TransformError(f"case path traverses a symlink: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(case_root)
    except (OSError, ValueError) as exc:
        raise TransformError(f"case path is missing or escapes the case: {relative}") from exc
    if not resolved.is_file():
        raise TransformError(f"required regular file is missing: {relative}")
    return resolved


def stage_payload(payload: Payload) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{payload.path.name}.", suffix=".tmp", dir=payload.path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload.after)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(payload.path.stat().st_mode))
        if temporary.read_bytes() != payload.after:
            raise TransformError(f"failed to verify staged file for {payload.path}")
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def restore_payload(payload: Payload) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{payload.path.name}.", suffix=".rollback", dir=payload.path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload.before)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(payload.path.stat().st_mode))
        os.replace(temporary, payload.path)
    finally:
        temporary.unlink(missing_ok=True)


def commit(payloads: list[Payload]) -> None:
    staged: list[tuple[Payload, Path]] = []
    replaced: list[Payload] = []
    try:
        for payload in payloads:
            staged.append((payload, stage_payload(payload)))
        for payload, temporary in staged:
            os.replace(temporary, payload.path)
            replaced.append(payload)
    except Exception as exc:
        rollback_errors: list[str] = []
        for payload in reversed(replaced):
            try:
                restore_payload(payload)
            except Exception as rollback_exc:  # pragma: no cover - OS failure path
                rollback_errors.append(f"{payload.path}: {rollback_exc}")
        if rollback_errors:
            detail = ", ".join(rollback_errors)
            raise TransformError(
                f"case update failed; rollback was incomplete: {detail}"
            ) from exc
        raise TransformError(
            "case update failed; prior replacements were rolled back"
        ) from exc
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)


def validation_certificate(case_root: Path, payloads: list[Payload]) -> dict[str, object]:
    """Bind completed payload checks to the bytes published by a successful commit.

    Call only after commit returns; this describes the declared edit, not case quality.
    """
    return {
        "status": "passed",
        "files": {
            str(payload.path.relative_to(case_root)): {
                "sha256": hashlib.sha256(payload.after).hexdigest(),
                "checks": list(payload.checks),
            }
            for payload in payloads
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a checked geometry-transform transaction to case files."
    )
    parser.add_argument("--case", required=True, type=Path, help="Isolated target case")
    parser.add_argument("--plan", required=True, type=Path, help="Task-local JSON plan")
    return parser.parse_args()


def apply(case: Path, plan: TransformPlan) -> dict[str, object]:
    """Apply an already parsed angle plan; shared with the public dispatcher."""
    if case.is_symlink() or not case.is_dir():
        raise TransformError(f"case root is not a regular directory: {case}")
    case_root = case.resolve()

    payloads: list[Payload] = []
    used_paths: set[Path] = set()
    for artifact in plan.artifacts:
        path = validated_case_file(case_root, artifact.path)
        if path in used_paths:
            raise TransformError(f"file appears more than once in plan: {artifact.path}")
        used_paths.add(path)
        if artifact.format == "unv-2411":
            payloads.append(transform_unv(path, plan.operation))
        else:
            payloads.append(transform_block_mesh(path, plan.operation))

    grouped_couplings: dict[Path, list[CouplingSpec]] = {}
    for coupling in plan.couplings:
        path = validated_case_file(case_root, coupling.path)
        if path in used_paths:
            raise TransformError(
                f"one file cannot be both an artifact and metadata: {coupling.path}"
            )
        grouped_couplings.setdefault(path, []).append(coupling)
    for path, specs in grouped_couplings.items():
        used_paths.add(path)
        payloads.append(transform_metadata(path, specs, plan.operation))

    unchanged = [
        str(payload.path.relative_to(case_root))
        for payload in payloads
        if payload.before == payload.after
    ]
    if unchanged:
        raise TransformError("expected planned files did not change: " + ", ".join(unchanged))
    commit(payloads)
    return {
        "schema_version": 1,
        "case": str(case_root),
        "operation": {
            "type": "cylindrical-angle-map",
            "axis": plan.operation.axis,
            "origin": list(plan.operation.origin),
            "source_start_degrees": round(math.degrees(plan.operation.source_start), 12),
            "source_span_degrees": round(math.degrees(plan.operation.source_span), 12),
            "target_start_degrees": round(math.degrees(plan.operation.target_start), 12),
            "target_span_degrees": round(math.degrees(plan.operation.target_span), 12),
            "require_boundary_coverage": plan.operation.require_boundary_coverage,
        },
        "files": {
            str(payload.path.relative_to(case_root)): payload.summary
            for payload in payloads
        },
        "validation": validation_certificate(case_root, payloads),
    }


def main() -> int:
    args = parse_args()
    report = apply(args.case, load_plan(args.plan))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TransformError as exc:
        raise SystemExit(f"error: {exc}") from exc
