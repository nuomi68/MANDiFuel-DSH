"""Deterministic, dependency-free selection for common ASCII OpenFOAM results.

Import this module directly for one-off extraction and persisted task programs.
Copy it into a program only when the user explicitly requests a standalone
program that runs without the plugin. It parses result fields, probe tables,
zones, and primitive mesh geometry; it never runs OpenFOAM or guesses a time,
region, or location.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

type FieldKind = Literal["scalar", "vector", "sphericalTensor", "symmTensor", "tensor"]
type Value = tuple[Decimal, ...]
type Point = tuple[Decimal, Decimal, Decimal]
type Face = tuple[int, ...]
type ReductionOperation = Literal["max", "min", "max_abs"]
type Axis = Literal["x", "y", "z"]
type DimensionOperation = Literal["add", "subtract", "multiply", "divide"]
type MeshPrimitiveName = Literal["points", "faces", "owner", "neighbour", "boundary", "cellZones"]
type MissingFieldPolicy = Literal["error", "skip"]

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_NONFINITE = re.compile(r"[+-]?(?:nan|inf(?:inity)?)", re.IGNORECASE)
_DELIMITERS = frozenset("{}()[];<>")
_MAX_OPENFOAM_LABEL = (1 << 63) - 1
_MAX_OPENFOAM_LABEL_DIGITS = len(str(_MAX_OPENFOAM_LABEL))
DEFAULT_COMPACT_LABEL_LIST_LIMIT = 10_000_000
_WIDTH: dict[FieldKind, int] = {
    "scalar": 1,
    "vector": 3,
    "sphericalTensor": 1,
    "symmTensor": 6,
    "tensor": 9,
}
_COMPONENT_NAMES: dict[FieldKind, tuple[str, ...]] = {
    "scalar": ("value",),
    "vector": ("x", "y", "z"),
    "sphericalTensor": ("ii",),
    "symmTensor": ("xx", "xy", "xz", "yy", "yz", "zz"),
    "tensor": ("xx", "xy", "xz", "yx", "yy", "yz", "zx", "zy", "zz"),
}
_MESH_PRIMITIVES: tuple[MeshPrimitiveName, ...] = (
    "points",
    "faces",
    "owner",
    "neighbour",
    "boundary",
    "cellZones",
)
_REQUIRED_GEOMETRY_PRIMITIVES: tuple[MeshPrimitiveName, ...] = (
    "points",
    "faces",
    "owner",
    "neighbour",
)
_BOUNDARY_TOPOLOGY_PRIMITIVES: tuple[MeshPrimitiveName, ...] = (
    "faces",
    "owner",
    "neighbour",
    "boundary",
)

DIMENSIONLESS_DIMENSIONS: tuple[Decimal, ...] = (Decimal(0),) * 7

CANONICAL_SI_UNITS_BY_DIMENSIONS: dict[tuple[Decimal, ...], str] = {
    (
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(1),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    ): "K",
    (
        Decimal(0),
        Decimal(1),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    ): "m",
    (
        Decimal(1),
        Decimal(-1),
        Decimal(-2),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    ): "Pa",
}


class OpenFOAMParseError(ValueError):
    """The selected result is malformed, unsupported, or ambiguous."""


class _ExactFieldMissing(OpenFOAMParseError):
    """The exact field directory entry is genuinely absent."""


def _validated_dimensions(dimensions: tuple[Decimal, ...], *, context: str) -> tuple[Decimal, ...]:
    if len(dimensions) != 7:
        raise OpenFOAMParseError(f"{context} must contain seven exponents")
    if any(
        not isinstance(exponent, Decimal) or not exponent.is_finite() for exponent in dimensions
    ):
        raise OpenFOAMParseError(f"{context} must contain finite Decimal exponents")
    return tuple(dimensions)


def combine_dimensions(
    left: tuple[Decimal, ...],
    right: tuple[Decimal, ...],
    *,
    operation: DimensionOperation,
) -> tuple[Decimal, ...]:
    """Propagate dimensions for one explicit binary arithmetic operation."""

    left = _validated_dimensions(left, context="left dimensions")
    right = _validated_dimensions(right, context="right dimensions")
    if operation in ("add", "subtract"):
        if left != right:
            raise OpenFOAMParseError(f"cannot {operation} quantities with different dimensions")
        return left
    if operation == "multiply":
        return tuple(a + b for a, b in zip(left, right, strict=True))
    if operation == "divide":
        return tuple(a - b for a, b in zip(left, right, strict=True))
    raise OpenFOAMParseError(f"unsupported dimension operation {operation!r}")


def canonical_si_unit_for_dimensions(dimensions: tuple[Decimal, ...]) -> str | None:
    """Return a narrow canonical SI unit for one seven-exponent vector.

    The all-zero vector intentionally has no mapping because OFFBEAT can store
    semantically dimensional quantities, including burnup, with zero exponents.
    """

    dimensions = _validated_dimensions(dimensions, context="OpenFOAM dimensions")
    return CANONICAL_SI_UNITS_BY_DIMENSIONS.get(dimensions)


@dataclass(frozen=True, slots=True)
class NumericDirectory:
    name: str
    value: Decimal
    path: Path


@dataclass(frozen=True, slots=True)
class CellZone:
    name: str
    cell_labels: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BoundaryPatchTopology:
    name: str
    n_faces: int
    start_face: int
    patch_type: str | None = None
    owner: bool | None = None
    neighbour_patch: str | None = None


@dataclass(frozen=True, slots=True)
class PolyMeshGeometry:
    cell_centres: tuple[Point, ...]
    cell_volumes: tuple[Decimal, ...]


@dataclass(frozen=True, slots=True)
class CellExtremum:
    cell_label: int
    value: Decimal
    centre: Point


@dataclass(frozen=True, slots=True)
class CellScalarValue:
    cell_label: int
    value: Decimal
    centre: Point


@dataclass(frozen=True, slots=True)
class CellValueReduction:
    operation: ReductionOperation
    selected_cell_count: int
    comparison_value: Decimal
    extrema: tuple[CellExtremum, ...]


@dataclass(frozen=True, slots=True)
class FieldReduction:
    source_path: str
    object_name: str
    operation: ReductionOperation
    component: str
    component_index: int
    selected_cell_count: int
    comparison_value: Decimal
    extrema: tuple[CellExtremum, ...]


@dataclass(frozen=True, slots=True)
class BoundaryFieldValues:
    source_path: str
    object_name: str
    class_name: str
    patch_name: str
    entry_name: str
    dimensions: tuple[Decimal, ...]
    field_kind: FieldKind
    storage: Literal["uniform", "nonuniform"]
    values: tuple[Value, ...]


@dataclass(frozen=True, slots=True)
class BoundaryExtremum:
    patch_local_index: int
    mesh_face_label: int
    value: Decimal


@dataclass(frozen=True, slots=True)
class BoundaryFieldReduction:
    source_path: str
    patch_name: str
    entry_name: str
    operation: ReductionOperation
    component: str
    component_index: int
    selected_face_count: int
    comparison_value: Decimal
    extrema: tuple[BoundaryExtremum, ...]


@dataclass(frozen=True, slots=True)
class MeshPrimitiveSource:
    """One primitive selected for a modeled time, with exact provenance."""

    name: MeshPrimitiveName
    relative_path: str
    instance: str
    instance_time: Decimal | None


@dataclass(frozen=True, slots=True)
class MeshResolution:
    """A per-primitive mesh resolution bound to one result root and time."""

    result_root: str
    modeled_time: Decimal
    time_directory: str
    primitive_sources: tuple[MeshPrimitiveSource, ...]


@dataclass(frozen=True, slots=True)
class CellSelectionContext:
    """The immutable spatial/temporal domain of one selected cell field."""

    mesh: MeshResolution
    zone_name: str
    cell_zones_source: str
    zone_cell_labels: tuple[int, ...]
    zone_face_labels: tuple[int, ...]
    zone_face_centres: tuple[tuple[int, Point], ...]
    zone_vertex_points: tuple[tuple[int, Point], ...]


@dataclass(frozen=True, slots=True)
class CellFieldSelection:
    """One field component selected over an exact, provenance-bound cell zone."""

    context: CellSelectionContext
    source_path: str
    field_selector: str
    object_name: str
    class_name: str
    dimensions: tuple[Decimal, ...]
    field_kind: FieldKind
    storage: Literal["uniform", "nonuniform"]
    component: str
    component_index: int
    records: tuple[CellScalarValue, ...]
    volumes: tuple[Decimal, ...]


@dataclass(frozen=True, slots=True)
class VolumeWeightedMean:
    selected_cell_count: int
    total_volume: Decimal
    value: Decimal


@dataclass(frozen=True, slots=True)
class VolumeWeightedRatio:
    selected_cell_count: int
    numerator: Decimal
    denominator: Decimal
    value: Decimal


@dataclass(frozen=True, slots=True)
class ZoneAxisBin:
    index: int
    lower: Decimal
    upper: Decimal
    upper_inclusive: bool
    cell_labels: tuple[int, ...]
    total_volume: Decimal
    weighted_mean: Decimal | None


@dataclass(frozen=True, slots=True)
class ZoneBinnedMean:
    axis: Axis
    lower: Decimal
    upper: Decimal
    bins: tuple[ZoneAxisBin, ...]


@dataclass(frozen=True, slots=True)
class BoundarySelectionContext:
    """The immutable domain shared by exact boundary-patch field selections."""

    mesh: MeshResolution
    owner_zone_name: str
    cell_zones_source: str
    boundary_source: str


@dataclass(frozen=True, slots=True)
class BoundaryFaceScalarValue:
    patch_name: str
    patch_local_index: int
    mesh_face_label: int
    owner_cell_label: int
    value: Decimal


@dataclass(frozen=True, slots=True)
class BoundaryFieldSelection:
    """One exact patch component with owner-zone and mesh provenance."""

    context: BoundarySelectionContext
    source_path: str
    field_selector: str
    object_name: str
    class_name: str
    dimensions: tuple[Decimal, ...]
    field_kind: FieldKind
    storage: Literal["uniform", "nonuniform"]
    entry_name: str
    patch_topology: BoundaryPatchTopology
    component: str
    component_index: int
    records: tuple[BoundaryFaceScalarValue, ...]


type FieldSelection = CellFieldSelection | BoundaryFieldSelection


@dataclass(frozen=True, slots=True)
class FieldTimeRow:
    """One exact modeled time with every input field column kept in order."""

    modeled_time: Decimal
    selections: tuple[FieldSelection | None, ...]


@dataclass(frozen=True, slots=True)
class ModeledTimeResult[T]:
    """One derived result bound to its exact modeled time."""

    modeled_time: Decimal
    result: T


@dataclass(frozen=True, slots=True)
class ModeledTimeResultRow:
    """One exact modeled time with every derived-result column kept in order."""

    modeled_time: Decimal
    results: tuple[object | None, ...]


@dataclass(frozen=True, slots=True)
class MultiBoundaryFieldReduction:
    source_path: str
    patch_names: tuple[str, ...]
    owner_zone_names: tuple[str, ...]
    entry_name: str
    operation: ReductionOperation
    component: str
    component_index: int
    selected_face_count: int
    comparison_value: Decimal
    extrema: tuple[BoundaryFaceScalarValue, ...]


@dataclass(frozen=True, slots=True)
class ModeledTimeExtrema[T]:
    """One temporal extremum with every exact tied time and spatial result."""

    operation: ReductionOperation
    comparison_value: Decimal
    extrema: tuple[ModeledTimeResult[T], ...]


@dataclass(frozen=True, slots=True)
class Token:
    text: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class FoamField:
    source_path: str
    object_name: str
    class_name: str
    dimensions: tuple[Decimal, ...]
    field_kind: FieldKind
    storage: Literal["uniform", "nonuniform"]
    values: tuple[Value, ...]


@dataclass(frozen=True, slots=True)
class ProbeLocation:
    index: int
    coordinates: tuple[Decimal, Decimal, Decimal]


@dataclass(frozen=True, slots=True)
class ProbeRecord:
    modeled_time: Decimal
    values: tuple[Value, ...]
    segment_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProbeSeries:
    field_name: str
    locations: tuple[ProbeLocation, ...]
    component_width: int
    records: tuple[ProbeRecord, ...]
    parsed_source_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ProbeSegment:
    locations: tuple[ProbeLocation, ...]
    component_width: int
    records: tuple[ProbeRecord, ...]


def _decimal(text: str, *, context: str) -> Decimal:
    token = text.strip()
    if not _NUMBER.fullmatch(token):
        raise OpenFOAMParseError(f"invalid finite number for {context}: {text!r}")
    try:
        value = Decimal(token)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise OpenFOAMParseError(f"invalid number for {context}: {text!r}") from exc
    if not value.is_finite():
        raise OpenFOAMParseError(f"non-finite number for {context}: {text!r}")
    return value


def _looks_like_bad_numeric_name(name: str) -> bool:
    stripped = name.strip()
    return bool(stripped and (stripped[0] in "+-.0123456789" or _NONFINITE.fullmatch(stripped)))


def discover_numeric_directories(parent: str | Path) -> tuple[NumericDirectory, ...]:
    """Return finite numeric child directories in numeric order.

    Ordinary names such as ``constant`` are ignored. Numeric-looking malformed
    names and two spellings of the same numeric time are rejected.
    """

    root = Path(parent)
    if not root.is_dir():
        raise OpenFOAMParseError(f"numeric-directory parent is not a directory: {root}")

    observed: list[NumericDirectory] = []
    by_value: dict[Decimal, str] = {}
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if not _NUMBER.fullmatch(entry.name):
            if _looks_like_bad_numeric_name(entry.name):
                raise OpenFOAMParseError(f"malformed numeric directory: {entry.name!r}")
            continue
        value = _decimal(entry.name, context="numeric directory")
        if value in by_value:
            raise OpenFOAMParseError(
                "duplicate numeric directories "
                f"{by_value[value]!r} and {entry.name!r} represent {value}"
            )
        by_value[value] = entry.name
        observed.append(NumericDirectory(entry.name, value, entry))

    observed.sort(key=lambda item: (item.value, item.name))
    return tuple(observed)


def validate_source_paths(result_root: str | Path, *source_paths: str | Path) -> tuple[str, ...]:
    """Bind existing read paths to one result root and return canonical relative paths."""

    root_input = Path(result_root)
    try:
        root = root_input.resolve(strict=True)
    except OSError as exc:
        raise OpenFOAMParseError(f"result root is absent or unresolved: {root_input}") from exc
    if not root.is_dir():
        raise OpenFOAMParseError(f"result root is not a directory: {root_input}")
    if not source_paths:
        raise OpenFOAMParseError("at least one source path is required")

    relative_paths: list[str] = []
    resolved_paths: set[Path] = set()
    for source_path in source_paths:
        supplied = Path(source_path)
        if ".." in supplied.parts:
            raise OpenFOAMParseError(f"source path contains a parent traversal: {supplied}")
        candidate = supplied if supplied.is_absolute() else root / supplied
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise OpenFOAMParseError(f"source path is absent or unresolved: {supplied}") from exc
        if not resolved.is_relative_to(root):
            raise OpenFOAMParseError(f"source path escapes the result root: {supplied}")
        if resolved in resolved_paths:
            raise OpenFOAMParseError(f"duplicate resolved source path: {supplied}")
        resolved_paths.add(resolved)
        relative_paths.append(resolved.relative_to(root).as_posix())
    return tuple(relative_paths)


def _selection_value(value: str | Decimal, *, context: str) -> Decimal:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise OpenFOAMParseError(f"non-finite number for {context}: {value!r}")
        return value
    if isinstance(value, str):
        return _decimal(value, context=context)
    raise OpenFOAMParseError(f"{context} must be supplied as a decimal string or Decimal")


def select_numeric_directory(
    parent: str | Path,
    *,
    exact: str | Decimal | None = None,
    latest: bool = False,
) -> NumericDirectory:
    """Select one exact or latest numeric directory without nearest matching."""

    if (exact is None) == (not latest):
        raise OpenFOAMParseError("select exactly one numeric-directory mode: exact or latest")
    directories = discover_numeric_directories(parent)
    if not directories:
        raise OpenFOAMParseError(f"no numeric directories below {Path(parent)}")
    if latest:
        latest_value = max(item.value for item in directories)
        matches = tuple(item for item in directories if item.value == latest_value)
    else:
        requested = _selection_value(exact, context="exact modeled time")  # type: ignore[arg-type]
        matches = tuple(item for item in directories if item.value == requested)
    if len(matches) != 1:
        requested_text = "latest" if latest else f"exact time {exact}"
        raise OpenFOAMParseError(
            f"{requested_text} must identify exactly one numeric directory; found {len(matches)}"
        )
    return matches[0]


def _canonical_result_root(result_root: str | Path) -> Path:
    supplied = Path(result_root)
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise OpenFOAMParseError(f"result root is absent or unresolved: {supplied}") from exc
    if not root.is_dir():
        raise OpenFOAMParseError(f"result root is not a directory: {supplied}")
    return root


def resolve_mesh_for_time(
    result_root: str | Path,
    *,
    exact: str | Decimal | None = None,
    latest: bool = False,
) -> MeshResolution:
    """Resolve every mesh primitive at or before one exact result time.

    ``constant/polyMesh`` is the baseline.  For each primitive independently,
    the latest numeric ``<time>/polyMesh`` override not later than the selected
    result time wins.  This supports moving meshes where a time instance replaces
    only ``points`` while topology remains in ``constant``.  Missing required
    geometry primitives, future-only primitives, ambiguous numeric spellings,
    and paths outside the result root fail closed.
    """

    root = _canonical_result_root(result_root)
    selected_time = select_numeric_directory(root, exact=exact, latest=latest)
    (time_directory,) = validate_source_paths(root, selected_time.path)
    if time_directory != selected_time.name:
        raise OpenFOAMParseError(
            "selected numeric directory is an alias for a different result instance"
        )
    numeric_directories = discover_numeric_directories(root)

    sources: list[MeshPrimitiveSource] = []
    for primitive in _MESH_PRIMITIVES:
        constant_path = root / "constant" / "polyMesh" / primitive
        selected = _mesh_primitive_source_if_present(
            root,
            primitive,
            constant_path,
            instance="constant",
            instance_time=None,
        )
        for directory in numeric_directories:
            if directory.value > selected_time.value:
                break
            candidate = directory.path / "polyMesh" / primitive
            event_source = _mesh_primitive_source_if_present(
                root,
                primitive,
                candidate,
                instance=directory.name,
                instance_time=directory.value,
            )
            if event_source is not None:
                selected = event_source
        if selected is None:
            if primitive in _REQUIRED_GEOMETRY_PRIMITIVES:
                raise OpenFOAMParseError(
                    f"mesh primitive {primitive!r} is absent at or before modeled time "
                    f"{selected_time.value}"
                )
            continue
        sources.append(selected)
    return MeshResolution(
        result_root=str(root),
        modeled_time=selected_time.value,
        time_directory=time_directory,
        primitive_sources=tuple(sources),
    )


def _mesh_primitive_source_if_present(
    root: Path,
    primitive: MeshPrimitiveName,
    path: Path,
    *,
    instance: str,
    instance_time: Decimal | None,
) -> MeshPrimitiveSource | None:
    """Return one canonical primitive, distinguishing absence from bad entries."""

    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise OpenFOAMParseError(
            f"cannot inspect mesh primitive {primitive!r} at {path}: {exc}"
        ) from exc
    if not path.is_file():
        raise OpenFOAMParseError(
            f"mesh primitive {primitive!r} is not a readable regular file: {path}"
        )
    (relative_path,) = validate_source_paths(root, path)
    expected_relative_path = f"{instance}/polyMesh/{primitive}"
    if relative_path != expected_relative_path:
        raise OpenFOAMParseError(
            f"mesh primitive {primitive!r} is an alias for a different mesh instance"
        )
    return MeshPrimitiveSource(primitive, relative_path, instance, instance_time)


def _resolve_mesh_for_directories(
    root: Path,
    directories: tuple[NumericDirectory, ...],
) -> tuple[MeshResolution, ...]:
    """Resolve a discovered numeric series in one monotonic primitive-state pass.

    Each mesh event is inspected and canonicalized once.  A primitive remains in
    force until a later numeric directory supplies an override, matching
    ``resolve_mesh_for_time`` without restarting its historical scan per time.
    """

    current_sources: dict[MeshPrimitiveName, MeshPrimitiveSource] = {}
    for primitive in _MESH_PRIMITIVES:
        source = _mesh_primitive_source_if_present(
            root,
            primitive,
            root / "constant" / "polyMesh" / primitive,
            instance="constant",
            instance_time=None,
        )
        if source is not None:
            current_sources[primitive] = source

    resolutions: list[MeshResolution] = []
    for directory in directories:
        (time_directory,) = validate_source_paths(root, directory.path)
        if time_directory != directory.name:
            raise OpenFOAMParseError(
                "selected numeric directory is an alias for a different result instance"
            )

        for primitive in _MESH_PRIMITIVES:
            source = _mesh_primitive_source_if_present(
                root,
                primitive,
                directory.path / "polyMesh" / primitive,
                instance=directory.name,
                instance_time=directory.value,
            )
            if source is not None:
                current_sources[primitive] = source

        for primitive in _REQUIRED_GEOMETRY_PRIMITIVES:
            if primitive not in current_sources:
                raise OpenFOAMParseError(
                    f"mesh primitive {primitive!r} is absent at or before modeled time "
                    f"{directory.value}"
                )
        resolutions.append(
            MeshResolution(
                result_root=str(root),
                modeled_time=directory.value,
                time_directory=time_directory,
                primitive_sources=tuple(
                    current_sources[primitive]
                    for primitive in _MESH_PRIMITIVES
                    if primitive in current_sources
                ),
            )
        )
    return tuple(resolutions)


def mesh_primitive_source(
    resolution: MeshResolution, primitive: MeshPrimitiveName
) -> MeshPrimitiveSource:
    """Return one exact primitive source from a mesh resolution."""

    if primitive not in _MESH_PRIMITIVES:
        raise OpenFOAMParseError(f"unsupported mesh primitive: {primitive!r}")
    matches = tuple(source for source in resolution.primitive_sources if source.name == primitive)
    if len(matches) != 1:
        raise OpenFOAMParseError(
            f"mesh primitive {primitive!r} must resolve exactly once; found {len(matches)}"
        )
    return matches[0]


def tokenize_openfoam(text: str, *, source_path: str = "<memory>") -> tuple[Token, ...]:
    """Tokenize OpenFOAM dictionaries while removing line and block comments."""

    tokens: list[Token] = []
    index = 0
    line = 1
    column = 1

    def advance(character: str) -> None:
        nonlocal line, column
        if character == "\n":
            line += 1
            column = 1
        else:
            column += 1

    while index < len(text):
        character = text[index]
        if character.isspace():
            advance(character)
            index += 1
            continue
        if text.startswith("//", index):
            while index < len(text) and text[index] != "\n":
                advance(text[index])
                index += 1
            continue
        if text.startswith("/*", index):
            start_line, start_column = line, column
            advance("/")
            advance("*")
            index += 2
            while index < len(text) and not text.startswith("*/", index):
                advance(text[index])
                index += 1
            if index == len(text):
                raise OpenFOAMParseError(
                    f"{source_path}:{start_line}:{start_column}: unterminated block comment"
                )
            advance("*")
            advance("/")
            index += 2
            continue

        start_line, start_column = line, column
        if character in _DELIMITERS:
            tokens.append(Token(character, line, column))
            advance(character)
            index += 1
            continue
        if character in "\"'":
            quote = character
            index += 1
            advance(character)
            value: list[str] = []
            while index < len(text) and text[index] != quote:
                if text[index] == "\\" and index + 1 < len(text):
                    value.append(text[index + 1])
                    advance(text[index])
                    advance(text[index + 1])
                    index += 2
                else:
                    value.append(text[index])
                    advance(text[index])
                    index += 1
            if index == len(text):
                raise OpenFOAMParseError(
                    f"{source_path}:{start_line}:{start_column}: unterminated quoted token"
                )
            advance(text[index])
            index += 1
            tokens.append(Token("".join(value), start_line, start_column))
            continue

        value = []
        while index < len(text):
            if text[index].isspace() or text[index] in _DELIMITERS:
                break
            if text.startswith("//", index) or text.startswith("/*", index):
                break
            value.append(text[index])
            advance(text[index])
            index += 1
        tokens.append(Token("".join(value), start_line, start_column))

    return tuple(tokens)


class _Cursor:
    def __init__(self, tokens: tuple[Token, ...], source_path: str) -> None:
        self.tokens = tokens
        self.source_path = source_path
        self.index = 0

    def take(self) -> Token:
        if self.index >= len(self.tokens):
            raise OpenFOAMParseError(f"{self.source_path}: unexpected end of file")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def expect(self, expected: str) -> Token:
        token = self.take()
        if token.text != expected:
            raise OpenFOAMParseError(
                f"{self.source_path}:{token.line}:{token.column}: "
                f"expected {expected!r}, found {token.text!r}"
            )
        return token


def _non_negative_decimal(token: Token, source_path: str, *, context: str) -> int:
    """Convert one OpenFOAM label token without leaking interpreter errors."""

    location = f"{source_path}:{token.line}:{token.column}"
    if not token.text.isdecimal():
        raise OpenFOAMParseError(f"{location}: invalid non-negative {context} {token.text!r}")
    normalized = token.text.lstrip("0") or "0"
    if len(normalized) > _MAX_OPENFOAM_LABEL_DIGITS:
        raise OpenFOAMParseError(
            f"{location}: non-negative {context} exceeds the supported "
            f"{_MAX_OPENFOAM_LABEL_DIGITS}-digit OpenFOAM label range"
        )
    try:
        value = int(normalized)
    except ValueError as exc:  # pragma: no cover - bounded decimal syntax is guarded above
        raise OpenFOAMParseError(
            f"{location}: invalid non-negative {context} {token.text!r}"
        ) from exc
    if value > _MAX_OPENFOAM_LABEL:
        raise OpenFOAMParseError(
            f"{location}: non-negative {context} exceeds the supported OpenFOAM label range"
        )
    return value


def _find(tokens: tuple[Token, ...], value: str, *, start: int = 0) -> int:
    for index in range(start, len(tokens)):
        if tokens[index].text == value:
            return index
    raise OpenFOAMParseError(f"required OpenFOAM entry {value!r} is absent")


def _parse_header(tokens: tuple[Token, ...], source_path: str) -> tuple[str, str]:
    foam_file = _find(tokens, "FoamFile")
    opening = foam_file + 1
    if opening >= len(tokens) or tokens[opening].text != "{":
        raise OpenFOAMParseError(f"{source_path}: malformed FoamFile header")
    closing = _matching_index(tokens, opening, "{", "}", source_path)
    _validate_balanced_delimiters(tokens, opening + 1, closing, source_path)

    entries: dict[str, str] = {}
    for key in ("format", "class", "object"):
        positions = _direct_key_positions(tokens, opening + 1, closing, key)
        if len(positions) != 1:
            raise OpenFOAMParseError(
                f"{source_path}: FoamFile header must define exactly one {key!r} entry"
            )
        cursor = _Cursor(tokens, source_path)
        cursor.index = positions[0] + 1
        entries[key] = cursor.take().text
        cursor.expect(";")
        if cursor.index > closing:
            raise OpenFOAMParseError(f"{source_path}: FoamFile entry {key!r} crosses header")

    if entries.get("format") != "ascii":
        raise OpenFOAMParseError(
            f"unsupported OpenFOAM format: {entries.get('format', '<missing>')!r}"
        )
    class_name = entries.get("class")
    object_name = entries.get("object")
    if not class_name or not object_name:
        raise OpenFOAMParseError("FoamFile header must define class and object")
    return class_name, object_name


def _matching_index(
    tokens: tuple[Token, ...], start: int, opening: str, closing: str, source_path: str
) -> int:
    if start >= len(tokens) or tokens[start].text != opening:
        raise OpenFOAMParseError(f"{source_path}: expected {opening!r}")
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].text == opening:
            depth += 1
        elif tokens[index].text == closing:
            depth -= 1
            if depth == 0:
                return index
    token = tokens[start]
    raise OpenFOAMParseError(
        f"{source_path}:{token.line}:{token.column}: unterminated {opening!r} block"
    )


def _validate_balanced_delimiters(
    tokens: tuple[Token, ...], start: int, end: int, source_path: str
) -> None:
    pairs = {"{": "}", "(": ")", "[": "]", "<": ">"}
    closing_to_opening = {closing: opening for opening, closing in pairs.items()}
    stack: list[Token] = []
    for token in tokens[start:end]:
        if token.text in pairs:
            stack.append(token)
        elif token.text in closing_to_opening:
            if not stack or stack[-1].text != closing_to_opening[token.text]:
                raise OpenFOAMParseError(
                    f"{source_path}:{token.line}:{token.column}: "
                    f"mismatched closing delimiter {token.text!r}"
                )
            stack.pop()
    if stack:
        token = stack[-1]
        raise OpenFOAMParseError(
            f"{source_path}:{token.line}:{token.column}: unterminated delimiter {token.text!r}"
        )


def _header_end(tokens: tuple[Token, ...], source_path: str) -> int:
    foam_file = _find(tokens, "FoamFile")
    opening = foam_file + 1
    if opening >= len(tokens) or tokens[opening].text != "{":
        raise OpenFOAMParseError(f"{source_path}: malformed FoamFile header")
    return _matching_index(tokens, opening, "{", "}", source_path)


def _ascii_tokens(text: str, source_path: str) -> tuple[Token, ...]:
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise OpenFOAMParseError(f"{source_path}: OpenFOAM file is not ASCII") from exc
    tokens = tokenize_openfoam(text, source_path=source_path)
    _parse_header(tokens, source_path)
    return tokens


def _read_ascii(path: str | Path, *, kind: str) -> str:
    source = Path(path)
    try:
        return source.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise OpenFOAMParseError(f"cannot read ASCII {kind} {source}: {exc}") from exc


def _counted_list_prefix(tokens: tuple[Token, ...], source_path: str) -> tuple[_Cursor, int, Token]:
    cursor = _Cursor(tokens, source_path)
    cursor.index = _header_end(tokens, source_path) + 1
    count_token = cursor.take()
    count = _non_negative_decimal(count_token, source_path, context="counted-list size")
    return cursor, count, count_token


def _counted_list_cursor(tokens: tuple[Token, ...], source_path: str) -> tuple[_Cursor, int]:
    cursor, count, _ = _counted_list_prefix(tokens, source_path)
    cursor.expect("(")
    return cursor, count


def _finish_counted_list(
    cursor: _Cursor, *, closing: str = ")", opening: Token | None = None
) -> None:
    if cursor.index >= len(cursor.tokens) and opening is not None:
        raise OpenFOAMParseError(
            f"{cursor.source_path}:{opening.line}:{opening.column}: "
            f"unterminated {opening.text!r} block"
        )
    cursor.expect(closing)
    if cursor.index < len(cursor.tokens) and cursor.tokens[cursor.index].text == ";":
        cursor.take()
    if cursor.index != len(cursor.tokens):
        token = cursor.tokens[cursor.index]
        raise OpenFOAMParseError(
            f"{cursor.source_path}:{token.line}:{token.column}: trailing counted-list content"
        )


def _direct_key_positions(
    tokens: tuple[Token, ...], start: int, end: int, key: str
) -> tuple[int, ...]:
    pairs = {"{": "}", "(": ")", "[": "]", "<": ">"}
    closing_to_opening = {closing: opening for opening, closing in pairs.items()}
    stack: list[str] = []
    matches: list[int] = []
    for index in range(start, end):
        token = tokens[index].text
        if token in pairs:
            stack.append(token)
        elif token in closing_to_opening:
            if stack and stack[-1] == closing_to_opening[token]:
                stack.pop()
        elif not stack and token == key:
            matches.append(index)
    return tuple(matches)


def _unique_body_key_position(tokens: tuple[Token, ...], key: str, source_path: str) -> int:
    start = _header_end(tokens, source_path) + 1
    _validate_balanced_delimiters(tokens, start, len(tokens), source_path)
    positions = _direct_key_positions(tokens, start, len(tokens), key)
    if len(positions) != 1:
        raise OpenFOAMParseError(
            f"{source_path}: field body must define exactly one top-level {key!r} entry"
        )
    return positions[0]


def _parse_label_entry(
    tokens: tuple[Token, ...], position: int, end: int, source_path: str
) -> tuple[int, ...]:
    cursor = _Cursor(tokens, source_path)
    cursor.index = position + 1
    cursor.expect("List")
    cursor.expect("<")
    cursor.expect("label")
    cursor.expect(">")
    count_token = cursor.take()
    count = _non_negative_decimal(count_token, source_path, context="cellLabels count")
    cursor.expect("(")
    labels: list[int] = []
    for _ in range(count):
        label_token = cursor.take()
        labels.append(_non_negative_decimal(label_token, source_path, context="cell label"))
    cursor.expect(")")
    cursor.expect(";")
    if cursor.index > end:
        raise OpenFOAMParseError(f"{source_path}: cellLabels entry crosses its zone dictionary")
    if len(set(labels)) != len(labels):
        raise OpenFOAMParseError(f"{source_path}: cellLabels contains duplicate labels")
    if not labels:
        raise OpenFOAMParseError(f"{source_path}: cell zone must not be empty")
    return tuple(labels)


def parse_cell_zones_text(text: str, *, source_path: str = "<memory>") -> tuple[CellZone, ...]:
    """Parse exact cell-zone names and labels from an ASCII ``cellZones`` file."""

    tokens = _ascii_tokens(text, source_path)
    _, object_name = _parse_header(tokens, source_path)
    if object_name != "cellZones":
        raise OpenFOAMParseError(
            f"{source_path}: expected FoamFile object 'cellZones', found {object_name!r}"
        )
    cursor, count = _counted_list_cursor(tokens, source_path)
    zones: list[CellZone] = []
    observed_names: set[str] = set()
    for _ in range(count):
        name = cursor.take().text
        if name in _DELIMITERS or not name:
            raise OpenFOAMParseError(f"{source_path}: invalid cell-zone name {name!r}")
        if name in observed_names:
            raise OpenFOAMParseError(f"{source_path}: duplicate cell-zone name {name!r}")
        observed_names.add(name)
        opening = cursor.index
        cursor.expect("{")
        closing = _matching_index(tokens, opening, "{", "}", source_path)
        positions = _direct_key_positions(tokens, opening + 1, closing, "cellLabels")
        if len(positions) != 1:
            raise OpenFOAMParseError(
                f"{source_path}: zone {name!r} must define exactly one cellLabels entry"
            )
        labels = _parse_label_entry(tokens, positions[0], closing, source_path)
        zones.append(CellZone(name, labels))
        cursor.index = closing + 1
    _finish_counted_list(cursor)
    return tuple(zones)


def parse_cell_zones(path: str | Path) -> tuple[CellZone, ...]:
    source = Path(path)
    return parse_cell_zones_text(
        _read_ascii(source, kind="cellZones file"), source_path=str(source)
    )


def cell_labels_for_zone(path: str | Path, zone_name: str) -> tuple[int, ...]:
    """Return labels for one exact, uniquely named, non-empty cell zone."""

    matches = tuple(zone for zone in parse_cell_zones(path) if zone.name == zone_name)
    if len(matches) != 1:
        raise OpenFOAMParseError(
            f"cell zone {zone_name!r} must match exactly once; found {len(matches)}"
        )
    return matches[0].cell_labels


def _unique_integer_entry(
    tokens: tuple[Token, ...],
    start: int,
    end: int,
    key: str,
    source_path: str,
) -> int:
    positions = _direct_key_positions(tokens, start, end, key)
    if len(positions) != 1:
        raise OpenFOAMParseError(
            f"{source_path}: boundary patch must define exactly one {key!r} entry"
        )
    cursor = _Cursor(tokens, source_path)
    cursor.index = positions[0] + 1
    value_token = cursor.take()
    value = _non_negative_decimal(
        value_token,
        source_path,
        context=f"boundary patch {key!r} integer",
    )
    cursor.expect(";")
    if cursor.index > end:
        raise OpenFOAMParseError(f"{source_path}: boundary patch {key!r} crosses its dictionary")
    return value


def _token_entry(
    tokens: tuple[Token, ...],
    start: int,
    end: int,
    key: str,
    source_path: str,
    *,
    required: bool,
) -> str | None:
    positions = _direct_key_positions(tokens, start, end, key)
    expected = "exactly one" if required else "at most one"
    if (required and len(positions) != 1) or (not required and len(positions) > 1):
        raise OpenFOAMParseError(
            f"{source_path}: boundary patch must define {expected} {key!r} entry"
        )
    if not positions:
        return None
    cursor = _Cursor(tokens, source_path)
    cursor.index = positions[0] + 1
    value = cursor.take().text
    if not value or value in _DELIMITERS:
        raise OpenFOAMParseError(
            f"{source_path}: boundary patch {key!r} has an invalid token value"
        )
    cursor.expect(";")
    if cursor.index > end:
        raise OpenFOAMParseError(f"{source_path}: boundary patch {key!r} crosses its dictionary")
    return value


def _optional_bool_entry(
    tokens: tuple[Token, ...], start: int, end: int, key: str, source_path: str
) -> bool | None:
    value = _token_entry(tokens, start, end, key, source_path, required=False)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise OpenFOAMParseError(
        f"{source_path}: boundary patch {key!r} must be exactly 'true' or 'false'"
    )


def parse_boundary_patches_text(
    text: str, *, source_path: str = "<memory>"
) -> tuple[BoundaryPatchTopology, ...]:
    """Parse exact patch names, face counts, and start faces from ``polyMesh/boundary``."""

    tokens = _ascii_tokens(text, source_path)
    _, object_name = _parse_header(tokens, source_path)
    if object_name != "boundary":
        raise OpenFOAMParseError(
            f"{source_path}: expected FoamFile object 'boundary', found {object_name!r}"
        )
    cursor, count = _counted_list_cursor(tokens, source_path)
    patches: list[BoundaryPatchTopology] = []
    observed_names: set[str] = set()
    for _ in range(count):
        name = cursor.take().text
        if name in _DELIMITERS or not name:
            raise OpenFOAMParseError(f"{source_path}: invalid boundary-patch name {name!r}")
        if name in observed_names:
            raise OpenFOAMParseError(f"{source_path}: duplicate boundary-patch name {name!r}")
        observed_names.add(name)
        opening = cursor.index
        cursor.expect("{")
        closing = _matching_index(tokens, opening, "{", "}", source_path)
        patch_type = _token_entry(tokens, opening + 1, closing, "type", source_path, required=True)
        n_faces = _unique_integer_entry(tokens, opening + 1, closing, "nFaces", source_path)
        start_face = _unique_integer_entry(tokens, opening + 1, closing, "startFace", source_path)
        owner = _optional_bool_entry(tokens, opening + 1, closing, "owner", source_path)
        neighbour_patch = _token_entry(
            tokens,
            opening + 1,
            closing,
            "neighbourPatch",
            source_path,
            required=False,
        )
        if n_faces == 0:
            raise OpenFOAMParseError(f"{source_path}: boundary patch {name!r} is empty")
        patches.append(
            BoundaryPatchTopology(
                name,
                n_faces,
                start_face,
                patch_type=patch_type,
                owner=owner,
                neighbour_patch=neighbour_patch,
            )
        )
        cursor.index = closing + 1
    _finish_counted_list(cursor)
    return tuple(patches)


def parse_boundary_patches(path: str | Path) -> tuple[BoundaryPatchTopology, ...]:
    source = Path(path)
    return parse_boundary_patches_text(
        _read_ascii(source, kind="polyMesh boundary file"), source_path=str(source)
    )


def boundary_patch_topology(boundary_path: str | Path, patch_name: str) -> BoundaryPatchTopology:
    """Return topology for one exact, uniquely named, non-empty boundary patch."""

    matches = tuple(
        patch for patch in parse_boundary_patches(boundary_path) if patch.name == patch_name
    )
    if len(matches) != 1:
        raise OpenFOAMParseError(
            f"boundary patch {patch_name!r} must match exactly once; found {len(matches)}"
        )
    return matches[0]


def validate_reciprocal_boundary_pair(
    first: BoundaryPatchTopology, second: BoundaryPatchTopology
) -> tuple[BoundaryPatchTopology, BoundaryPatchTopology]:
    """Validate reciprocal nonconformal metadata and return ``(owner, neighbour)``.

    Face counts are deliberately allowed to differ.  The function validates only
    metadata reciprocity and owner-side designation; it never pairs face indices.
    """

    if not first.name or not second.name or first.name == second.name:
        raise OpenFOAMParseError("reciprocal boundary patches must have two distinct names")
    if not first.patch_type or not second.patch_type or first.patch_type != second.patch_type:
        raise OpenFOAMParseError(
            "reciprocal boundary patches must have one exact matching non-empty type"
        )
    if first.neighbour_patch != second.name or second.neighbour_patch != first.name:
        raise OpenFOAMParseError("boundary neighbourPatch metadata is not reciprocal")
    if type(first.owner) is not bool or type(second.owner) is not bool:
        raise OpenFOAMParseError("reciprocal boundary owner metadata must use exact booleans")
    if first.owner is second.owner:
        raise OpenFOAMParseError(
            "reciprocal boundary patches must designate exactly one owner side"
        )
    return (first, second) if first.owner else (second, first)


def owner_side_boundary_patch(
    first: BoundaryPatchTopology, second: BoundaryPatchTopology
) -> BoundaryPatchTopology:
    """Return the metadata-declared owner side of one reciprocal patch pair."""

    owner, _ = validate_reciprocal_boundary_pair(first, second)
    return owner


def parse_points_text(text: str, *, source_path: str = "<memory>") -> tuple[Point, ...]:
    tokens = _ascii_tokens(text, source_path)
    _, object_name = _parse_header(tokens, source_path)
    if object_name != "points":
        raise OpenFOAMParseError(
            f"{source_path}: expected FoamFile object 'points', found {object_name!r}"
        )
    cursor, count = _counted_list_cursor(tokens, source_path)
    if count == 0:
        raise OpenFOAMParseError(f"{source_path}: points list must not be empty")
    points = tuple(_parse_parenthesized_value(cursor, 3, "polyMesh point") for _ in range(count))
    _finish_counted_list(cursor)
    return points  # type: ignore[return-value]


def parse_points(path: str | Path) -> tuple[Point, ...]:
    source = Path(path)
    return parse_points_text(_read_ascii(source, kind="points file"), source_path=str(source))


def parse_faces_text(text: str, *, source_path: str = "<memory>") -> tuple[Face, ...]:
    tokens = _ascii_tokens(text, source_path)
    _, object_name = _parse_header(tokens, source_path)
    if object_name != "faces":
        raise OpenFOAMParseError(
            f"{source_path}: expected FoamFile object 'faces', found {object_name!r}"
        )
    cursor, count = _counted_list_cursor(tokens, source_path)
    if count == 0:
        raise OpenFOAMParseError(f"{source_path}: faces list must not be empty")
    faces: list[Face] = []
    for _ in range(count):
        width_token = cursor.take()
        width = _non_negative_decimal(width_token, source_path, context="face width")
        if width < 3:
            raise OpenFOAMParseError(
                f"{source_path}:{width_token.line}:{width_token.column}: "
                f"invalid face width {width_token.text!r}"
            )
        cursor.expect("(")
        vertices: list[int] = []
        for _ in range(width):
            vertex_token = cursor.take()
            vertices.append(_non_negative_decimal(vertex_token, source_path, context="point label"))
        cursor.expect(")")
        if len(set(vertices)) != len(vertices):
            raise OpenFOAMParseError(f"{source_path}: face repeats a point label")
        faces.append(tuple(vertices))
    _finish_counted_list(cursor)
    return tuple(faces)


def parse_faces(path: str | Path) -> tuple[Face, ...]:
    source = Path(path)
    return parse_faces_text(_read_ascii(source, kind="faces file"), source_path=str(source))


def _validated_label_list_bound(value: int | None, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenFOAMParseError(f"{name} must be a non-negative integer")
    if value > _MAX_OPENFOAM_LABEL:
        raise OpenFOAMParseError(f"{name} exceeds the supported OpenFOAM label range")
    return value


def parse_label_list_text(
    text: str,
    *,
    expected_object: str,
    source_path: str = "<memory>",
    expected_count: int | None = None,
    maximum_count: int | None = None,
    compact_limit: int = DEFAULT_COMPACT_LABEL_LIST_LIMIT,
) -> tuple[int, ...]:
    """Parse one ASCII labelList with optional pre-allocation count constraints."""

    expected_count = _validated_label_list_bound(expected_count, name="expected_count")
    maximum_count = _validated_label_list_bound(maximum_count, name="maximum_count")
    validated_compact_limit = _validated_label_list_bound(compact_limit, name="compact_limit")
    if validated_compact_limit is None:
        raise OpenFOAMParseError("compact_limit must be a non-negative integer")
    if expected_count is not None and maximum_count is not None and expected_count > maximum_count:
        raise OpenFOAMParseError("expected_count must not exceed maximum_count")

    tokens = _ascii_tokens(text, source_path)
    _, object_name = _parse_header(tokens, source_path)
    if object_name != expected_object:
        raise OpenFOAMParseError(
            f"{source_path}: expected FoamFile object {expected_object!r}, found {object_name!r}"
        )
    cursor, count, count_token = _counted_list_prefix(tokens, source_path)
    count_location = f"{source_path}:{count_token.line}:{count_token.column}"
    if expected_count is not None and count != expected_count:
        raise OpenFOAMParseError(
            f"{count_location}: {expected_object} labelList size {count} does not match "
            f"expected count {expected_count}"
        )
    if maximum_count is not None and count > maximum_count:
        raise OpenFOAMParseError(
            f"{count_location}: {expected_object} labelList size {count} exceeds "
            f"maximum count {maximum_count}"
        )
    opening = cursor.take()
    if opening.text not in {"(", "{"}:
        raise OpenFOAMParseError(
            f"{source_path}:{opening.line}:{opening.column}: "
            f"expected '(' or '{{', found {opening.text!r}"
        )

    def take_label() -> int:
        label_token = cursor.take()
        return _non_negative_decimal(label_token, source_path, context="mesh label")

    if opening.text == "(":
        labels = tuple(take_label() for _ in range(count))
        _finish_counted_list(cursor)
        return labels

    if count > validated_compact_limit:
        raise OpenFOAMParseError(
            f"{count_location}: compact labelList size {count} exceeds expansion limit "
            f"{validated_compact_limit}"
        )

    if count == 0:
        _finish_counted_list(cursor, closing="}", opening=opening)
        return ()

    if cursor.index >= len(cursor.tokens):
        _finish_counted_list(cursor, closing="}", opening=opening)
    label = take_label()
    _finish_counted_list(cursor, closing="}", opening=opening)
    try:
        return (label,) * count
    except (MemoryError, OverflowError) as exc:
        raise OpenFOAMParseError(
            f"{count_location}: compact labelList size {count} cannot be represented"
        ) from exc


def parse_label_list(
    path: str | Path,
    *,
    expected_object: str,
    expected_count: int | None = None,
    maximum_count: int | None = None,
    compact_limit: int = DEFAULT_COMPACT_LABEL_LIST_LIMIT,
) -> tuple[int, ...]:
    source = Path(path)
    return parse_label_list_text(
        _read_ascii(source, kind=f"{expected_object} file"),
        expected_object=expected_object,
        source_path=str(source),
        expected_count=expected_count,
        maximum_count=maximum_count,
        compact_limit=compact_limit,
    )


def boundary_patch_owner_cell_labels(
    topology: BoundaryPatchTopology,
    owner: tuple[int, ...],
    zone_labels: tuple[int, ...],
) -> tuple[int, ...]:
    """Map one exact patch face range to owner cells and require one exact zone."""

    if (
        not topology.name
        or isinstance(topology.n_faces, bool)
        or not isinstance(topology.n_faces, int)
        or topology.n_faces <= 0
        or isinstance(topology.start_face, bool)
        or not isinstance(topology.start_face, int)
        or topology.start_face < 0
    ):
        raise OpenFOAMParseError("boundary topology contains an invalid face range")
    if not zone_labels or len(set(zone_labels)) != len(zone_labels):
        raise OpenFOAMParseError("exact owner zone must be non-empty and contain unique labels")
    if any(
        isinstance(label, bool) or not isinstance(label, int) or label < 0 for label in zone_labels
    ):
        raise OpenFOAMParseError("exact owner zone contains an invalid cell label")
    if any(isinstance(label, bool) or not isinstance(label, int) or label < 0 for label in owner):
        raise OpenFOAMParseError("owner contains an invalid cell label")
    end_face = topology.start_face + topology.n_faces
    if end_face > len(owner):
        raise OpenFOAMParseError(
            f"boundary patch {topology.name!r} face range exceeds owner count {len(owner)}"
        )
    patch_owners = owner[topology.start_face : end_face]
    zone_set = set(zone_labels)
    outside = tuple(sorted(set(patch_owners) - zone_set))
    if outside:
        raise OpenFOAMParseError(
            f"boundary patch {topology.name!r} has owner cells outside exact zone: {outside}"
        )
    return patch_owners


def owner_cell_labels_for_boundary_patch(
    boundary_path: str | Path,
    owner_path: str | Path,
    cell_zones_path: str | Path,
    *,
    patch_name: str,
    zone_name: str,
) -> tuple[int, ...]:
    """Resolve exact path selectors and return patch-local owner cell labels."""

    topology = boundary_patch_topology(boundary_path, patch_name)
    owner = parse_label_list(owner_path, expected_object="owner")
    zone_labels = cell_labels_for_zone(cell_zones_path, zone_name)
    return boundary_patch_owner_cell_labels(topology, owner, zone_labels)


def _point_add(left: Point, right: Point) -> Point:
    return tuple(left[index] + right[index] for index in range(3))  # type: ignore[return-value]


def _point_subtract(left: Point, right: Point) -> Point:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def _point_scale(value: Point, scale: Decimal) -> Point:
    return tuple(component * scale for component in value)  # type: ignore[return-value]


def _validated_point(point: Point, *, context: str) -> Point:
    if (
        not isinstance(point, tuple)
        or len(point) != 3
        or any(not isinstance(value, Decimal) or not value.is_finite() for value in point)
    ):
        raise OpenFOAMParseError(f"{context} must be a finite three-component Decimal point")
    return point


def point_axis_coordinate(point: Point, *, axis: Axis) -> Decimal:
    """Project one exact point onto a caller-selected Cartesian axis."""

    point = _validated_point(point, context="point")
    try:
        index = {"x": 0, "y": 1, "z": 2}[axis]
    except (KeyError, TypeError) as exc:
        raise OpenFOAMParseError(f"unsupported Cartesian axis: {axis!r}") from exc
    return point[index]


def point_distance(point: Point, *, origin: Point) -> Decimal:
    """Return Euclidean distance from one explicit origin using Decimal arithmetic."""

    point = _validated_point(point, context="point")
    origin = _validated_point(origin, context="origin")
    squared = sum(
        ((value - reference) ** 2 for value, reference in zip(point, origin, strict=True)),
        Decimal(0),
    )
    distance = squared.sqrt()
    if not distance.is_finite():
        raise OpenFOAMParseError("point distance is non-finite")
    return distance


def point_radial_distance(point: Point, *, axis: Axis, origin: Point) -> Decimal:
    """Return distance from an explicit Cartesian axis through ``origin``."""

    point = _validated_point(point, context="point")
    origin = _validated_point(origin, context="origin")
    try:
        axial_index = {"x": 0, "y": 1, "z": 2}[axis]
    except (KeyError, TypeError) as exc:
        raise OpenFOAMParseError(f"unsupported Cartesian axis: {axis!r}") from exc
    squared = sum(
        ((point[index] - origin[index]) ** 2 for index in range(3) if index != axial_index),
        Decimal(0),
    )
    distance = squared.sqrt()
    if not distance.is_finite():
        raise OpenFOAMParseError("radial distance is non-finite")
    return distance


def _dot(left: Point, right: Point) -> Decimal:
    return sum((left[index] * right[index] for index in range(3)), start=Decimal(0))


def _cross(left: Point, right: Point) -> Point:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _mean_points(points: tuple[Point, ...]) -> Point:
    if not points:
        raise OpenFOAMParseError("cannot average an empty point sequence")
    total: Point = (Decimal(0), Decimal(0), Decimal(0))
    for point in points:
        total = _point_add(total, point)
    return _point_scale(total, Decimal(1) / Decimal(len(points)))


def _face_centre_and_area(
    points: tuple[Point, ...], face: Face, *, face_label: int
) -> tuple[Point, Point]:
    vertices = tuple(points[label] for label in face)
    if len(vertices) == 3:
        centre = _mean_points(vertices)
        area = _point_scale(
            _cross(
                _point_subtract(vertices[1], vertices[0]),
                _point_subtract(vertices[2], vertices[0]),
            ),
            Decimal("0.5"),
        )
    else:
        estimate = _mean_points(vertices)
        sum_normal: Point = (Decimal(0), Decimal(0), Decimal(0))
        sum_area = Decimal(0)
        sum_area_centres: Point = (Decimal(0), Decimal(0), Decimal(0))
        for index, current in enumerate(vertices):
            following = vertices[(index + 1) % len(vertices)]
            normal = _cross(
                _point_subtract(following, current),
                _point_subtract(estimate, current),
            )
            magnitude = _dot(normal, normal).sqrt()
            sum_normal = _point_add(sum_normal, normal)
            sum_area += magnitude
            triangle_centre_times_three = _point_add(_point_add(current, following), estimate)
            sum_area_centres = _point_add(
                sum_area_centres,
                _point_scale(triangle_centre_times_three, magnitude),
            )
        if sum_area == 0:
            centre = estimate
            area = (Decimal(0), Decimal(0), Decimal(0))
        else:
            centre = _point_scale(sum_area_centres, Decimal(1) / (Decimal(3) * sum_area))
            area = _point_scale(sum_normal, Decimal("0.5"))
    return centre, area


def reconstruct_poly_mesh_geometry(
    points: tuple[Point, ...],
    faces: tuple[Face, ...],
    owner: tuple[int, ...],
    neighbour: tuple[int, ...],
) -> PolyMeshGeometry:
    """Reconstruct OpenFOAM cell centres and volumes from primitive mesh topology.

    This follows OpenFOAM's face-centre/face-pyramid algorithm. It never uses a
    vertex mean, layer midpoint, probe coordinate, or material-interface point.
    """

    if not points or not faces:
        raise OpenFOAMParseError("polyMesh points and faces must not be empty")
    if len(owner) != len(faces):
        raise OpenFOAMParseError(f"owner count {len(owner)} does not match face count {len(faces)}")
    if len(neighbour) > len(faces):
        raise OpenFOAMParseError("neighbour count exceeds face count")
    all_cell_labels = owner + neighbour
    if not all_cell_labels:
        raise OpenFOAMParseError("polyMesh topology contains no cell labels")
    if any(isinstance(label, bool) or not isinstance(label, int) or label < 0 for label in owner):
        raise OpenFOAMParseError("owner contains an invalid cell label")
    if any(
        isinstance(label, bool) or not isinstance(label, int) or label < 0 for label in neighbour
    ):
        raise OpenFOAMParseError("neighbour contains an invalid cell label")
    for face_label, face in enumerate(faces):
        if len(face) < 3 or len(set(face)) != len(face):
            raise OpenFOAMParseError(f"polyMesh face {face_label} is malformed")
        if any(point_label < 0 or point_label >= len(points) for point_label in face):
            raise OpenFOAMParseError(f"polyMesh face {face_label} has an out-of-range point label")
    for face_label, cell_label in enumerate(neighbour):
        if owner[face_label] == cell_label:
            raise OpenFOAMParseError(f"internal face {face_label} has the same owner and neighbour")

    cell_count = max(all_cell_labels) + 1
    if set(all_cell_labels) != set(range(cell_count)):
        raise OpenFOAMParseError("polyMesh cell labels are not contiguous from zero")

    face_centres: list[Point] = []
    face_areas: list[Point] = []
    for face_label, face in enumerate(faces):
        centre, area = _face_centre_and_area(points, face, face_label=face_label)
        face_centres.append(centre)
        face_areas.append(area)

    cell_faces: list[list[tuple[int, bool]]] = [[] for _ in range(cell_count)]
    for face_label, cell_label in enumerate(owner):
        cell_faces[cell_label].append((face_label, True))
    for face_label, cell_label in enumerate(neighbour):
        cell_faces[cell_label].append((face_label, False))

    estimates: list[Point] = []
    for cell_label, memberships in enumerate(cell_faces):
        if len(memberships) < 4:
            raise OpenFOAMParseError(f"polyMesh cell {cell_label} has fewer than four faces")
        oriented_edge_counts: dict[tuple[int, int], tuple[int, int]] = {}
        for face_label, is_owner in memberships:
            vertices = faces[face_label] if is_owner else tuple(reversed(faces[face_label]))
            for index, start in enumerate(vertices):
                end = vertices[(index + 1) % len(vertices)]
                edge = (min(start, end), max(start, end))
                count, balance = oriented_edge_counts.get(edge, (0, 0))
                direction = 1 if start < end else -1
                oriented_edge_counts[edge] = (count + 1, balance + direction)
        if any(count != 2 or balance != 0 for count, balance in oriented_edge_counts.values()):
            raise OpenFOAMParseError(
                f"polyMesh cell {cell_label} does not form a closed consistently oriented surface"
            )
        estimates.append(
            _mean_points(tuple(face_centres[face_label] for face_label, _ in memberships))
        )

    cell_centres: list[Point] = []
    cell_volumes: list[Decimal] = []
    for cell_label, memberships in enumerate(cell_faces):
        estimate = estimates[cell_label]
        volume_times_three = Decimal(0)
        weighted_centre: Point = (Decimal(0), Decimal(0), Decimal(0))
        for face_label, is_owner in memberships:
            face_centre = face_centres[face_label]
            face_area = face_areas[face_label]
            height = (
                _point_subtract(face_centre, estimate)
                if is_owner
                else _point_subtract(estimate, face_centre)
            )
            pyramid_volume_times_three = _dot(face_area, height)
            pyramid_centre = _point_add(
                _point_scale(face_centre, Decimal("0.75")),
                _point_scale(estimate, Decimal("0.25")),
            )
            weighted_centre = _point_add(
                weighted_centre,
                _point_scale(pyramid_centre, pyramid_volume_times_three),
            )
            volume_times_three += pyramid_volume_times_three
        if volume_times_three <= 0:
            raise OpenFOAMParseError(
                f"polyMesh cell {cell_label} has non-positive reconstructed volume"
            )
        cell_centres.append(_point_scale(weighted_centre, Decimal(1) / volume_times_three))
        cell_volumes.append(volume_times_three / Decimal(3))
    return PolyMeshGeometry(tuple(cell_centres), tuple(cell_volumes))


def load_poly_mesh_geometry(poly_mesh_directory: str | Path) -> PolyMeshGeometry:
    directory = Path(poly_mesh_directory)
    if not directory.is_dir():
        raise OpenFOAMParseError(f"polyMesh directory is absent: {directory}")
    points = parse_points(directory / "points")
    faces = parse_faces(directory / "faces")
    face_count = len(faces)
    owner = parse_label_list(
        directory / "owner",
        expected_object="owner",
        expected_count=face_count,
        compact_limit=face_count,
    )
    neighbour = parse_label_list(
        directory / "neighbour",
        expected_object="neighbour",
        maximum_count=face_count,
        compact_limit=face_count,
    )
    return reconstruct_poly_mesh_geometry(points, faces, owner, neighbour)


def _require_current_mesh_resolution(resolution: MeshResolution) -> MeshResolution:
    if not isinstance(resolution, MeshResolution):
        raise OpenFOAMParseError("mesh resolution must be produced by resolve_mesh_for_time")
    if not isinstance(resolution.modeled_time, Decimal) or not resolution.modeled_time.is_finite():
        raise OpenFOAMParseError("mesh resolution has an invalid modeled time")
    expected = resolve_mesh_for_time(
        resolution.result_root,
        exact=resolution.modeled_time,
    )
    if resolution != expected:
        raise OpenFOAMParseError(
            "mesh resolution is stale, incomplete, or not the deterministic resolution "
            "for its result root and modeled time"
        )
    return resolution


def _resolved_primitive_path(resolution: MeshResolution, primitive: MeshPrimitiveName) -> Path:
    source = mesh_primitive_source(resolution, primitive)
    root = _canonical_result_root(resolution.result_root)
    (relative_path,) = validate_source_paths(root, source.relative_path)
    if relative_path != source.relative_path:
        raise OpenFOAMParseError(f"mesh primitive {primitive!r} provenance is not canonical")
    return root / relative_path


def load_resolved_poly_mesh_geometry(resolution: MeshResolution) -> PolyMeshGeometry:
    """Load geometry from one current deterministic per-primitive resolution."""

    points, faces, owner, neighbour = _load_resolved_mesh_primitives(resolution)
    return reconstruct_poly_mesh_geometry(points, faces, owner, neighbour)


def _load_resolved_mesh_primitives(
    resolution: MeshResolution,
) -> tuple[tuple[Point, ...], tuple[Face, ...], tuple[int, ...], tuple[int, ...]]:
    resolution = _require_current_mesh_resolution(resolution)
    return _load_mesh_primitives_from_provenance(resolution)


def _load_mesh_primitives_from_provenance(
    resolution: MeshResolution,
) -> tuple[tuple[Point, ...], tuple[Face, ...], tuple[int, ...], tuple[int, ...]]:
    """Load canonical sources from an internally prevalidated mesh resolution."""

    points = parse_points(_resolved_primitive_path(resolution, "points"))
    faces = parse_faces(_resolved_primitive_path(resolution, "faces"))
    face_count = len(faces)
    owner = parse_label_list(
        _resolved_primitive_path(resolution, "owner"),
        expected_object="owner",
        expected_count=face_count,
        compact_limit=face_count,
    )
    neighbour = parse_label_list(
        _resolved_primitive_path(resolution, "neighbour"),
        expected_object="neighbour",
        maximum_count=face_count,
        compact_limit=face_count,
    )
    return points, faces, owner, neighbour


def _cell_face_labels(
    owner: tuple[int, ...], neighbour: tuple[int, ...], cell_count: int
) -> tuple[tuple[int, ...], ...]:
    memberships: list[list[int]] = [[] for _ in range(cell_count)]
    for face_label, cell_label in enumerate(owner):
        if cell_label < 0 or cell_label >= cell_count:
            raise OpenFOAMParseError("owner contains an out-of-range cell label")
        memberships[cell_label].append(face_label)
    for face_label, cell_label in enumerate(neighbour):
        if cell_label < 0 or cell_label >= cell_count:
            raise OpenFOAMParseError("neighbour contains an out-of-range cell label")
        memberships[cell_label].append(face_label)
    return tuple(tuple(labels) for labels in memberships)


def load_cell_centres(poly_mesh_directory: str | Path) -> tuple[Point, ...]:
    """Load true volume-weighted cell centres from one ASCII ``polyMesh``."""

    return load_poly_mesh_geometry(poly_mesh_directory).cell_centres


def _class_kind(class_name: str) -> FieldKind:
    volume_classes: dict[str, FieldKind] = {
        "volScalarField": "scalar",
        "volVectorField": "vector",
        "volSphericalTensorField": "sphericalTensor",
        "volSymmTensorField": "symmTensor",
        "volTensorField": "tensor",
    }
    try:
        return volume_classes[class_name]
    except KeyError as exc:
        raise OpenFOAMParseError(f"unsupported volume-field class: {class_name!r}") from exc


def _parse_dimensions(tokens: tuple[Token, ...], source_path: str) -> tuple[Decimal, ...]:
    cursor = _Cursor(tokens, source_path)
    cursor.index = _unique_body_key_position(tokens, "dimensions", source_path) + 1
    cursor.expect("[")
    values = tuple(_decimal(cursor.take().text, context="dimension exponent") for _ in range(7))
    cursor.expect("]")
    cursor.expect(";")
    return values


def _parse_parenthesized_value(cursor: _Cursor, width: int, context: str) -> Value:
    cursor.expect("(")
    value = tuple(_decimal(cursor.take().text, context=context) for _ in range(width))
    cursor.expect(")")
    return value


def _parse_uniform(cursor: _Cursor, kind: FieldKind) -> tuple[Value, ...]:
    width = _WIDTH[kind]
    value: Value
    if width == 1:
        value = (_decimal(cursor.take().text, context="uniform field value"),)
    else:
        value = _parse_parenthesized_value(cursor, width, "uniform field component")
    cursor.expect(";")
    return (value,)


def _parse_nonuniform(cursor: _Cursor, expected_kind: FieldKind) -> tuple[Value, ...]:
    cursor.expect("List")
    cursor.expect("<")
    listed_kind = cursor.take().text
    cursor.expect(">")
    if listed_kind != expected_kind:
        raise OpenFOAMParseError(
            f"field class expects {expected_kind}, but internalField declares {listed_kind}"
        )
    count_token = cursor.take()
    count = _non_negative_decimal(
        count_token,
        cursor.source_path,
        context="internalField count",
    )
    width = _WIDTH[expected_kind]
    cursor.expect("(")
    values: list[Value] = []
    for _ in range(count):
        if width == 1:
            values.append((_decimal(cursor.take().text, context="field value"),))
        else:
            values.append(_parse_parenthesized_value(cursor, width, "field component"))
    cursor.expect(")")
    cursor.expect(";")
    return tuple(values)


def parse_field_text(text: str, *, source_path: str = "<memory>") -> FoamField:
    """Parse one ASCII field's header, dimensions, and ``internalField``."""

    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise OpenFOAMParseError(f"{source_path}: field is not ASCII") from exc

    tokens = tokenize_openfoam(text, source_path=source_path)
    class_name, object_name = _parse_header(tokens, source_path)
    kind = _class_kind(class_name)
    dimensions = _parse_dimensions(tokens, source_path)
    cursor = _Cursor(tokens, source_path)
    cursor.index = _unique_body_key_position(tokens, "internalField", source_path) + 1
    storage = cursor.take().text
    if storage == "uniform":
        values = _parse_uniform(cursor, kind)
    elif storage == "nonuniform":
        values = _parse_nonuniform(cursor, kind)
    else:
        raise OpenFOAMParseError(f"unsupported internalField storage: {storage!r}")
    return FoamField(
        source_path=source_path,
        object_name=object_name,
        class_name=class_name,
        dimensions=dimensions,
        field_kind=kind,
        storage=storage,  # type: ignore[arg-type]
        values=values,
    )


