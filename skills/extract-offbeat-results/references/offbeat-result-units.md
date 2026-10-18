# OFFBEAT result-unit evidence

Use this table only after selecting an exact observed field or a result quantity with an explicit scope when its unit cannot be resolved from the seven-exponent `dimensions` entry. An all-zero or unmapped dimension vector provides no unit evidence; it does not establish that the quantity is dimensionless.

Match field names case-sensitively. Do not extend a row to aliases or to other quantities with similar physical meaning. The gap-gas row applies only to a parsed `gasPressure` entry or to a parsed pressure entry whose containing result object is explicitly identified as gap-gas state; it does not apply to a general pressure field.

| Observed field or explicitly scoped quantity | Unit | Official OFFBEAT source, relative to the source tree |
|---|---|---|
| `Bu` | `MWd/MT_oxide` | `mkdocs/docs/user_guide/solverDict/burnup.md:4`; `offbeatLib/burnup/burnupLassmann.H:65-67` |
| `gapWidth` | `m` | `mkdocs/docs/user_guide/data_processing/index.md:27`; `offbeatLib/physicsSubSolvers/mechanicsSubSolver/mechanicsSubSolver.C:640-655,1475-1485` also explains why the all-zero field dimensions do not establish that this quantity is dimensionless |
| `interfaceP` | `Pa` | `mkdocs/docs/user_guide/data_processing/index.md:27` |
| `sigma` | `Pa` | `mkdocs/docs/user_guide/data_processing/index.md:25` |
| `sigmaEq` | `Pa` | `mkdocs/docs/user_guide/data_processing/index.md:25` |
| `sigmaHyd` | `Pa` | `mkdocs/docs/user_guide/data_processing/index.md:25` |
| `sigmaY` | `Pa` | `mkdocs/docs/user_guide/data_processing/index.md:25` |
| Gap-gas `gasPressure` | `Pa` | `offbeatLib/gapGasModel/gapGasModel.H:133-134` |

Do not assign a verified unit to `Bu_kgU` from this snapshot. The declaration in `offbeatLib/burnup/burnupLassmann.H:219-220` states `MWd/kgU`, while `offbeatLib/burnup/burnupLassmann.C:796,806,812` describes `MWd/MTU` and applies only a `0.8815` uranium-fraction conversion. Before comparison on an `MWd/kgHM` axis, the official validation script `Cases/Verification/burnupFBR/plot.py:19-21,57-58,73` divides the stored value by `1000`. Unless additional authoritative evidence for the exact result-producing version resolves this conflict, report `Bu_kgU` as `unit_unverified`.
