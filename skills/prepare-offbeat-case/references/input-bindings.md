# OFFBEAT input bindings

Select the row for the requested change. Paths describe common fresh cases;
selected models, `#include` and `file` entries identify the actual data owner.
Generator inputs in Python-literal `rodDict` / `sphereDict` use Python or text
edits; they are not OpenFOAM dictionaries. Keyed OpenFOAM fragments, including
headerless includes, use the native entry helper below.

| Requested change | File responsible | Entry and meaning |
| --- | --- | --- |
| Initial or boundary temperature | `0/T` | `internalField` initializes the field; `boundaryField/<patch>` defines the thermal boundary condition. See the boundary entries below. |
| Displacement restraint or contact | `0/D` or `0/DD`, according to the mechanics solver | `boundaryField/<patch>` defines restraints, traction or contact. A `gapContact` patch holds contact options such as `frictionCoefficient`. |
| Coolant pressure | Displacement boundary input or `constant/solverDict` → `rheologyOptions`, and its referenced table | Follow the selected `coolantPressureList.file`, often `constant/systemPressure`; change the pressure data there. |
| Rod cold dimensions | Generator parameters and `constant/solverDict/materials/<fuel>` | Existing `DiamCold` and `GapCold` accompany radius and gap changes; use the generator-dimension bindings from Prepare. |
| Initial gap-gas state | `0/gapGas` | `gasPressure` (Pa), `gasPressureType` and `massFractions` (mass fractions, not mole fractions). With `fromModel`, pressure evolves through the gas model. |
| LHGR or volumetric power history | `constant/solverDict` → `heatSourceOptions` | Parallel `timePoints` and `lhgr` (W/m) or `vhgr` (W/m³) lists, according to the selected `heatSource`, with `timeInterpolationMethod`. |
| Prescribed fast-flux history | `constant/solverDict` → `fastFluxOptions` | Its own `timePoints` / `fastFlux` lists. `0/neutronFlux0`, when present, instead supplies a solved neutron-flux field's initial and boundary values. |
| Axial power profile | `constant/solverDict` → `heatSourceOptions/axialProfile`, often including `constant/axialProfile` | Consuming `type`, included data, `axialLocations`, profile `timePoints` and `axialInterpolationMethod` jointly define the profile. Edit included data in its defining file. |
| Physical model selection | `constant/solverDict` | Top-level selectors such as `thermalSolver`, `mechanicsSolver`, `heatSource`, `gapGas` and `fgr`, with their corresponding options dictionaries. |
| SCIANTIX model settings | Case-root `input_settings.txt`, when supplied | Model switches consumed by the SCIANTIX coupling; retain these with the case when changing geometry or loads. |
| Material properties or constitutive models | `constant/solverDict` → `materials/<material-or-zone-group>` | Material identity, reference temperature, density fraction, enrichment, conductivity, swelling, creep or failure-model inputs belong to the selected material entry. |
| Duration, time stepping, restart or writing | `system/controlDict` | `startFrom`, `startTime`, `endTime`, `deltaT`, adaptive-step controls, `writeControl` and `writeInterval`. |
| Numerical convergence or relaxation | `system/fvSolution` | `solvers`, outer-correction settings such as `stressAnalysis`, and `relaxationFactors`. Physical model choices belong to `constant/solverDict`. |
| Discretization schemes | `system/fvSchemes` | Time-derivative, gradient, divergence and Laplacian schemes. |
| Monitors and sampling | `system/controlDict` → `functions`, or included `system/probes` / `system/sample` | Requested fields and function-specific `axialPositions`, `probeLocations`, `points` or sampling endpoints. |

For the standard ESI `coolantPressureList` table, `interpolationScheme` defaults
to `linear`. `outOfBounds clamp` holds the first/last pressure outside the table's
time range; it is not a pressure limit. The displacement patch and rheology with
`modifiedPlaneStrain on` may share the file; one edit serves both consumers.
Explicit table settings take precedence. Other table types use their own selectors.