def parse_field(path: str | Path) -> FoamField:
    source = Path(path)
    try:
        text = source.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise OpenFOAMParseError(f"cannot read ASCII field {source}: {exc}") from exc
    return parse_field_text(text, source_path=str(source))


def component_names(field_kind: FieldKind) -> tuple[str, ...]:
    """Return the explicit OpenFOAM component order for one field kind."""

    try:
        return _COMPONENT_NAMES[field_kind]
    except KeyError as exc:
        raise OpenFOAMParseError(f"unsupported OpenFOAM field kind: {field_kind!r}") from exc


def cylindrical_symm_tensor_normal_component(
    engineering_component: Literal["radial", "hoop", "axial"],
) -> Literal["xx", "yy", "zz"]:
    """Return the OpenFOAM symmTensor diagonal storage component.

    The exact mapping is radial to ``xx``, hoop to ``yy``, and axial to ``zz``.
    The caller or selector semantics must establish compatible producer and
    cylindrical-basis provenance; this function only performs the exact name mapping.
    """

    if not isinstance(engineering_component, str) or engineering_component not in (
        "radial",
        "hoop",
        "axial",
    ):
        raise OpenFOAMParseError(
            "unsupported cylindrical symmTensor normal component "
            f"{engineering_component!r}; expected exactly one of ('radial', 'hoop', 'axial')"
        )
    if engineering_component == "radial":
        return "xx"
    if engineering_component == "hoop":
        return "yy"
    return "zz"


