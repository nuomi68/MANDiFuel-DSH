"""Small public result API backed by the full OpenFOAM parser."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
import math
from pathlib import Path
from typing import Literal

import openfoam_parser as _backend


type TimeSelector = str | int | float | Decimal
type Scope = Literal["internal", "all"] | tuple[Literal["cellZone", "patch"], str]
type Location = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class FieldFrame:
    """One scalar component, with optional aligned cell volumes in cubic metres."""

    variable: str
    time: str
    scope: str
    component: str
    unit: str | None
    labels: tuple[int, ...]
    coordinates: tuple[Location | None, ...]
    values: tuple[float, ...]
    volumes: tuple[float, ...] | None = None


def _time_kwargs(time: TimeSelector) -> dict[str, object]:
    if time == "latest":
        return {"latest": True}
    if time == "all":
        raise ValueError("'all' is valid only for series-aware public calls")
    if isinstance(time, bool) or not isinstance(time, (str, int, float, Decimal)):
        raise TypeError("time must be an exact value, 'latest', or 'all'")
    return {"exact": str(time)}


def _component_name(component: str) -> str:
    if component in ("radial", "hoop", "axial"):
        return _backend.cylindrical_symm_tensor_normal_component(component)
    return component


def _principal_max(values: Sequence[Decimal | float | int]) -> float:
    """Largest eigenvalue of a symmetric tensor in OpenFOAM component order."""
    numbers = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in numbers):
        raise ValueError("principal_max requires finite tensor components")
    scale = max(abs(value) for value in numbers)
    if scale == 0:
        return 0.0
    xx, xy, xz, yy, yz, zz = (value / scale for value in numbers)
    if xy == xz == yz == 0:
        return max(xx, yy, zz) * scale
    q = (xx + yy + zz) / 3
    p = math.sqrt(((xx-q)**2 + (yy-q)**2 + (zz-q)**2 + 2*(xy*xy+xz*xz+yz*yz))/6)
    if p == 0:
        return q * scale
    a, b, c = (xx-q)/p, (yy-q)/p, (zz-q)/p
    d, e, f = xy/p, xz/p, yz/p
    determinant = a*b*c + 2*d*e*f - a*f*f - b*e*e - c*d*d
    angle = math.acos(max(-1.0, min(1.0, determinant / 2))) / 3
    return (q + 2*p*math.cos(angle)) * scale


def _principal_frame(root: Path, variable: str, time: str, scope: Scope,
                     include_volumes: bool, *, resolved_mesh=None) -> FieldFrame:
    directory = _backend.select_numeric_directory(root, exact=time)
    path, _ = _backend._selected_field_path(root, directory, variable)
    field = _backend.parse_field(path)
    if field.object_name != variable or field.class_name != "volSymmTensorField":
        raise ValueError("principal_max requires the selected volSymmTensorField")
    mesh = resolved_mesh or _backend.resolve_mesh_for_time(root, exact=directory.value)
    if scope in ("internal", "all"):
        geometry = _geometry(mesh, prevalidated=resolved_mesh is not None)
        labels = tuple(range(len(geometry.cell_centres)))
        scope_name = "internal"
    elif isinstance(scope, tuple) and len(scope) == 2 and scope[0] == "cellZone":
        context, geometry = _backend._zone_selection_context(
            mesh, scope[1], mesh_prevalidated=resolved_mesh is not None)
        labels, scope_name = context.zone_cell_labels, f"cellZone:{scope[1]}"
    else:
        raise ValueError("principal_max requires an internal or cellZone scope")
    values = _backend.expand_internal_field(field, len(geometry.cell_centres))
    return FieldFrame(variable, directory.name, scope_name, "principal_max",
                      _backend.canonical_si_unit_for_dimensions(field.dimensions), labels,
                      tuple(tuple(float(v) for v in geometry.cell_centres[i]) for i in labels),
                      tuple(_principal_max(values[i]) for i in labels),
                      tuple(float(geometry.cell_volumes[i]) for i in labels) if include_volumes else None)


def _geometry(mesh: _backend.MeshResolution, *, prevalidated: bool):
    if prevalidated:
        return _backend.reconstruct_poly_mesh_geometry(
            *_backend._load_mesh_primitives_from_provenance(mesh))
    return _backend.load_resolved_poly_mesh_geometry(mesh)


def _mesh_path(mesh: _backend.MeshResolution, primitive: str) -> Path | None:
    source = next(
        (item for item in mesh.primitive_sources if item.name == primitive), None
    )
    return None if source is None else Path(mesh.result_root) / source.relative_path


def list_times(
    result_root: str | Path,
    variable: str | None = None,
    *,
    source: str = "fields",
) -> tuple[str, ...]:
    """List numeric solver or post-processing times, optionally containing a file."""

    parent = Path(result_root) if source == "fields" else Path(result_root) / source
    directories = _backend.discover_numeric_directories(parent)
    if variable is not None:
        directories = tuple(item for item in directories if (item.path / variable).is_file())
    return tuple(item.name for item in directories)


def list_variables(
    result_root: str | Path,
    *,
    time: TimeSelector = "latest",
) -> dict[str, dict[str, object]]:
    """Describe readable volume fields at one time or across all solver times."""

    root = Path(result_root)
    if time == "all":
        directories = _backend.discover_numeric_directories(root)
    else:
        directories = (_backend.select_numeric_directory(root, **_time_kwargs(time)),)
    found: dict[str, dict[str, object]] = {}
    for directory in directories:
        for path in sorted(directory.path.iterdir()):
            if not path.is_file():
                continue
            try:
                field = _backend.parse_field(path)
            except _backend.OpenFOAMParseError:
                continue
            info = {
                "class": field.class_name,
                "components": _backend.component_names(field.field_kind),
                "unit": _backend.canonical_si_unit_for_dimensions(field.dimensions),
            }
            previous = found.get(field.object_name)
            if previous is not None and previous != info:
                raise ValueError(f"field schema changes across time: {field.object_name}")
            found[field.object_name] = info
    return dict(sorted(found.items()))


def list_scopes(
    result_root: str | Path,
    *,
    time: TimeSelector = "latest",
) -> dict[str, tuple[str, ...]]:
    """List named cell zones and boundary patches for one resolved mesh."""

    mesh = _backend.resolve_mesh_for_time(result_root, **_time_kwargs(time))
    zones_path = _mesh_path(mesh, "cellZones")
    boundary_path = _mesh_path(mesh, "boundary")
    zones = () if zones_path is None else tuple(
        zone.name for zone in _backend.parse_cell_zones(zones_path)
    )
    patches = () if boundary_path is None else tuple(
        patch.name for patch in _backend.parse_boundary_patches(boundary_path)
    )
    return {"cellZones": zones, "patches": patches}


def describe_field(
    result_root: str | Path,
    variable: str,
    *,
    time: TimeSelector = "latest",
) -> dict[str, object]:
    """Return one field's binding; dimensions are exact, JSON-safe decimal strings."""

    root = Path(result_root)
    directory = _backend.select_numeric_directory(root, **_time_kwargs(time))
    path = directory.path / variable
    (relative_path,) = _backend.validate_source_paths(root, path)
    if relative_path != f"{directory.name}/{variable}":
        raise ValueError("field path does not match the selected time and variable")
    field = _backend.parse_field(path)
    if field.object_name != variable or not field.class_name.startswith("vol"):
        raise ValueError(f"{variable!r} is not the requested volume field")
    return {
        "variable": variable,
        "time": directory.name,
        "unit": _backend.canonical_si_unit_for_dimensions(field.dimensions),
        "dimensions": tuple(str(value) for value in field.dimensions),
        "field_path": relative_path,
    }