For fresh FRAPCON gap gas, an absent or nonpositive `gasMass` lets the model
initialize mass from pressure, composition and its modeled gas volumes and
temperatures. A positive `gasMass` supplies that initial inventory instead.
Preserve restart inventory; a requested refill uses the fresh-state inputs.

For a tabulated load, modify the requested values on the existing time grid.
`controlDict/endTime` stops the solve; it does not truncate load-table support.
Retain a template's later final knot when changing load levels or solve duration;
change the grid or interpolation when that is part of the requested load history.
The LHGR input is in W/m, so a value in kW/m is multiplied by 1000. Axial and
radial profiles can make local output power differ from this input. The entry
readback establishes the requested setting; a field-integrated power is a
separate response when requested.

In `0/T`, the selected patch `type` determines the load entry: `fixedValue` uses
`value`; `uniformFixedValue` uses `uniformValue` (which may be a time table);
`convectiveHTC` uses sink temperature `T0` and coefficient `h`;
`radiativeConvectiveSink` uses `T0`, `alpha` and `emissivity`. For the latter
conditions, `value` initializes the patch and does not replace these load inputs.
Use the existing patch or quoted patch group that applies to the requested surface.
`system/blockMeshDict` defines mesh patches; field files assign their thermal and
mechanical conditions. For a load change on an existing patch, edit the field
condition or its referenced data.

When the task requests exact equal modeled-time output intervals, use
`writeControl adjustableRunTime` with `writeInterval` from modeled duration /
interval count. Plain `runTime` may miss
the exact instants with varying steps.

For tabulated rod profiles, `constantTabulated` consumes one flat value list;
retained time entries alone do not make it a matrix. `timeDependentTabulated`
consumes one row per profile time and one column per axial location. Its stationary
replacement repeats the same row. `axialLocations` normally spans normalized fuel
height 0–1; this time grid is independent of the LHGR grid. A piecewise-linear
profile uses `axialInterpolationMethod linear`; editing values alone leaves a
retained `step` method unchanged. Preserve unrelated grids and amplitudes.

Normalize an axial profile using its selected interpolation; the mean of its
nodes is not generally the spatial mean. The selected type, table shape,
interpolation and requested integral define this input edit. Their readback
completes preparation; output-power analysis is a separate requested response.

With the block-stacked `rodMaker.py` convention, a whole-fuel height fraction `f`
maps to `convertToMeters * (offsetFuel + f * sum(heightFuel))` metres. Other
constructors or fractions within one block use their actual origin and extent.
Move only feature-anchored monitors; keep duplicate `points` / `probeLocations`
entries aligned when they represent the same probe in different distributions.

## Native entry operation

Entries use slash-separated dictionary paths:

```python
from foam_edit import set_foam_entry
readback = set_foam_entry(case, file="constant/solverDict",
                          entry="heatSourceOptions/lhgr", value="(0 18000 18000)")
```

The helper replaces an existing entry through `foamDictionary` and returns
`file`, `entry` and native readback in `value`.
Scalars, tables and whole dictionary values use OpenFOAM syntax. On the CLI,
omitting both set options reads the entry. Edit included entries in their defining
file; the helper keeps includes and macros unexpanded.

An include with `timePoints`, `axialLocations` and `data` is a keyed dictionary
fragment even without a `FoamFile` header. Edit its `data` entry directly with
the same helper. For a multiline matrix, put only the replacement value in a file:

```bash
python3 <skill-dir>/scripts/foam_edit.py --case <target> --file constant/axialProfile --entry data --set-file <matrix-value-file>
```

The native writer normalizes formatting and numeric spelling.
A bare list, new entries, explicitly verbatim surrounding text and unsupported
syntax use focused text or Python edits.
In `surfaces (data { point (...); ... });`, `surfaces` is a list: edit that list's
value or its selected text; `surfaces/data/point` and `surfaces/0/point` are not
dictionary paths. A headerless keyed fragment still uses the native helper.