def component_index(field_kind: FieldKind, component: str) -> int:
    """Resolve an exact component name; numeric or inferred components are rejected."""

    names = component_names(field_kind)
    matches = tuple(index for index, name in enumerate(names) if name == component)
    if len(matches) != 1:
        raise OpenFOAMParseError(
            f"component {component!r} is invalid for {field_kind}; expected one of {names}"
        )
    return matches[0]


def _expand_values(
    storage: Literal["uniform", "nonuniform"],
    values: tuple[Value, ...],
    *,
    expected_count: int,
    expected_width: int,
    context: str,
) -> tuple[Value, ...]:
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count <= 0
    ):
        raise OpenFOAMParseError(f"{context}: expected count must be a positive integer")
    if any(len(value) != expected_width for value in values):
        raise OpenFOAMParseError(
            f"{context}: component width does not match the declared field kind"
        )
    if storage == "uniform":
        if len(values) != 1:
            raise OpenFOAMParseError(f"{context}: uniform field must contain exactly one value")
        return values * expected_count
    if storage == "nonuniform":
        if len(values) != expected_count:
            raise OpenFOAMParseError(
                f"{context}: nonuniform count {len(values)} does not match {expected_count}"
            )
        return values
    raise OpenFOAMParseError(f"{context}: unsupported field storage {storage!r}")


