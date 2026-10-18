---
name: extract-offbeat-results
description: Extract requested physical responses from completed OFFBEAT/OpenFOAM results.
---

# Extract the requested OFFBEAT result

Extract physical responses from completed result trees through
`scripts/result_api.py`. A scalar response can be returned as one float.

## Select the response

The selection consists of the requested native object or formula, physical
support, modeled time, component, reduction and unit. Shared time-window limits
apply to every response in that window. Common calls are:

```python
list_times(result_root, variable=None, source="fields")
list_variables(result_root, time="latest")
list_scopes(result_root, time="latest")
read_field(result_root, variable, time=..., scope=..., component=..., location=...)
extreme(result_root, variable, operation=..., time=..., scope=..., component=...)
```

`list_scopes` returns a mapping with `cellZones` and `patches`.
`time` accepts an exact modeled time, `"latest"`, or `"all"`. `scope` accepts
`"internal"` for the complete cell domain, `("cellZone", name)`, or
`("patch", name)`; a patch also takes `owner_zone`. A `location=(x, y, z)`
selects the nearest stored cell centre inside the chosen cell scope.
For a material-region response, use the corresponding named cellZone from the
mesh or its generator definition. Its internal-cell extremum includes every cell
in that zone, including cells adjacent to a boundary. An inner radial ring or a
patch-owner subset requires a request for that narrower support. Patch values
answer boundary questions.
`read_field` returns values aligned with labels and coordinates, while `extreme`
returns one float by default and can return location/time details when requested.
With `operation="max_abs"`, that float is the nonnegative magnitude used in
absolute-limit formulas; `details=True` retains signed values in `matches`.
Active standard OFFBEAT mechanics writes Cartesian `sigma`, a symmetric stress
tensor in Pa. `mechanicsSolverOptions/cylindricalStress on` additionally writes
`sigmaCyl` in the radial/hoop/axial basis about the z-axis. Use `sigma` with
`component="principal_max"` for its largest eigenvalue in one field/mesh read;
use `sigmaCyl` with `component="hoop"` for circumferential stress. A tensile-only
definition applies `max(0, value)` after the principal selection. The same
`principal_max` selector accepts other symmetric cell tensors.
`extreme(time="all")` reduces one time at a time;
`iter_fields(..., time="all")` streams frames for custom history formulas.
`"all"` includes time zero when that field is stored there; filter a requested
window by each frame's modeled time. Saved times belong to each result root and
field: `list_times(root, variable=...)` finds available field times, which can
differ between evaluations even with the same output controls.
At one selected time, a spatial maximum answers a state question. `"all"` instead
answers a maximum over stored frames; sparse writes do not establish a continuous
history peak or monotonic evolution. A probe history retains its sampled spatial
support and does not substitute for a cellZone-wide maximum. Bind each response
to the requested time support before choosing either route.

[Advanced result selection](references/openfoam-result-discovery.md) provides
metadata, volumes, probe tables, Decimal reductions and boundary semantics when
the requested response needs them.
[OFFBEAT unit evidence](references/offbeat-result-units.md) covers native quantities
whose field dimensions do not establish their physical units.

## Reuse the selected response

Retain a successful response with its selection for reuse by the caller.
Exports, plots and reports serialize it; replay code uses the same API selection.
History peaks, locations, alternate components and mesh-derived quantities are
additional selections when the task requests them. A successful Study response
already supplies that report column; consume it without another API call.

Modeled-time keys, fields, supports, components, stored signs and requested ties
are exact selection semantics. Derived means, volumes and fractions have the
task's tolerance or the numerical precision of their operands and computation;
decimal-string identity is not a numerical accuracy criterion.

Return the requested scalar or mapping, with unavailable responses identified.
