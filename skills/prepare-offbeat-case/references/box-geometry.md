# Box dimensions and cell widths

Use `box-resize` for an explicit block mesh and retained ASCII OpenFOAM points.
Resolve the dimensions, units and fixed corner from the named input. For geometry
owned by an existing generator, edit its parameters and regenerate the dictionary;
apply a coordinate map only to separately required retained geometry.

```python
from geometry_ops import apply
readback = apply(case, {
    "operation": {"type": "box-resize", "size_m": [0.003, 0.002, 0.001]},
    "artifacts": [{"path": "system/blockMeshDict", "format": "openfoam-block-mesh"}],
})
```

Lengths are metres. The helper converts block coordinates using literal
`convertToMeters` or scalar `scale`; retained points are already metres. The minimum
corner stays fixed unless `origin_m` is supplied. All vertices are mapped.
Add retained points as another artifact with `format: "openfoam-points"` when needed.

Optional `cell_size_m` is one maximum nominal width or three global-axis widths.
Automatic ceiling counts require one axis-aligned eight-vertex hex. A hex's three
counts follow its **block-local** directions; their order need not be global x/y/z.
For other layouts, retain counts or edit their established bindings separately.
Counts alone do not move interfaces. Anisotropic resizing of a circular arc needs
another edge representation; uniform scaling supports the existing curved controls.

`describe(case, artifact)` reports bounds and membership. The `apply` return
includes bounds in metres and requested counts. A requested
centre probe uses the midpoint of those bounds; finish that binding separately.