def expand_internal_field(field: FoamField, expected_count: int) -> tuple[Value, ...]:
    """Expand ``uniform`` values and verify ``nonuniform`` values against the mesh."""

    return _expand_values(
        field.storage,
        field.values,
        expected_count=expected_count,
        expected_width=_WIDTH[field.field_kind],
        context=f"internalField {field.object_name!r}",
    )


def select_cell_component_values(
    field: FoamField,
    cell_labels: tuple[int, ...],
    cell_centres: tuple[Point, ...],
    *,
    component: str,
) -> tuple[CellScalarValue, ...]:
    """Select one exact field component over exact labels with true cell centres."""

    if not cell_centres:
        raise OpenFOAMParseError("cell-centre sequence must not be empty")
    for cell_label, centre in enumerate(cell_centres):
        if len(centre) != 3 or any(
            not isinstance(value, Decimal) or not value.is_finite() for value in centre
        ):
            raise OpenFOAMParseError(f"cell centre {cell_label} is not a finite Decimal point")
    if not cell_labels:
        raise OpenFOAMParseError("selected cell zone must not be empty")
    if len(set(cell_labels)) != len(cell_labels):
        raise OpenFOAMParseError("selected cell labels contain duplicates")
    if any(
        isinstance(label, bool)
        or not isinstance(label, int)
        or label < 0
        or label >= len(cell_centres)
        for label in cell_labels
    ):
        raise OpenFOAMParseError("selected cell zone contains an out-of-range label")
    index = component_index(field.field_kind, component)
    values = expand_internal_field(field, len(cell_centres))
    return tuple(
        CellScalarValue(label, values[label][index], cell_centres[label])
        for label in sorted(cell_labels)
    )


