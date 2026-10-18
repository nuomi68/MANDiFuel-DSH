# Generator-owned rod and particle dimensions

Edit the source generator's parameter input. For a solve using a supplied runner
that invokes this generator, the parameter edit completes preparation; the runner
produces the dictionary and mesh. For a requested dictionary deliverable, invoke
the generator in the target and place its output at `system/blockMeshDict`.
The generator owns derived vertices and mesh representation.

| Binding | Meaning |
| --- | --- |
| 1D or 2D r-z rod: `rodDict` -> `rodMaker.py` | `rInnerFuel` / `rOuterFuel` and clad counterparts are block radii; `heightFuel` / `heightClad` and offsets set axial geometry. Lengths use `convertToMeters`. The script writes `blockMeshDict` in its working directory; place it at `system/blockMeshDict` when delivering that dictionary. |
| Parameterized 3D rod: `rod3Ddict.json` -> `rod3Dmaker.py` | `fuelInnerRadius` / `fuelOuterRadius`, `cladInnerRadius` / `cladOuterRadius`, `rodHeight`, `center` and `unit` define the rod. The native script reads the first array entry and writes `blockMeshDict`. |
| TRISO: `sphereDict` -> the source's `sphereMaker.py` or `octantSphereMaker.py` | `rKernel` is a radius; `tBuffer`, `tIPyC`, `tSiC`, `tOPyC` are thicknesses. In the common enabled-layer convention, gap follows Buffer: IPyC inner = `rKernel + tBuffer + gap`; IPyC outer adds `tIPyC`. The source generator supplies the spherical mesh representation. |

Serialize derived dimensions with enough significant digits to retain their
relationships; the supplied generator handles conversion to vertex coordinates.

At a corresponding axial section, radial gap = clad inner radius - fuel outer
radius, and wall thickness = clad outer radius - clad inner radius. Increasing
fuel radius while holding both fixed shifts both cladding radii by the same amount.
For the standard fuel-material cold-dimension entries in
`constant/solverDict/materials/<fuel>`, `DiamCold` is the fuel outer diameter and
`GapCold` is the diametral fuel-cladding gap, both in metres:
`DiamCold = 2*rOuterFuel`, `GapCold = 2*(rInnerClad-rOuterFuel)` after unit
conversion. Include these existing entries in the geometry edit when the
corresponding dimensions change. Separate cap radii and fixed-space probes are
not coupled by equal numbers alone.

For the enabled-layer sphere convention above, changing `gap` by `dg` shifts
all IPyC, SiC and OPyC radii by `dg`, leaving Kernel and Buffer fixed. An
IPyC-SiC interface probe has radius `rKernel + tBuffer + gap + tIPyC`, converted
to metres. In the standard OFFBEAT `trisoGap` model, `jumpDistance` is a thermal
jump contribution, separate from the geometry-derived gap width; a geometry-only
edit preserves that input.