def describe_mesh(
    result_root: str | Path,
    *,
    time: TimeSelector = "latest",
) -> dict[str, object]:
    """Return the time-bound mesh primitive paths relative to the supplied root."""

    mesh = _backend.resolve_mesh_for_time(result_root, **_time_kwargs(time))
    return {
        "time": mesh.time_directory,
        "primitive_sources": {
            item.name: item.relative_path for item in mesh.primitive_sources
        },
    }


def _internal_frame(
    root: Path,
    variable: str,
    time: str,
    component: str,
    include_volumes: bool,
    *, resolved_mesh=None,
) -> FieldFrame:
    directory = _backend.select_numeric_directory(root, exact=time)
    mesh = resolved_mesh or _backend.resolve_mesh_for_time(root, exact=directory.value)
    geometry = _geometry(mesh, prevalidated=resolved_mesh is not None)
    field = _backend.parse_field(directory.path / variable)
    if field.object_name != variable or not field.class_name.startswith("vol"):
        raise ValueError(f"{variable!r} is not the requested volume field")
    index = _backend.component_index(field.field_kind, component)
    expanded = _backend.expand_internal_field(field, len(geometry.cell_centres))
    return FieldFrame(
        variable,
        directory.name,
        "internal",
        component,
        _backend.canonical_si_unit_for_dimensions(field.dimensions),
        tuple(range(len(expanded))),
        tuple(tuple(float(item) for item in point) for point in geometry.cell_centres),
        tuple(float(value[index]) for value in expanded),
        tuple(float(value) for value in geometry.cell_volumes) if include_volumes else None,
    )