def _validated_cell_record_identity(
    records: tuple[CellScalarValue, ...], *, context: str
) -> tuple[tuple[int, Point], ...]:
    if not records:
        raise OpenFOAMParseError(f"{context} must not be empty")
    labels = tuple(record.cell_label for record in records)
    if len(set(labels)) != len(labels):
        raise OpenFOAMParseError(f"{context} contains duplicate labels")
    if labels != tuple(sorted(labels)):
        raise OpenFOAMParseError(f"{context} must be sorted by cell label")
    for record in records:
        if (
            isinstance(record.cell_label, bool)
            or not isinstance(record.cell_label, int)
            or record.cell_label < 0
            or not isinstance(record.value, Decimal)
            or not record.value.is_finite()
            or len(record.centre) != 3
            or any(
                not isinstance(value, Decimal) or not value.is_finite() for value in record.centre
            )
        ):
            raise OpenFOAMParseError(f"{context} contains a malformed record")
    return tuple((record.cell_label, record.centre) for record in records)


def validate_aligned_cell_values(
    *series: tuple[CellScalarValue, ...],
) -> tuple[tuple[CellScalarValue, ...], ...]:
    """Require multiple derived-quantity operands to share exact labels and centres."""

    if len(series) < 2:
        raise OpenFOAMParseError("derived cell formula requires at least two operand series")
    expected = _validated_cell_record_identity(series[0], context="cell operand 0")
    for index, records in enumerate(series[1:], start=1):
        identity = _validated_cell_record_identity(records, context=f"cell operand {index}")
        if identity != expected:
            raise OpenFOAMParseError(
                f"cell operand {index} labels or centres do not align with operand 0"
            )
    return series


def reduce_cell_values(
    records: tuple[CellScalarValue, ...], *, operation: ReductionOperation
) -> CellValueReduction:
    """Reduce selected scalar records and preserve all exact extremum ties."""

    _validated_cell_record_identity(records, context="selected cell-value records")
    if operation == "max":
        comparison = max(record.value for record in records)
        tied = tuple(record for record in records if record.value == comparison)
    elif operation == "min":
        comparison = min(record.value for record in records)
        tied = tuple(record for record in records if record.value == comparison)
    elif operation == "max_abs":
        comparison = max(abs(record.value) for record in records)
        tied = tuple(record for record in records if abs(record.value) == comparison)
    else:
        raise OpenFOAMParseError(f"unsupported reduction operation: {operation!r}")
    return CellValueReduction(
        operation=operation,
        selected_cell_count=len(records),
        comparison_value=comparison,
        extrema=tuple(
            CellExtremum(record.cell_label, record.value, record.centre) for record in tied
        ),
    )


def reduce_cell_field(
    field: FoamField,
    cell_labels: tuple[int, ...],
    cell_centres: tuple[Point, ...],
    *,
    component: str,
    operation: ReductionOperation,
) -> FieldReduction:
    """Reduce one verified component over exact labels and return every exact tie."""

    index = component_index(field.field_kind, component)
    selected = select_cell_component_values(field, cell_labels, cell_centres, component=component)
    reduced = reduce_cell_values(selected, operation=operation)
    return FieldReduction(
        source_path=field.source_path,
        object_name=field.object_name,
        operation=operation,
        component=component,
        component_index=index,
        selected_cell_count=reduced.selected_cell_count,
        comparison_value=reduced.comparison_value,
        extrema=reduced.extrema,
    )


def _safe_exact_name(value: str, *, context: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or Path(value).is_absolute()
        or Path(value).name != value
    ):
        raise OpenFOAMParseError(f"{context} must be one exact safe basename")
    return value


def _selected_field_path(
    root: Path, time_directory: NumericDirectory, field_selector: str
) -> tuple[Path, str]:
    field_selector = _safe_exact_name(field_selector, context="field selector")
    candidate = time_directory.path / field_selector
    try:
        candidate.lstat()
    except FileNotFoundError as exc:
        raise _ExactFieldMissing(
            f"exact field {field_selector!r} is absent at modeled time {time_directory.value}"
        ) from exc
    except OSError as exc:
        raise OpenFOAMParseError(f"cannot inspect exact field path {candidate}: {exc}") from exc
    if not candidate.is_file():
        raise OpenFOAMParseError(
            f"exact field {field_selector!r} is not a readable regular file at modeled time "
            f"{time_directory.value}"
        )
    (relative_path,) = validate_source_paths(root, candidate)
    expected_relative_path = f"{time_directory.name}/{field_selector}"
    if relative_path != expected_relative_path:
        raise OpenFOAMParseError(
            f"exact field {field_selector!r} is an alias for a different modeled time"
        )
    return root / relative_path, relative_path


def _zone_selection_context(
    mesh: MeshResolution,
    zone_name: str,
    *,
    cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...], str],
        tuple[CellSelectionContext, PolyMeshGeometry],
    ]
    | None = None,
    mesh_prevalidated: bool = False,
) -> tuple[CellSelectionContext, PolyMeshGeometry]:
    zone_name = _safe_exact_name(zone_name, context="cell-zone selector")
    cache_key = (mesh.result_root, mesh.primitive_sources, zone_name)
    if cache is not None and cache_key in cache:
        cached_context, geometry = cache[cache_key]
        return (
            CellSelectionContext(
                mesh=mesh,
                zone_name=cached_context.zone_name,
                cell_zones_source=cached_context.cell_zones_source,
                zone_cell_labels=cached_context.zone_cell_labels,
                zone_face_labels=cached_context.zone_face_labels,
                zone_face_centres=cached_context.zone_face_centres,
                zone_vertex_points=cached_context.zone_vertex_points,
            ),
            geometry,
        )

    if mesh_prevalidated:
        points, faces, owner, neighbour = _load_mesh_primitives_from_provenance(mesh)
    else:
        points, faces, owner, neighbour = _load_resolved_mesh_primitives(mesh)
    geometry = reconstruct_poly_mesh_geometry(points, faces, owner, neighbour)
    cell_zones_source = mesh_primitive_source(mesh, "cellZones")
    zone_path = _resolved_primitive_path(mesh, "cellZones")
    labels = tuple(sorted(cell_labels_for_zone(zone_path, zone_name)))
    if any(label >= len(geometry.cell_centres) for label in labels):
        raise OpenFOAMParseError("selected cell zone contains a label outside the resolved mesh")

    cell_faces = _cell_face_labels(owner, neighbour, len(geometry.cell_centres))
    face_labels = tuple(sorted({face for label in labels for face in cell_faces[label]}))
    if not face_labels:
        raise OpenFOAMParseError("selected cell zone has no resolved mesh faces")
    face_centres = tuple(
        (face_label, _face_centre_and_area(points, faces[face_label], face_label=face_label)[0])
        for face_label in face_labels
    )
    point_labels = tuple(
        sorted({point_label for face_label in face_labels for point_label in faces[face_label]})
    )
    vertex_points = tuple((point_label, points[point_label]) for point_label in point_labels)
    context = CellSelectionContext(
        mesh=mesh,
        zone_name=zone_name,
        cell_zones_source=cell_zones_source.relative_path,
        zone_cell_labels=labels,
        zone_face_labels=face_labels,
        zone_face_centres=face_centres,
        zone_vertex_points=vertex_points,
    )
    result = (context, geometry)
    if cache is not None:
        cache[cache_key] = result
    return result


def _select_cell_field_for_time_directory(
    root: Path,
    time_directory: NumericDirectory,
    mesh: MeshResolution,
    *,
    field_selector: str,
    zone_name: str,
    component: str,
    zone_cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...], str],
        tuple[CellSelectionContext, PolyMeshGeometry],
    ]
    | None = None,
    mesh_prevalidated: bool = False,
) -> CellFieldSelection:
    field_path, source_path = _selected_field_path(root, time_directory, field_selector)
    field = parse_field(field_path)
    if field.object_name != field_selector:
        raise OpenFOAMParseError(
            f"field selector {field_selector!r} disagrees with FoamFile object "
            f"{field.object_name!r}"
        )
    context, geometry = _zone_selection_context(
        mesh,
        zone_name,
        cache=zone_cache,
        mesh_prevalidated=mesh_prevalidated,
    )
    records = select_cell_component_values(
        field,
        context.zone_cell_labels,
        geometry.cell_centres,
        component=component,
    )
    volumes = tuple(geometry.cell_volumes[record.cell_label] for record in records)
    return CellFieldSelection(
        context=context,
        source_path=source_path,
        field_selector=field_selector,
        object_name=field.object_name,
        class_name=field.class_name,
        dimensions=field.dimensions,
        field_kind=field.field_kind,
        storage=field.storage,
        component=component,
        component_index=component_index(field.field_kind, component),
        records=records,
        volumes=volumes,
    )


def select_cell_field_at_time(
    result_root: str | Path,
    *,
    field_selector: str,
    zone_name: str,
    component: str,
    exact: str | Decimal | None = None,
    latest: bool = False,
) -> CellFieldSelection:
    """Select one field component over one exact zone and time-bound mesh."""

    root = _canonical_result_root(result_root)
    time_directory = select_numeric_directory(root, exact=exact, latest=latest)
    mesh = resolve_mesh_for_time(root, exact=time_directory.value)
    return _select_cell_field_for_time_directory(
        root,
        time_directory,
        mesh,
        field_selector=field_selector,
        zone_name=zone_name,
        component=component,
    )


def select_cell_field_series(
    result_root: str | Path,
    *,
    field_selector: str,
    zone_name: str,
    component: str,
    missing: MissingFieldPolicy = "error",
) -> tuple[CellFieldSelection, ...]:
    """Select a field across numeric times under one explicit missing-field policy.

    The default fails when any exact field is absent.  ``missing="skip"`` omits
    only a genuinely absent exact field path; existing aliases, broken symlinks,
    malformed fields, and every other source or parse error still fail closed.
    Returned selections therefore state the actual covered times through each
    ``selection.context.mesh.modeled_time``.
    """

    if missing != "error" and missing != "skip":
        raise OpenFOAMParseError(f"unsupported missing-field policy: {missing!r}")
    field_selector = _safe_exact_name(field_selector, context="field selector")
    zone_name = _safe_exact_name(zone_name, context="cell-zone selector")

    root = _canonical_result_root(result_root)
    directories = discover_numeric_directories(root)
    if not directories:
        raise OpenFOAMParseError(f"no numeric directories below {root}")
    mesh_resolutions = _resolve_mesh_for_directories(root, directories)
    zone_cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...], str],
        tuple[CellSelectionContext, PolyMeshGeometry],
    ] = {}
    selected: list[CellFieldSelection] = []
    for directory, mesh in zip(directories, mesh_resolutions, strict=True):
        try:
            selection = _select_cell_field_for_time_directory(
                root,
                directory,
                mesh,
                field_selector=field_selector,
                zone_name=zone_name,
                component=component,
                zone_cache=zone_cache,
                mesh_prevalidated=True,
            )
        except _ExactFieldMissing:
            if missing == "skip":
                continue
            raise
        selected.append(selection)
    selections = tuple(selected)
    if not selections:
        raise OpenFOAMParseError(
            f"exact field {field_selector!r} is absent at every numeric modeled time"
        )
    baseline = selections[0]
    for selection in selections[1:]:
        if (
            selection.object_name != baseline.object_name
            or selection.dimensions != baseline.dimensions
            or selection.field_kind != baseline.field_kind
            or selection.component_index != baseline.component_index
        ):
            raise OpenFOAMParseError(
                f"field {field_selector!r} schema changes across modeled-time directories"
            )
    return selections


