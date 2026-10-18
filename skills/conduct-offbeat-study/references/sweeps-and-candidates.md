# Sweeps and finite candidates

Use this card when all evaluations can be named before solving.

## Explicit sweeps

Materialize the complete table in stable point order. For a Cartesian design,
include every requested combination exactly once. For a discretization study,
change only numerical controls and keep physical inputs fixed; describe the
result as numerical behavior, not physical validation.

If the request asks for an effects model or reduced screening design, construct
the coded design matrix before execution. Check the requested rank or
estimability condition and record the selected rows and selection rule. Fit the
model only when the valid completed rows still satisfy that condition.

For paired, trajectory, or elementary-effect screening, record the coded scale,
step rule, pair or trajectory construction, factor order, and estimator before
execution. Compute an effect only from its complete required pair or trajectory;
a missing member invalidates that contrast and is never imputed. Report this as
screening evidence, not a variance contribution or causal effect.

## Finite-candidate selection

Candidate selection uses a finite point set, feasibility rules, objective
direction, shared operating scenarios and a tie rule. Input-only constraints
apply to proposed values; solver-dependent constraints use extracted responses.

Rank valid feasible candidates after all authorized evaluations finish. Keep
failed, invalid, and tied candidates visible. Report the winner as the best
observed feasible candidate in the evaluated set, not as a continuous or global
optimum. When candidates share scenarios, use the same scenario set and the
pre-recorded aggregation rule for every candidate.