def _zone_frame(
    root: Path,
    variable: str,
    time: str,
    zone: str,
    component: str,
    include_volumes: bool,
    *, resolved_mesh=None,
) -> FieldFrame:
    if resolved_mesh is None:
        selected = _backend.select_cell_field_at_time(
            root, field_selector=variable, zone_name=zone, component=component, exact=time)
    else:
        selected = _backend._select_cell_field_for_time_directory(
            root, _backend.select_numeric_directory(root, exact=time), resolved_mesh,
            field_selector=variable, zone_name=zone, component=component, mesh_prevalidated=True)
    return FieldFrame(
        variable,
        selected.context.mesh.time_directory,
        f"cellZone:{zone}",
        component,
        _backend.canonical_si_unit_for_dimensions(selected.dimensions),
        tuple(row.cell_label for row in selected.records),
        tuple(tuple(float(item) for item in row.centre) for row in selected.records),
        tuple(float(row.value) for row in selected.records),
        tuple(float(value) for value in selected.volumes) if include_volumes else None,
    )


def _patch_frame(
    root: Path,
    variable: str,
    time: str,
    patch: str,
    component: str,
    owner_zone: str | None,
    entry_name: str,
) -> FieldFrame:
    if owner_zone is None:
        raise ValueError("owner_zone is required for a boundary patch")
    selected = _backend.select_boundary_field_at_time(
        root,
        field_selector=variable,
        patch_name=patch,
        owner_zone_name=owner_zone,
        component=component,
        entry_name=entry_name,
        exact=time,
    )
    return FieldFrame(
        variable,
        selected.context.mesh.time_directory,
        f"patch:{patch}",
        component,
        _backend.canonical_si_unit_for_dimensions(selected.dimensions),
        tuple(row.mesh_face_label for row in selected.records),
        (None,) * len(selected.records),
        tuple(float(row.value) for row in selected.records),
    )


def _at_location(frame: FieldFrame, location: Location | None) -> FieldFrame:
    if location is None:
        return frame
    if len(location) != 3 or not all(isinstance(item, (int, float)) for item in location):
        raise ValueError("location must be a finite (x, y, z) tuple")
    candidates = tuple(
        (index, point) for index, point in enumerate(frame.coordinates) if point is not None
    )
    if not candidates:
        raise ValueError("coordinate selection is unavailable for this scope")
    index, _ = min(
        candidates,
        key=lambda item: sum((a - b) ** 2 for a, b in zip(item[1], location, strict=True)),
    )
    return FieldFrame(
        frame.variable,
        frame.time,
        frame.scope,
        frame.component,
        frame.unit,
        (frame.labels[index],),
        (frame.coordinates[index],),
        (frame.values[index],),
        (frame.volumes[index],) if frame.volumes is not None else None,
    )