def align_field_series_by_time(
    *series: tuple[FieldSelection, ...],
) -> tuple[FieldTimeRow, ...]:
    """Align non-empty cell/boundary field series on the sorted union of exact times.

    Missing columns are represented only by ``None``.  The function never uses
    positional pairing, interpolation, nearest-time matching, or numeric fill.
    """

    if not series:
        raise OpenFOAMParseError("field time alignment requires at least one series")

    expected_root: str | None = None
    indexes: list[dict[Decimal, FieldSelection]] = []
    for series_index, selections in enumerate(series):
        if not selections:
            raise OpenFOAMParseError(f"field series {series_index} is empty")

        indexed: dict[Decimal, FieldSelection] = {}
        expected_signature: tuple[object, ...] | None = None
        for selection in selections:
            if not isinstance(selection, CellFieldSelection | BoundaryFieldSelection):
                raise OpenFOAMParseError(
                    f"field series {series_index} contains an invalid selection"
                )
            mesh = selection.context.mesh
            modeled_time = mesh.modeled_time
            if not isinstance(modeled_time, Decimal) or not modeled_time.is_finite():
                raise OpenFOAMParseError(
                    f"field series {series_index} contains an invalid modeled time"
                )
            if modeled_time in indexed:
                raise OpenFOAMParseError(
                    f"field series {series_index} contains duplicate modeled time {modeled_time}"
                )

            root = mesh.result_root
            if expected_root is None:
                expected_root = root
            elif root != expected_root:
                raise OpenFOAMParseError("field time alignment requires one exact result root")

            signature: tuple[object, ...]
            if isinstance(selection, CellFieldSelection):
                signature = (
                    "cell",
                    selection.field_selector,
                    selection.object_name,
                    selection.dimensions,
                    selection.field_kind,
                    selection.component,
                    selection.component_index,
                    selection.context.zone_name,
                )
            else:
                signature = (
                    "boundary",
                    selection.field_selector,
                    selection.object_name,
                    selection.dimensions,
                    selection.field_kind,
                    selection.entry_name,
                    selection.patch_topology.name,
                    selection.component,
                    selection.component_index,
                    selection.context.owner_zone_name,
                )
            if expected_signature is None:
                expected_signature = signature
            elif signature != expected_signature:
                raise OpenFOAMParseError(
                    f"field series {series_index} changes field or selection context"
                )
            indexed[modeled_time] = selection
        indexes.append(indexed)

    modeled_times = sorted({modeled_time for indexed in indexes for modeled_time in indexed})
    rows: list[FieldTimeRow] = []
    for modeled_time in modeled_times:
        aligned = tuple(indexed.get(modeled_time) for indexed in indexes)
        present_meshes = tuple(
            selection.context.mesh for selection in aligned if selection is not None
        )
        if any(mesh != present_meshes[0] for mesh in present_meshes[1:]):
            raise OpenFOAMParseError(
                f"field mesh provenance conflicts at modeled time {modeled_time}"
            )
        rows.append(FieldTimeRow(modeled_time, aligned))
    return tuple(rows)


def align_modeled_time_results(
    *series: tuple[ModeledTimeResult[Any], ...],
) -> tuple[ModeledTimeResultRow, ...]:
    """Align non-empty derived-result series on the sorted union of exact times.

    Input order fixes the output column order, and ``None`` is reserved for a
    missing column.  Payload types may differ by column; each payload object is
    returned unchanged.  This pure envelope operation does not inspect or
    validate source freshness, result roots, units, or payload semantics.
    """

    if not series:
        raise OpenFOAMParseError("modeled-time result alignment requires at least one series")

    indexes: list[dict[Decimal, object]] = []
    for series_index, results in enumerate(series):
        if not results:
            raise OpenFOAMParseError(f"modeled-time result series {series_index} is empty")

        indexed: dict[Decimal, object] = {}
        for row in results:
            if not isinstance(row, ModeledTimeResult):
                raise OpenFOAMParseError(
                    f"modeled-time result series {series_index} contains an invalid row"
                )
            modeled_time = row.modeled_time
            if not isinstance(modeled_time, Decimal) or not modeled_time.is_finite():
                raise OpenFOAMParseError(
                    f"modeled-time result series {series_index} contains an invalid modeled time"
                )
            if modeled_time in indexed:
                raise OpenFOAMParseError(
                    f"modeled-time result series {series_index} contains duplicate modeled time "
                    f"{modeled_time}"
                )
            if row.result is None:
                raise OpenFOAMParseError(
                    f"modeled-time result series {series_index} contains a None result"
                )
            indexed[modeled_time] = row.result
        indexes.append(indexed)

    modeled_times = sorted({modeled_time for indexed in indexes for modeled_time in indexed})
    return tuple(
        ModeledTimeResultRow(
            modeled_time,
            tuple(indexed.get(modeled_time) for indexed in indexes),
        )
        for modeled_time in modeled_times
    )


def reduce_modeled_time_extrema[T: FieldReduction | MultiBoundaryFieldReduction](
    rows: tuple[ModeledTimeResult[T], ...],
    *,
    operation: ReductionOperation,
) -> ModeledTimeExtrema[T]:
    """Reduce one spatial-extremum history and preserve all exact time ties.

    ``rows`` must be the output shape of ``reduce_cell_selection_series`` or
    ``reduce_boundary_selection_series``.  The temporal operation must match
    the spatial operation already applied to every payload.  Returned rows and
    their spatial extrema are not reconstructed, so signed ``max_abs`` values
    and all inner spatial ties remain intact.
    """

    if operation not in ("max", "min", "max_abs"):
        raise OpenFOAMParseError(f"unsupported reduction operation: {operation!r}")
    if not rows:
        raise OpenFOAMParseError("modeled-time extrema require a non-empty series")

    expected_payload_type: type[object] | None = None
    expected_identity: tuple[object, ...] | None = None
    indexed: dict[Decimal, ModeledTimeResult[T]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, ModeledTimeResult):
            raise OpenFOAMParseError(
                f"modeled-time extrema row {index} is not a ModeledTimeResult"
            )
        modeled_time = row.modeled_time
        if not isinstance(modeled_time, Decimal) or not modeled_time.is_finite():
            raise OpenFOAMParseError(
                f"modeled-time extrema row {index} contains an invalid modeled time"
            )
        if modeled_time in indexed:
            raise OpenFOAMParseError(
                f"modeled-time extrema contain duplicate modeled time {modeled_time}"
            )

        payload = row.result
        if type(payload) not in (FieldReduction, MultiBoundaryFieldReduction):
            raise OpenFOAMParseError(
                "modeled-time extrema require FieldReduction or "
                "MultiBoundaryFieldReduction payloads"
            )
        payload_type = type(payload)
        if expected_payload_type is None:
            expected_payload_type = payload_type
        elif payload_type is not expected_payload_type:
            raise OpenFOAMParseError("modeled-time extrema payload types are inconsistent")
        if payload.operation != operation:
            raise OpenFOAMParseError(
                "modeled-time extrema require the temporal and spatial operations to match"
            )
        comparison = payload.comparison_value
        if not isinstance(comparison, Decimal) or not comparison.is_finite():
            raise OpenFOAMParseError(
                f"modeled-time extrema row {index} has a non-finite comparison value"
            )
        if operation == "max_abs" and comparison < 0:
            raise OpenFOAMParseError(
                f"modeled-time extrema row {index} has a negative max_abs comparison value"
            )

        identity: tuple[object, ...]
        if isinstance(payload, FieldReduction):
            identity = (
                payload.object_name,
                payload.component,
                payload.component_index,
            )
        else:
            identity = (
                payload.patch_names,
                payload.owner_zone_names,
                payload.entry_name,
                payload.component,
                payload.component_index,
            )
        if expected_identity is None:
            expected_identity = identity
        elif identity != expected_identity:
            raise OpenFOAMParseError(
                "modeled-time extrema payload selection identities are inconsistent"
            )
        indexed[modeled_time] = row

    if operation == "min":
        comparison_value = min(row.result.comparison_value for row in indexed.values())
    else:
        comparison_value = max(row.result.comparison_value for row in indexed.values())
    extrema = tuple(
        indexed[modeled_time]
        for modeled_time in sorted(indexed)
        if indexed[modeled_time].result.comparison_value == comparison_value
    )
    return ModeledTimeExtrema(operation, comparison_value, extrema)


def _require_current_cell_selection(selection: CellFieldSelection) -> CellFieldSelection:
    if not isinstance(selection, CellFieldSelection):
        raise OpenFOAMParseError("cell selection must be produced by select_cell_field_at_time")
    expected = select_cell_field_at_time(
        selection.context.mesh.result_root,
        field_selector=selection.field_selector,
        zone_name=selection.context.zone_name,
        component=selection.component,
        exact=selection.context.mesh.modeled_time,
    )
    if selection != expected:
        raise OpenFOAMParseError(
            "cell selection is stale, forged, or inconsistent with its result source"
        )
    return selection


def _require_current_cell_field_series(
    selections: tuple[CellFieldSelection, ...],
) -> tuple[CellFieldSelection, ...]:
    """Rebuild one complete field history through the linear series selector."""

    if not selections:
        raise OpenFOAMParseError("cell field series must not be empty")
    if any(not isinstance(selection, CellFieldSelection) for selection in selections):
        raise OpenFOAMParseError("cell field series contains an invalid selection")
    baseline = selections[0]
    expected = select_cell_field_series(
        baseline.context.mesh.result_root,
        field_selector=baseline.field_selector,
        zone_name=baseline.context.zone_name,
        component=baseline.component,
        missing="skip",
    )
    if selections != expected:
        raise OpenFOAMParseError(
            "cell field series is stale, incomplete, forged, or inconsistent with its result source"
        )
    return selections


def validate_aligned_cell_selections(
    *selections: CellFieldSelection,
) -> tuple[CellFieldSelection, ...]:
    """Require complete root/time/zone/mesh/label/centre/volume alignment."""

    if len(selections) < 2:
        raise OpenFOAMParseError("derived cell formula requires at least two field selections")
    current = tuple(_require_current_cell_selection(selection) for selection in selections)
    return _validate_current_aligned_cell_selections(current)


def _validate_current_aligned_cell_selections(
    selections: tuple[CellFieldSelection, ...],
) -> tuple[CellFieldSelection, ...]:
    """Validate already-current selections without repeating source discovery."""

    baseline = selections[0]
    baseline_identity = _validated_cell_record_identity(
        baseline.records, context="cell field selection 0"
    )
    for index, selection in enumerate(selections[1:], start=1):
        identity = _validated_cell_record_identity(
            selection.records, context=f"cell field selection {index}"
        )
        if (
            selection.context != baseline.context
            or identity != baseline_identity
            or selection.volumes != baseline.volumes
        ):
            raise OpenFOAMParseError(
                f"cell field selection {index} does not align with selection 0"
            )
    return selections


def reduce_cell_selection(
    selection: CellFieldSelection, *, operation: ReductionOperation
) -> FieldReduction:
    """Reduce one provenance-bound cell selection and retain all exact ties."""

    selection = _require_current_cell_selection(selection)
    return _reduce_current_cell_selection(selection, operation=operation)


def _reduce_current_cell_selection(
    selection: CellFieldSelection, *, operation: ReductionOperation
) -> FieldReduction:
    reduced = reduce_cell_values(selection.records, operation=operation)
    return FieldReduction(
        source_path=selection.source_path,
        object_name=selection.object_name,
        operation=operation,
        component=selection.component,
        component_index=selection.component_index,
        selected_cell_count=reduced.selected_cell_count,
        comparison_value=reduced.comparison_value,
        extrema=reduced.extrema,
    )


def reduce_cell_selection_series(
    selections: tuple[CellFieldSelection, ...],
    *,
    operation: ReductionOperation,
) -> tuple[ModeledTimeResult[FieldReduction], ...]:
    """Reduce a complete cell-field history after one linear batch revalidation."""

    current = _require_current_cell_field_series(selections)
    return tuple(
        ModeledTimeResult(
            selection.context.mesh.modeled_time,
            _reduce_current_cell_selection(selection, operation=operation),
        )
        for selection in current
    )


def volume_weighted_mean(selection: CellFieldSelection) -> VolumeWeightedMean:
    """Return the exact zone volume-weighted mean for one bound selection."""

    selection = _require_current_cell_selection(selection)
    return _volume_weighted_mean_current(selection)


def _volume_weighted_mean_current(selection: CellFieldSelection) -> VolumeWeightedMean:
    total_volume = sum(selection.volumes, Decimal(0))
    if total_volume <= 0 or not total_volume.is_finite():
        raise OpenFOAMParseError("selected cell volume sum must be finite and positive")
    weighted_sum = sum(
        (
            record.value * volume
            for record, volume in zip(selection.records, selection.volumes, strict=True)
        ),
        Decimal(0),
    )
    value = weighted_sum / total_volume
    if not value.is_finite():
        raise OpenFOAMParseError("volume-weighted mean is non-finite")
    return VolumeWeightedMean(len(selection.records), total_volume, value)


def volume_weighted_mean_series(
    selections: tuple[CellFieldSelection, ...],
) -> tuple[ModeledTimeResult[VolumeWeightedMean], ...]:
    """Compute means for a complete history after one linear batch revalidation."""

    current = _require_current_cell_field_series(selections)
    return tuple(
        ModeledTimeResult(
            selection.context.mesh.modeled_time,
            _volume_weighted_mean_current(selection),
        )
        for selection in current
    )


def volume_weighted_ratio(
    numerator_selection: CellFieldSelection,
    denominator_selection: CellFieldSelection,
) -> VolumeWeightedRatio:
    """Return ``sum(V*numerator) / sum(V*denominator)`` on one exact domain."""

    numerator_selection, denominator_selection = validate_aligned_cell_selections(
        numerator_selection, denominator_selection
    )
    return _volume_weighted_ratio_current(numerator_selection, denominator_selection)


def _volume_weighted_ratio_current(
    numerator_selection: CellFieldSelection,
    denominator_selection: CellFieldSelection,
) -> VolumeWeightedRatio:
    if numerator_selection.dimensions != denominator_selection.dimensions:
        raise OpenFOAMParseError("volume-weighted ratio operands have different dimensions")
    numerator = sum(
        (
            record.value * volume
            for record, volume in zip(
                numerator_selection.records, numerator_selection.volumes, strict=True
            )
        ),
        Decimal(0),
    )
    denominator = sum(
        (
            record.value * volume
            for record, volume in zip(
                denominator_selection.records, denominator_selection.volumes, strict=True
            )
        ),
        Decimal(0),
    )
    if denominator == 0:
        raise OpenFOAMParseError("volume-weighted ratio denominator is zero")
    value = numerator / denominator
    if not numerator.is_finite() or not denominator.is_finite() or not value.is_finite():
        raise OpenFOAMParseError("volume-weighted ratio is non-finite")
    return VolumeWeightedRatio(len(numerator_selection.records), numerator, denominator, value)


def volume_weighted_ratio_series(
    numerator_series: tuple[CellFieldSelection, ...],
    denominator_series: tuple[CellFieldSelection, ...],
) -> tuple[ModeledTimeResult[VolumeWeightedRatio], ...]:
    """Compute exact-time ratios after two linear complete-history validations."""

    numerators = _require_current_cell_field_series(numerator_series)
    denominators = _require_current_cell_field_series(denominator_series)
    numerator_times = tuple(item.context.mesh.modeled_time for item in numerators)
    denominator_times = tuple(item.context.mesh.modeled_time for item in denominators)
    if numerator_times != denominator_times:
        raise OpenFOAMParseError(
            "volume-weighted ratio series require identical exact modeled-time coverage"
        )

    ratios: list[ModeledTimeResult[VolumeWeightedRatio]] = []
    for numerator, denominator in zip(numerators, denominators, strict=True):
        _validate_current_aligned_cell_selections((numerator, denominator))
        ratios.append(
            ModeledTimeResult(
                numerator.context.mesh.modeled_time,
                _volume_weighted_ratio_current(numerator, denominator),
            )
        )
    return tuple(ratios)


