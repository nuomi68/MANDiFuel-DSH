# Retained radial coordinates

Use this operation for explicit geometry without a generator, or separately
requested retained coordinates. Resolve the named coordinate input and moving
assembly once. Generator-owned dimensions use the parameter edit instead.

For a fresh case using the standard `smallStrainIncrementalUpdated` mechanics
solver, `referenceMesh` is constructed from `constant/polyMesh/points` and the
active mesh topology, then written as output. Regenerating that initial mesh
therefore supplies the new reference geometry; a retained
`constant/referenceMesh` is not a second geometry-edit binding. A restart instead
keeps the original reference geometry and its corresponding state.

The native r-z `rodMaker` applies a wedge-volume correction to vertex radii:
`coordinate_radius = nominal_radius * sqrt(sin(alpha/2)/(alpha/2))`, with `alpha`
in radians. Regeneration handles this convention. A retained-coordinate map must
use coordinate radii rather than substitute nominal radii directly.

```python
from geometry_ops import apply
readback = apply(case, {
    "operation": {"type": "radial-map", "space": "spherical",
                  "radii_m": [[0.0004, 0.00042], [0.0006, 0.00062]]},
    "artifacts": [{"path": "system/blockMeshDict", "format": "openfoam-block-mesh",
                   "selection": {"blocks": ["shell"]}}],
})
```

Pairs are `[source_radius, target_radius]` in increasing order, with linear mapping
between pairs. Equal offsets preserve thickness; different offsets change it.
All lengths are metres. Block coordinates use literal `convertToMeters` or scalar
`scale`; retained points are already metres. Both spaces accept `origin_m`, default
`[0,0,0]`. `space: "cylindrical"` preserves the coordinate along `axis` (`x`, `y`,
or `z`, default `z`). Spherical mapping uses distance from the centre.
Endpoint tolerance defaults to `max(1e-12 m, largest_source_radius * 1e-5)` for ASCII
rounding; override with `radius_tolerance_m` if needed. It does not select points.

Each artifact may select `{"blocks": ["regionName"]}`, `{"patch": "patchName"}`,
`{"connected_to_patch": "patchName"}`, `{"component": 40}` or `{"points": [4,5,6,7]}`.
Omit selection to map all points. Add retained points as another artifact with
`format: "openfoam-points"`. Components use sibling ASCII `faces`; patch names also
use `boundary`. For unresolved membership, `describe(case, artifact)` returns
component IDs and bounds: IDs are representative point IDs, and radius ranges
are about `(0,0,0)`.
With sibling `faces` but an empty `boundary`, it still reports components.
Match the moving assembly's established radial extent to a reported component
and use `{"component": <id>}`; no patch name or point-ID inventory is needed.

Coincident gap surfaces can have distinct IDs: select the requested side by
membership, not radius alone. Components are not necessarily material regions.
IDs differ between representations; resolve each selection once. Shared IDs remain
shared, so this map cannot separate a surface that has no distinct point IDs.
Supported radial arcs must be concentric about the mapping origin.
If the task also bounds radial cell width, uniform radial cells use
`ceil(thickness / width_bound)`; update the corresponding block-local count separately.

The mapping leaves generator parameters and feature-anchored probes to their
separate resolved edits. Complete those bindings for the same target.