def iter_fields(
    result_root: str | Path,
    variable: str,
    *,
    time: TimeSelector = "latest",
    scope: Scope = "internal",
    component: str = "value",
    location: Location | None = None,
    owner_zone: str | None = None,
    entry_name: str = "value",
    include_volumes: bool = False,
) -> Iterator[FieldFrame]:
    """Yield selected frames one time at a time, including moving-mesh geometry."""

    root = _backend._canonical_result_root(result_root)
    times = list_times(root, variable) if time == "all" else (
        _backend.select_numeric_directory(root, **_time_kwargs(time)).name,
    )
    component = _component_name(component)
    meshes = {}
    cell_scope = scope in ("internal", "all") or (
        isinstance(scope, tuple) and len(scope) == 2 and scope[0] == "cellZone")
    if time == "all" and times and cell_scope:
        # Keep mesh events even at times with no selected field. This is a local
        # snapshot for a completed result tree, not a cache surviving later calls.
        directories = tuple(d for d in _backend.discover_numeric_directories(root)
                            if d.value <= Decimal(times[-1]))
        try:
            _backend.resolve_mesh_for_time(root, exact=directories[0].value)
        except _backend.OpenFOAMParseError:
            # An earlier, unselected time can predate the first available mesh.
            # Preserve the single-time selector's behavior in that case.
            pass
        else:
            meshes = {m.time_directory: m for m in _backend._resolve_mesh_for_directories(
                root.resolve(), directories)}
    found = False
    for selected_time in times:
        if component == "principal_max":
            frame = _principal_frame(root, variable, selected_time, scope, include_volumes,
                                     resolved_mesh=meshes.get(selected_time))
        elif scope in ("internal", "all"):
            frame = _internal_frame(root, variable, selected_time, component, include_volumes,
                                    resolved_mesh=meshes.get(selected_time))
        elif isinstance(scope, tuple) and len(scope) == 2 and scope[0] == "cellZone":
            frame = _zone_frame(root, variable, selected_time, scope[1], component, include_volumes,
                                resolved_mesh=meshes.get(selected_time))
        elif isinstance(scope, tuple) and len(scope) == 2 and scope[0] == "patch":
            if include_volumes:
                raise ValueError("include_volumes requires a cell scope, not a boundary patch")
            frame = _patch_frame(
                root, variable, selected_time, scope[1], component, owner_zone, entry_name
            )
        else:
            raise ValueError("scope must be 'internal', ('cellZone', name), or ('patch', name)")
        found = True
        yield _at_location(frame, location)
    if not found:
        raise ValueError(f"no readable {variable!r} field at the selected times")


def read_field(result_root: str | Path, variable: str, *,
               time: TimeSelector = "latest", scope: Scope = "internal",
               component: str = "value", location: Location | None = None,
               owner_zone: str | None = None, entry_name: str = "value",
               include_volumes: bool = False) -> FieldFrame | tuple[FieldFrame, ...]:
    """Read a scalar component or principal_max; 'all' materializes the frames."""
    frames = tuple(iter_fields(result_root, variable, time=time, scope=scope,
                              component=component, location=location, owner_zone=owner_zone,
                              entry_name=entry_name, include_volumes=include_volumes))
    return tuple(frames) if time == "all" else frames[0]


def extreme(
    result_root: str | Path,
    variable: str,
    *,
    operation: Literal["max", "min", "max_abs"] = "max",
    details: bool = False,
    **selection: object,
) -> float | dict[str, object]:
    """Reduce a selected field over one time or all times; return a float by default."""

    if operation not in ("max", "min", "max_abs"):
        raise ValueError("operation must be 'max', 'min', or 'max_abs'")
    comparison, unit, matches = None, None, []
    for frame in iter_fields(result_root, variable, **selection):
        for index, value in enumerate(frame.values):
            candidate = abs(value) if operation == "max_abs" else value
            better = comparison is None or (candidate < comparison if operation == "min" else candidate > comparison)
            if better:
                comparison, unit, matches = candidate, frame.unit, []
            if details and candidate == comparison:
                matches.append({"time": frame.time, "signed_value": value,
                                "label": frame.labels[index], "coordinate": frame.coordinates[index]})
    if comparison is None:
        raise ValueError("selected field contains no values")
    if not details:
        return comparison
    return {"value": comparison, "unit": unit, "matches": tuple(matches)}


__all__ = [
    "FieldFrame",
    "list_times",
    "list_variables",
    "list_scopes",
    "describe_field",
    "describe_mesh",
    "read_field",
    "iter_fields",
    "extreme",
]