def zone_axis_face_envelope(
    selection: CellFieldSelection, *, axis: Axis
) -> tuple[Decimal, Decimal]:
    """Return min/max zone face-vertex coordinates on one explicit axis."""

    selection = _require_current_cell_selection(selection)
    coordinates = tuple(
        point_axis_coordinate(point, axis=axis) for _, point in selection.context.zone_vertex_points
    )
    if not coordinates:
        raise OpenFOAMParseError("selected cell zone has no face-vertex coordinates")
    lower = min(coordinates)
    upper = max(coordinates)
    if lower >= upper:
        raise OpenFOAMParseError("selected cell zone has no positive axis extent")
    return lower, upper


def bin_zone_volume_weighted_mean(
    selection: CellFieldSelection, *, axis: Axis, bin_count: int
) -> ZoneBinnedMean:
    """Bin cell centres across the exact face envelope and volume-average each bin."""

    selection = _require_current_cell_selection(selection)
    if isinstance(bin_count, bool) or not isinstance(bin_count, int) or bin_count <= 0:
        raise OpenFOAMParseError("bin count must be a positive integer")
    lower, upper = zone_axis_face_envelope(selection, axis=axis)
    width = (upper - lower) / Decimal(bin_count)
    members: list[list[tuple[CellScalarValue, Decimal]]] = [[] for _ in range(bin_count)]
    for record, volume in zip(selection.records, selection.volumes, strict=True):
        coordinate = point_axis_coordinate(record.centre, axis=axis)
        if coordinate < lower or coordinate > upper:
            raise OpenFOAMParseError("selected cell centre lies outside its zone face envelope")
        index = bin_count - 1 if coordinate == upper else int((coordinate - lower) / width)
        if index < 0 or index >= bin_count:
            raise OpenFOAMParseError("selected cell centre cannot be assigned to an axis bin")
        members[index].append((record, volume))

    bins: list[ZoneAxisBin] = []
    for index, entries in enumerate(members):
        bin_lower = lower + width * Decimal(index)
        bin_upper = upper if index == bin_count - 1 else lower + width * Decimal(index + 1)
        total_volume = sum((volume for _, volume in entries), Decimal(0))
        weighted_mean = None
        if entries:
            weighted_mean = (
                sum((record.value * volume for record, volume in entries), Decimal(0))
                / total_volume
            )
            if not weighted_mean.is_finite():
                raise OpenFOAMParseError("axis-bin volume-weighted mean is non-finite")
        bins.append(
            ZoneAxisBin(
                index=index,
                lower=bin_lower,
                upper=bin_upper,
                upper_inclusive=index == bin_count - 1,
                cell_labels=tuple(record.cell_label for record, _ in entries),
                total_volume=total_volume,
                weighted_mean=weighted_mean,
            )
        )
    return ZoneBinnedMean(axis=axis, lower=lower, upper=upper, bins=tuple(bins))


def parse_boundary_values_text(
    text: str,
    *,
    patch_name: str,
    expected_count: int,
    entry_name: str = "value",
    source_path: str = "<memory>",
) -> BoundaryFieldValues:
    """Parse one exact boundary patch entry and validate its size and width."""

    tokens = _ascii_tokens(text, source_path)
    class_name, object_name = _parse_header(tokens, source_path)
    kind = _class_kind(class_name)
    dimensions = _parse_dimensions(tokens, source_path)
    header_end = _header_end(tokens, source_path)
    boundary_positions = _direct_key_positions(tokens, header_end + 1, len(tokens), "boundaryField")
    if len(boundary_positions) != 1:
        raise OpenFOAMParseError(
            f"{source_path}: field must define exactly one boundaryField dictionary"
        )
    boundary_opening = boundary_positions[0] + 1
    boundary_closing = _matching_index(tokens, boundary_opening, "{", "}", source_path)
    patch_positions = _direct_key_positions(
        tokens, boundary_opening + 1, boundary_closing, patch_name
    )
    if len(patch_positions) != 1:
        raise OpenFOAMParseError(
            f"{source_path}: patch {patch_name!r} must match exactly once; "
            f"found {len(patch_positions)}"
        )
    patch_opening = patch_positions[0] + 1
    patch_closing = _matching_index(tokens, patch_opening, "{", "}", source_path)
    entry_positions = _direct_key_positions(tokens, patch_opening + 1, patch_closing, entry_name)
    if len(entry_positions) != 1:
        raise OpenFOAMParseError(
            f"{source_path}: patch {patch_name!r} must define exactly one {entry_name!r} entry"
        )
    cursor = _Cursor(tokens, source_path)
    cursor.index = entry_positions[0] + 1
    storage = cursor.take().text
    if storage == "uniform":
        values = _parse_uniform(cursor, kind)
    elif storage == "nonuniform":
        values = _parse_nonuniform(cursor, kind)
    else:
        raise OpenFOAMParseError(f"{source_path}: unsupported boundary storage {storage!r}")
    if cursor.index > patch_closing:
        raise OpenFOAMParseError(f"{source_path}: boundary value crosses its patch dictionary")
    expanded = _expand_values(
        storage,  # type: ignore[arg-type]
        values,
        expected_count=expected_count,
        expected_width=_WIDTH[kind],
        context=f"boundary patch {patch_name!r} entry {entry_name!r}",
    )
    return BoundaryFieldValues(
        source_path=source_path,
        object_name=object_name,
        class_name=class_name,
        patch_name=patch_name,
        entry_name=entry_name,
        dimensions=dimensions,
        field_kind=kind,
        storage=storage,  # type: ignore[arg-type]
        values=expanded,
    )


def parse_boundary_values(
    path: str | Path,
    *,
    patch_name: str,
    expected_count: int,
    entry_name: str = "value",
) -> BoundaryFieldValues:
    source = Path(path)
    return parse_boundary_values_text(
        _read_ascii(source, kind="field"),
        patch_name=patch_name,
        expected_count=expected_count,
        entry_name=entry_name,
        source_path=str(source),
    )


def reduce_boundary_field(
    boundary_values: BoundaryFieldValues,
    topology: BoundaryPatchTopology,
    *,
    component: str,
    operation: ReductionOperation,
) -> BoundaryFieldReduction:
    """Reduce one exact boundary component without inventing face coordinates."""

    if not topology.name or topology.name != boundary_values.patch_name:
        raise OpenFOAMParseError("boundary values and topology must identify the same exact patch")
    if (
        isinstance(topology.n_faces, bool)
        or not isinstance(topology.n_faces, int)
        or topology.n_faces <= 0
        or isinstance(topology.start_face, bool)
        or not isinstance(topology.start_face, int)
        or topology.start_face < 0
    ):
        raise OpenFOAMParseError("boundary topology contains an invalid face range")
    if len(boundary_values.values) != topology.n_faces:
        raise OpenFOAMParseError(
            f"boundary value count {len(boundary_values.values)} does not match "
            f"topology n_faces {topology.n_faces}"
        )
    if boundary_values.storage not in ("uniform", "nonuniform"):
        raise OpenFOAMParseError(f"unsupported boundary storage: {boundary_values.storage!r}")

    index = component_index(boundary_values.field_kind, component)
    width = _WIDTH[boundary_values.field_kind]
    for value in boundary_values.values:
        if len(value) != width or any(
            not isinstance(item, Decimal) or not item.is_finite() for item in value
        ):
            raise OpenFOAMParseError(
                "boundary value width or finiteness does not match the declared field kind"
            )
    selected = tuple(
        (patch_local_index, value[index])
        for patch_local_index, value in enumerate(boundary_values.values)
    )
    if operation == "max":
        comparison = max(value for _, value in selected)
        tied = tuple(item for item in selected if item[1] == comparison)
    elif operation == "min":
        comparison = min(value for _, value in selected)
        tied = tuple(item for item in selected if item[1] == comparison)
    elif operation == "max_abs":
        comparison = max(abs(value) for _, value in selected)
        tied = tuple(item for item in selected if abs(item[1]) == comparison)
    else:
        raise OpenFOAMParseError(f"unsupported reduction operation: {operation!r}")
    return BoundaryFieldReduction(
        source_path=boundary_values.source_path,
        patch_name=boundary_values.patch_name,
        entry_name=boundary_values.entry_name,
        operation=operation,
        component=component,
        component_index=index,
        selected_face_count=topology.n_faces,
        comparison_value=comparison,
        extrema=tuple(
            BoundaryExtremum(
                patch_local_index=patch_local_index,
                mesh_face_label=topology.start_face + patch_local_index,
                value=value,
            )
            for patch_local_index, value in tied
        ),
    )


def _load_validated_boundary_topology_for_mesh(
    mesh: MeshResolution,
) -> tuple[tuple[BoundaryPatchTopology, ...], tuple[int, ...]]:
    mesh = _require_current_mesh_resolution(mesh)
    return _load_boundary_topology_from_provenance(mesh)


def _load_boundary_topology_from_provenance(
    mesh: MeshResolution,
) -> tuple[tuple[BoundaryPatchTopology, ...], tuple[int, ...]]:
    """Load boundary topology from an internally prevalidated mesh resolution."""

    faces = parse_faces(_resolved_primitive_path(mesh, "faces"))
    face_count = len(faces)
    owner = parse_label_list(
        _resolved_primitive_path(mesh, "owner"),
        expected_object="owner",
        expected_count=face_count,
        compact_limit=face_count,
    )
    neighbour = parse_label_list(
        _resolved_primitive_path(mesh, "neighbour"),
        expected_object="neighbour",
        maximum_count=face_count,
        compact_limit=face_count,
    )
    patches = parse_boundary_patches(_resolved_primitive_path(mesh, "boundary"))

    expected_start = len(neighbour)
    for patch in patches:
        if patch.start_face != expected_start:
            raise OpenFOAMParseError(
                f"boundary patch {patch.name!r} starts at face {patch.start_face}; "
                f"expected exact contiguous boundary face {expected_start}"
            )
        expected_start += patch.n_faces
        if expected_start > len(faces):
            raise OpenFOAMParseError(
                f"boundary patch {patch.name!r} face range exceeds face count {len(faces)}"
            )
    if expected_start != len(faces):
        raise OpenFOAMParseError(
            "boundary patches do not cover the exact boundary-face range "
            f"[{len(neighbour)}, {len(faces)})"
        )
    return patches, owner


def validate_boundary_topology_for_mesh(
    mesh: MeshResolution,
) -> tuple[BoundaryPatchTopology, ...]:
    """Bind every boundary patch to the exact internal/boundary face partition."""

    patches, _ = _load_validated_boundary_topology_for_mesh(mesh)
    return patches


def _validated_boundary_topology_for_mesh(
    mesh: MeshResolution,
    patch_name: str,
    *,
    cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...]],
        tuple[tuple[BoundaryPatchTopology, ...], tuple[int, ...]],
    ]
    | None = None,
    mesh_prevalidated: bool = False,
) -> tuple[BoundaryPatchTopology, str, tuple[int, ...]]:
    patch_name = _safe_exact_name(patch_name, context="boundary-patch selector")
    boundary_source = mesh_primitive_source(mesh, "boundary")
    topology_sources = tuple(
        mesh_primitive_source(mesh, primitive) for primitive in _BOUNDARY_TOPOLOGY_PRIMITIVES
    )
    cache_key = (mesh.result_root, topology_sources)
    if cache is not None and cache_key in cache:
        patches, owner = cache[cache_key]
    else:
        if mesh_prevalidated:
            patches, owner = _load_boundary_topology_from_provenance(mesh)
        else:
            patches, owner = _load_validated_boundary_topology_for_mesh(mesh)
        if cache is not None:
            cache[cache_key] = (patches, owner)
    matches = tuple(patch for patch in patches if patch.name == patch_name)
    if len(matches) != 1:
        raise OpenFOAMParseError(
            f"boundary patch {patch_name!r} must match exactly once; found {len(matches)}"
        )
    topology = matches[0]
    has_pair_metadata = topology.owner is not None or topology.neighbour_patch is not None
    if has_pair_metadata:
        if topology.owner is None or topology.neighbour_patch is None:
            raise OpenFOAMParseError(
                f"boundary patch {patch_name!r} has incomplete reciprocal metadata"
            )
        neighbours = tuple(patch for patch in patches if patch.name == topology.neighbour_patch)
        if len(neighbours) != 1:
            raise OpenFOAMParseError(
                f"boundary neighbour patch {topology.neighbour_patch!r} must match exactly once"
            )
        neighbour = neighbours[0]
        validate_reciprocal_boundary_pair(topology, neighbour)
    return topology, boundary_source.relative_path, owner


def _select_boundary_field_for_time_directory(
    root: Path,
    time_directory: NumericDirectory,
    mesh: MeshResolution,
    *,
    field_selector: str,
    patch_name: str,
    owner_zone_name: str,
    component: str,
    entry_name: str = "value",
    require_owner_side: bool = False,
    topology_cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...]],
        tuple[tuple[BoundaryPatchTopology, ...], tuple[int, ...]],
    ]
    | None = None,
    zone_cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...], str],
        tuple[CellSelectionContext, PolyMeshGeometry],
    ]
    | None = None,
    mesh_prevalidated: bool = False,
) -> BoundaryFieldSelection:
    field_path, source_path = _selected_field_path(root, time_directory, field_selector)

    topology, boundary_source, owner_labels = _validated_boundary_topology_for_mesh(
        mesh,
        patch_name,
        cache=topology_cache,
        mesh_prevalidated=mesh_prevalidated,
    )
    if topology.owner is False or (require_owner_side and topology.owner is not True):
        raise OpenFOAMParseError(
            f"boundary patch {topology.name!r} is not the metadata-declared owner side"
        )
    owner_zone_name = _safe_exact_name(owner_zone_name, context="owner-zone selector")
    entry_name = _safe_exact_name(entry_name, context="boundary-entry selector")
    zone_context, _ = _zone_selection_context(
        mesh,
        owner_zone_name,
        cache=zone_cache,
        mesh_prevalidated=mesh_prevalidated,
    )
    zone_labels = zone_context.zone_cell_labels
    patch_owner_labels = boundary_patch_owner_cell_labels(topology, owner_labels, zone_labels)

    values = parse_boundary_values(
        field_path,
        patch_name=topology.name,
        expected_count=topology.n_faces,
        entry_name=entry_name,
    )
    if values.object_name != field_selector:
        raise OpenFOAMParseError(
            f"field selector {field_selector!r} disagrees with FoamFile object "
            f"{values.object_name!r}"
        )
    index = component_index(values.field_kind, component)
    records = tuple(
        BoundaryFaceScalarValue(
            patch_name=topology.name,
            patch_local_index=patch_local_index,
            mesh_face_label=topology.start_face + patch_local_index,
            owner_cell_label=owner_cell_label,
            value=value[index],
        )
        for patch_local_index, (owner_cell_label, value) in enumerate(
            zip(patch_owner_labels, values.values, strict=True)
        )
    )
    return BoundaryFieldSelection(
        context=BoundarySelectionContext(
            mesh=mesh,
            owner_zone_name=owner_zone_name,
            cell_zones_source=zone_context.cell_zones_source,
            boundary_source=boundary_source,
        ),
        source_path=source_path,
        field_selector=field_selector,
        object_name=values.object_name,
        class_name=values.class_name,
        dimensions=values.dimensions,
        field_kind=values.field_kind,
        storage=values.storage,
        entry_name=entry_name,
        patch_topology=topology,
        component=component,
        component_index=index,
        records=records,
    )


def select_boundary_field_at_time(
    result_root: str | Path,
    *,
    field_selector: str,
    patch_name: str,
    owner_zone_name: str,
    component: str,
    entry_name: str = "value",
    exact: str | Decimal | None = None,
    latest: bool = False,
    require_owner_side: bool = False,
) -> BoundaryFieldSelection:
    """Select one exact boundary component with time, topology, and zone binding."""

    root = _canonical_result_root(result_root)
    time_directory = select_numeric_directory(root, exact=exact, latest=latest)
    mesh = resolve_mesh_for_time(root, exact=time_directory.value)
    return _select_boundary_field_for_time_directory(
        root,
        time_directory,
        mesh,
        field_selector=field_selector,
        patch_name=patch_name,
        owner_zone_name=owner_zone_name,
        component=component,
        entry_name=entry_name,
        require_owner_side=require_owner_side,
    )


