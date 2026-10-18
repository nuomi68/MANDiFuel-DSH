# Practical OpenFOAM result selection

Advanced selection routes complement `scripts/result_api.py` for probe tables,
Decimal reductions, derived responses and special boundary semantics.

For requested field and mesh provenance, use `describe_field(root, variable,
time=...)` and `describe_mesh(root, time=...)` at the established time. The former
returns `variable`, `time`, `unit`, `dimensions` as exact decimal strings, and
`field_path`; the latter returns `time` and a `primitive_sources` mapping from
primitive names to their resolved paths. All paths are relative to the supplied
root, and both mappings can be serialized directly as JSON.

For cell-weighted arithmetic, use `read_field(..., include_volumes=True)`.
`frame.volumes` contains cubic-metre weights aligned with `labels`, `values`,
and `coordinates`, including a nearest-cell selection. The default is `None`;
patch volumes are rejected because face support is not cell support. For
example, after establishing `time` and `zone`:

```python
frame = result_api.read_field(root, "T", time=time, scope=("cellZone", zone),
                              include_volumes=True)
mean = sum(v * w for v, w in zip(frame.values, frame.volumes, strict=True)) / sum(frame.volumes)
```

The thin field values and volumes are floats. When a task requires preserving
stored decimal distinctions beyond float precision, use the public Decimal
selection/reduction route below. Boundary coordinates remain unavailable in the
thin frame; cell centres and face locations represent different supports.

For symmetric cell tensors, `read_field(..., component="principal_max")` or
`extreme(..., component="principal_max")` uses all six stored components together.
It returns the largest algebraic eigenvalue, including a negative value under
all-direction compression; tensile clipping belongs to the requested formula.
This selector supports internal cells and cellZones, not boundary patches.
For custom history reductions, `iter_fields(..., time="all")` yields one frame
at a time with that time's mesh. Filter the requested window by `frame.time`;
`read_field(time="all")` instead retains every frame in memory.

## Advanced selectors

Selector arguments bind the native object, time, support and component. Supports
include an internal cellZone, a boundary/interface patch with its owner region
and entry, or a probe and sample slot.

| Advanced support or operation | Backend public route when needed |
|---|---|
| internal cellZone field | `select_cell_field_at_time`, then `reduce_cell_selection` |
| boundary or interface patch field | `select_boundary_field_at_time`, then `reduce_boundary_selections` |
| segmented probe record | `parse_segmented_probe_tables`, then `select_probe_record` |
| aligned cell operands | `validate_aligned_cell_selections` before arithmetic |
| cylindrical engineering component | `cylindrical_symm_tensor_normal_component` before selection |
| dimensions-to-unit mapping | `canonical_si_unit_for_dimensions` |

These functions are exposed by `scripts/openfoam_parser.py`. A parser rejection
indicates an unavailable or incompatible selection; unsupported file syntax can
use a fallback reader for the same selected object and support.

## Choose the physical support

- Cell selectors bind field, exact cellZone labels, and the mesh for that time.
  Do not reduce a whole internal field or infer membership from case names,
  nominal radii, probe locations, or array length.
- Boundary selectors bind exact field object, patch, entry, owner region,
  topology, component, and time. An `internalField` in the same object does not
  make a requested interface quantity cell-internal.
- Probe selectors use actual segmented table metadata, probe slot, component,
  and modeled-time key. Do not join probe rows by position across restarts.

### Conditional OFFBEAT producer notes

Use these notes only when local case documentation or a compatible bundled
OFFBEAT producer contract confirms the standard object semantics; explicit case
documentation takes precedence. Contact/interface result objects may carry the
physical values on an owner-side boundary while their internal values are
placeholders or sentinels. Under that contract, native `gapWidth` and
`interfaceP` interface responses use the appropriate owner-side boundary, not
the internal placeholder.

The native cylindrical stress object (`sigmaCyl`) maps radial, hoop and axial
through `cylindrical_symm_tensor_normal_component`. A derivation from Cartesian
stress requires the corresponding basis transformation.

## Select, reduce, and report

For a cellZone reduction:

```python
selected = api.select_cell_field_at_time(
    result_root,
    field_selector=field,
    zone_name=zone,
    component=component,
    exact=requested_time,
)
reduced = api.reduce_cell_selection(selected, operation=operation)
unit = api.canonical_si_unit_for_dimensions(selected.dimensions)
```

For a boundary reduction, use the analogous boundary selector with
`patch_name`, `owner_zone_name`, `entry_name`, and the same exact time, followed
by `reduce_boundary_selections`. Use `value` for a scalar; use public component
names or mappings for vectors and tensors. For `max_abs`, the comparison value
is unsigned; retain signed ties and locations only when the task requests them.

A native result object takes precedence over an agent-reconstructed proxy. A
derived response is valid only when the task or maintained source semantics
defines the formula. Select every operand from the same root, time, support, and
mesh; validate alignment before arithmetic. A fallback may decode an unsupported
syntax but cannot change the object, support, component, formula, or reduction.

## Time selection

- Pass an explicitly requested time as `exact` and require its field or probe
  record. For exact-final extraction, use the numerically equal `endTime` already
  established by Execute.
- Bind what `latest` means before selection. Use `latest=True` only for the
  latest numeric case time; use the series APIs for the latest time containing a
  selected object or the latest common aligned time. Do not switch among these
  meanings after seeing which one has data.
- Series APIs align histories by exact modeled-time keys, including across
  restarts; row position does not establish time alignment.