def select_boundary_field_series(
    result_root: str | Path,
    *,
    field_selector: str,
    patch_name: str,
    owner_zone_name: str,
    component: str,
    entry_name: str = "value",
    require_owner_side: bool = False,
    missing: MissingFieldPolicy = "error",
) -> tuple[BoundaryFieldSelection, ...]:
    """Select one boundary component under an explicit exact-field missing policy."""

    if missing != "error" and missing != "skip":
        raise OpenFOAMParseError(f"unsupported missing-field policy: {missing!r}")
    field_selector = _safe_exact_name(field_selector, context="field selector")
    patch_name = _safe_exact_name(patch_name, context="boundary-patch selector")
    owner_zone_name = _safe_exact_name(owner_zone_name, context="owner-zone selector")
    entry_name = _safe_exact_name(entry_name, context="boundary-entry selector")

    root = _canonical_result_root(result_root)
    directories = discover_numeric_directories(root)
    if not directories:
        raise OpenFOAMParseError(f"no numeric directories below {root}")
    mesh_resolutions = _resolve_mesh_for_directories(root, directories)
    topology_cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...]],
        tuple[tuple[BoundaryPatchTopology, ...], tuple[int, ...]],
    ] = {}
    zone_cache: dict[
        tuple[str, tuple[MeshPrimitiveSource, ...], str],
        tuple[CellSelectionContext, PolyMeshGeometry],
    ] = {}
    selected: list[BoundaryFieldSelection] = []
    for directory, mesh in zip(directories, mesh_resolutions, strict=True):
        try:
            selection = _select_boundary_field_for_time_directory(
                root,
                directory,
                mesh,
                field_selector=field_selector,
                patch_name=patch_name,
                owner_zone_name=owner_zone_name,
                component=component,
                entry_name=entry_name,
                require_owner_side=require_owner_side,
                topology_cache=topology_cache,
                zone_cache=zone_cache,
                mesh_prevalidated=True,
            )
        except _ExactFieldMissing:
            if missing == "skip":
                continue
            raise
        selected.append(selection)
    selections = tuple(selected)
    if not selections:
        raise OpenFOAMParseError(
            f"exact field {field_selector!r} is absent at every numeric modeled time"
        )
    baseline = selections[0]
    for selection in selections[1:]:
        if (
            selection.object_name != baseline.object_name
            or selection.dimensions != baseline.dimensions
            or selection.field_kind != baseline.field_kind
            or selection.component_index != baseline.component_index
            or selection.entry_name != baseline.entry_name
        ):
            raise OpenFOAMParseError(
                f"boundary field {field_selector!r} schema changes across modeled-time directories"
            )
    return selections


def _require_current_boundary_selection(
    selection: BoundaryFieldSelection,
) -> BoundaryFieldSelection:
    if not isinstance(selection, BoundaryFieldSelection):
        raise OpenFOAMParseError(
            "boundary selection must be produced by select_boundary_field_at_time"
        )
    expected = select_boundary_field_at_time(
        selection.context.mesh.result_root,
        field_selector=selection.field_selector,
        patch_name=selection.patch_topology.name,
        owner_zone_name=selection.context.owner_zone_name,
        component=selection.component,
        entry_name=selection.entry_name,
        exact=selection.context.mesh.modeled_time,
        require_owner_side=selection.patch_topology.owner is True,
    )
    if selection != expected:
        raise OpenFOAMParseError(
            "boundary selection is stale, forged, or inconsistent with its result source"
        )
    return selection


def _require_current_boundary_field_series(
    selections: tuple[BoundaryFieldSelection, ...],
) -> tuple[BoundaryFieldSelection, ...]:
    """Rebuild one complete boundary history through the linear series selector."""

    if not selections:
        raise OpenFOAMParseError("boundary field series must not be empty")
    if any(not isinstance(selection, BoundaryFieldSelection) for selection in selections):
        raise OpenFOAMParseError("boundary field series contains an invalid selection")
    baseline = selections[0]
    expected = select_boundary_field_series(
        baseline.context.mesh.result_root,
        field_selector=baseline.field_selector,
        patch_name=baseline.patch_topology.name,
        owner_zone_name=baseline.context.owner_zone_name,
        component=baseline.component,
        entry_name=baseline.entry_name,
        require_owner_side=baseline.patch_topology.owner is True,
        missing="skip",
    )
    if selections != expected:
        raise OpenFOAMParseError(
            "boundary field series is stale, incomplete, forged, or inconsistent with its "
            "result source"
        )
    return selections


def validate_aligned_boundary_selections(
    *selections: BoundaryFieldSelection,
) -> tuple[BoundaryFieldSelection, ...]:
    """Bind multiple patches to one root/time/field/component mesh domain."""

    if len(selections) < 2:
        raise OpenFOAMParseError("multi-patch selection requires at least two patches")
    current = tuple(_require_current_boundary_selection(selection) for selection in selections)
    baseline = current[0]
    patch_names = tuple(selection.patch_topology.name for selection in current)
    if len(set(patch_names)) != len(patch_names):
        raise OpenFOAMParseError("multi-patch selection contains a duplicate patch")
    for index, selection in enumerate(current[1:], start=1):
        if (
            selection.context.mesh != baseline.context.mesh
            or selection.context.boundary_source != baseline.context.boundary_source
            or selection.source_path != baseline.source_path
            or selection.field_selector != baseline.field_selector
            or selection.object_name != baseline.object_name
            or selection.dimensions != baseline.dimensions
            or selection.field_kind != baseline.field_kind
            or selection.entry_name != baseline.entry_name
            or selection.component != baseline.component
            or selection.component_index != baseline.component_index
        ):
            raise OpenFOAMParseError(
                f"boundary field selection {index} does not align with selection 0"
            )
    return current


def reduce_boundary_selections(
    *selections: BoundaryFieldSelection,
    operation: ReductionOperation,
) -> MultiBoundaryFieldReduction:
    """Reduce one or more bound patches without pairing nonconformal faces."""

    if not selections:
        raise OpenFOAMParseError("at least one boundary selection is required")
    current = (
        (_require_current_boundary_selection(selections[0]),)
        if len(selections) == 1
        else validate_aligned_boundary_selections(*selections)
    )
    return _reduce_current_boundary_selections(current, operation=operation)


def _reduce_current_boundary_selections(
    selections: tuple[BoundaryFieldSelection, ...],
    *,
    operation: ReductionOperation,
) -> MultiBoundaryFieldReduction:
    current = selections
    records = tuple(record for selection in current for record in selection.records)
    if operation == "max":
        comparison = max(record.value for record in records)
        extrema = tuple(record for record in records if record.value == comparison)
    elif operation == "min":
        comparison = min(record.value for record in records)
        extrema = tuple(record for record in records if record.value == comparison)
    elif operation == "max_abs":
        comparison = max(abs(record.value) for record in records)
        extrema = tuple(record for record in records if abs(record.value) == comparison)
    else:
        raise OpenFOAMParseError(f"unsupported reduction operation: {operation!r}")
    baseline = current[0]
    return MultiBoundaryFieldReduction(
        source_path=baseline.source_path,
        patch_names=tuple(selection.patch_topology.name for selection in current),
        owner_zone_names=tuple(selection.context.owner_zone_name for selection in current),
        entry_name=baseline.entry_name,
        operation=operation,
        component=baseline.component,
        component_index=baseline.component_index,
        selected_face_count=len(records),
        comparison_value=comparison,
        extrema=extrema,
    )


def reduce_boundary_selection_series(
    selections: tuple[BoundaryFieldSelection, ...],
    *,
    operation: ReductionOperation,
) -> tuple[ModeledTimeResult[MultiBoundaryFieldReduction], ...]:
    """Reduce a complete boundary history after one linear batch revalidation."""

    current = _require_current_boundary_field_series(selections)
    return tuple(
        ModeledTimeResult(
            selection.context.mesh.modeled_time,
            _reduce_current_boundary_selections((selection,), operation=operation),
        )
        for selection in current
    )


def parse_unique_scalar_entry_text(
    text: str, *, key: str, source_path: str = "<memory>"
) -> Decimal:
    """Return one exact finite ``key scalar;`` dictionary entry, rejecting ambiguity."""

    if not key or key in _DELIMITERS:
        raise OpenFOAMParseError(f"invalid exact dictionary key: {key!r}")
    tokens = _ascii_tokens(text, source_path)
    start = _header_end(tokens, source_path) + 1
    _validate_balanced_delimiters(tokens, start, len(tokens), source_path)
    positions = tuple(
        index
        for index in range(start, len(tokens))
        if tokens[index].text == key
        and (index == start or tokens[index - 1].text in {"{", "}", ";"})
    )
    if len(positions) != 1:
        raise OpenFOAMParseError(
            f"{source_path}: scalar key {key!r} must match exactly once; found {len(positions)}"
        )
    cursor = _Cursor(tokens, source_path)
    cursor.index = positions[0] + 1
    value = _decimal(cursor.take().text, context=f"dictionary scalar {key!r}")
    cursor.expect(";")
    return value


def parse_unique_scalar_entry(path: str | Path, *, key: str) -> Decimal:
    source = Path(path)
    return parse_unique_scalar_entry_text(
        _read_ascii(source, kind="dictionary"), key=key, source_path=str(source)
    )


_PROBE = re.compile(r"^\s*#\s*Probe\s+(\d+)\s*\(([^)]*)\)\s*$")
_TIME_HEADER = re.compile(r"^\s*#\s*Time(?:\s+(.*?))?\s*$")


def _parse_probe_row(
    line: str, probe_count: int, context: str
) -> tuple[Decimal, tuple[Value, ...]]:
    tokens = tokenize_openfoam(line, source_path=context)
    cursor = _Cursor(tokens, context)
    modeled_time = _decimal(cursor.take().text, context=f"{context} modeled time")
    values: list[Value] = []
    while cursor.index < len(tokens):
        if tokens[cursor.index].text == "(":
            cursor.take()
            components: list[Decimal] = []
            while cursor.index < len(tokens) and tokens[cursor.index].text != ")":
                components.append(
                    _decimal(cursor.take().text, context=f"{context} probe component")
                )
            cursor.expect(")")
            if len(components) not in _WIDTH.values():
                raise OpenFOAMParseError(
                    f"{context}: unsupported probe component width {len(components)}"
                )
            values.append(tuple(components))
        else:
            values.append((_decimal(cursor.take().text, context=f"{context} probe value"),))
    if len(values) != probe_count:
        raise OpenFOAMParseError(
            f"{context}: expected {probe_count} probe values, found {len(values)}"
        )
    widths = {len(value) for value in values}
    if len(widths) != 1:
        raise OpenFOAMParseError(f"{context}: probe values have inconsistent widths")
    return modeled_time, tuple(values)


def parse_probe_table_text(
    text: str,
    *,
    field_name: str,
    segment_name: str,
    source_path: str = "<memory>",
) -> _ProbeSegment:
    """Parse one standard OpenFOAM probes table segment."""

    locations: dict[int, ProbeLocation] = {}
    declared_slots: tuple[int, ...] | None = None
    data_lines: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        probe_match = _PROBE.fullmatch(line)
        if probe_match:
            index = _non_negative_decimal(
                Token(
                    probe_match.group(1),
                    line_number,
                    probe_match.start(1) + 1,
                ),
                source_path,
                context="probe index",
            )
            parts = probe_match.group(2).split()
            if len(parts) != 3:
                raise OpenFOAMParseError(
                    f"{source_path}:{line_number}: probe coordinate must have 3 components"
                )
            coordinates = tuple(
                _decimal(part, context=f"{source_path}:{line_number} coordinate") for part in parts
            )
            if index in locations:
                raise OpenFOAMParseError(f"{source_path}:{line_number}: duplicate probe {index}")
            locations[index] = ProbeLocation(index, coordinates)  # type: ignore[arg-type]
            continue
        time_match = _TIME_HEADER.fullmatch(line)
        if time_match:
            slot_group = time_match.group(1) or ""
            slot_offset = time_match.start(1) if time_match.group(1) is not None else len(line)
            declared_slots = tuple(
                _non_negative_decimal(
                    Token(slot.group(), line_number, slot_offset + slot.start() + 1),
                    source_path,
                    context="Time column",
                )
                for slot in re.finditer(r"\S+", slot_group)
            )
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            data_lines.append((line_number, stripped))

    if not locations or declared_slots is None:
        raise OpenFOAMParseError(f"{source_path}: probe and Time headers are required")
    ordered_indices = tuple(sorted(locations))
    if ordered_indices != tuple(range(len(locations))) or declared_slots != ordered_indices:
        raise OpenFOAMParseError(f"{source_path}: probe indices and Time columns differ")
    ordered_locations = tuple(locations[index] for index in ordered_indices)

    records: list[ProbeRecord] = []
    width: int | None = None
    for line_number, line in data_lines:
        modeled_time, values = _parse_probe_row(
            line, len(ordered_locations), f"{source_path}:{line_number}"
        )
        row_width = len(values[0])
        if width is not None and row_width != width:
            raise OpenFOAMParseError(f"{source_path}:{line_number}: probe width changed")
        width = row_width
        records.append(ProbeRecord(modeled_time, values, (segment_name,)))
    if not records:
        raise OpenFOAMParseError(f"{source_path}: probe table has no data rows")
    return _ProbeSegment(ordered_locations, width or 0, tuple(records))


def parse_segmented_probe_tables(
    source_root: str | Path,
    relative_directory: str | Path,
    field_name: str,
) -> ProbeSeries:
    """Parse and merge numeric probe segments, deduplicating equal overlaps."""

    root = Path(source_root).resolve()
    relative = Path(relative_directory)
    if relative.is_absolute() or ".." in relative.parts:
        raise OpenFOAMParseError("probe directory must be relative to the result root")
    probe_root = (root / relative).resolve()
    if not probe_root.is_relative_to(root):
        raise OpenFOAMParseError("probe directory escapes the result root")

    segments = discover_numeric_directories(probe_root)
    if not segments:
        raise OpenFOAMParseError(f"no numeric probe segments below {probe_root}")

    expected_locations: tuple[ProbeLocation, ...] | None = None
    expected_width: int | None = None
    merged: dict[Decimal, ProbeRecord] = {}
    source_files: list[str] = []
    for segment in segments:
        field_path = segment.path / field_name
        if not field_path.is_file():
            raise OpenFOAMParseError(f"probe segment lacks {field_name!r}: {segment.path}")
        try:
            text = field_path.read_text(encoding="ascii")
        except (OSError, UnicodeError) as exc:
            raise OpenFOAMParseError(f"cannot read probe table {field_path}: {exc}") from exc
        relative_path = field_path.relative_to(root).as_posix()
        parsed = parse_probe_table_text(
            text,
            field_name=field_name,
            segment_name=segment.name,
            source_path=relative_path,
        )
        source_files.append(relative_path)
        if expected_locations is None:
            expected_locations = parsed.locations
            expected_width = parsed.component_width
        elif parsed.locations != expected_locations or parsed.component_width != expected_width:
            raise OpenFOAMParseError(f"probe schema differs in segment {segment.name!r}")

        for record in parsed.records:
            previous = merged.get(record.modeled_time)
            if previous is None:
                merged[record.modeled_time] = record
            elif previous.values != record.values:
                raise OpenFOAMParseError(
                    f"conflicting probe overlap at modeled time {record.modeled_time}"
                )
            else:
                merged[record.modeled_time] = ProbeRecord(
                    record.modeled_time,
                    record.values,
                    previous.segment_names + record.segment_names,
                )

    return ProbeSeries(
        field_name=field_name,
        locations=expected_locations or (),
        component_width=expected_width or 0,
        records=tuple(merged[time] for time in sorted(merged)),
        parsed_source_files=tuple(source_files),
    )


def select_probe_record(
    series: ProbeSeries,
    *,
    exact: str | Decimal | None = None,
    latest: bool = False,
) -> ProbeRecord:
    """Select one exact or latest modeled-time record without nearest matching."""

    if (exact is None and not latest) or (exact is not None and latest):
        raise OpenFOAMParseError("select exactly one probe-record mode: exact or latest")
    if not series.records:
        raise OpenFOAMParseError("probe series contains no records")
    if latest:
        selected_time = max(record.modeled_time for record in series.records)
    else:
        if exact is None:  # pragma: no cover - guarded by the mode check above
            raise OpenFOAMParseError("exact probe modeled time is required")
        selected_time = _selection_value(
            exact,
            context="exact probe modeled time",
        )
    matches = tuple(record for record in series.records if record.modeled_time == selected_time)
    if len(matches) != 1:
        requested_text = "latest" if latest else f"exact time {exact}"
        raise OpenFOAMParseError(
            f"{requested_text} must identify exactly one probe record; found {len(matches)}"
        )
    return matches[0]
