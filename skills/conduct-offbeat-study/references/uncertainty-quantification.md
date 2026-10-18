# Uncertainty quantification

Use this card only when inputs are defined as random variables or samples. A
range-only grid is sensitivity exploration, not probabilistic UQ.

## Define and generate the sample

The sampling design consists of distributions and supports, dependencies,
sample count, algorithm, seed and draw order. For a named sampler, prefer its
maintained library implementation and resolve the dependency before solving.
Record the library version and RNG/scramble settings with the seed; these can
change the design. The materialized numeric table is the input to execution
and recovery, so sampler setup finishes before the first evaluation.

Follow an explicitly requested generator exactly. For a small independent
Monte Carlo design using Python's standard library, create one
`random.Random(seed)` instance, draw variables in the stated row and variable
order, and write the resulting numeric table before any solve. Recovery reads
that table. Named distribution parameters map to the generator's keywords;
their order in prose can differ from its positional argument order.

## Match the design to the estimator

Use ordinary Monte Carlo for empirical distribution summaries. For Latin
hypercube, quasi-random, stratified, or dependent-input sampling, record the
exact construction, ordering, balance requirements, dependence model, and seed
or scramble state. Marginal distributions plus pairwise correlations do not by
themselves define a joint distribution.

A variance-based sensitivity index requires its named structured design and
estimator. Materialize every base and coupled row before solving, and record
both the base sample size and total solver-start requirement. Do not derive
such indices from an unrelated Monte Carlo or Latin-hypercube table. Compute an
index only from the complete blocks required by its estimator; keep failed or
missing block members explicit and never impute them.

When repeated seeds represent stochastic solver response at the same physical
inputs, record the replicate seeds and aggregation rule before execution.
Intentional replicates are distinct evaluations and starts, not duplicate
points to cache.

## Summarize observed uncertainty

Compute statistics from valid completed samples and report that denominator
alongside failed, missing and unfinished counts.

For a small sample, report empirical range, mean, sample standard deviation
with its convention, median or quantiles only when requested, and the exact
sample size. Rank correlations are descriptive input-response associations;
they are not causal sensitivity indices. Preserve tied ranks correctly.

Do not claim population coverage, tail probabilities, convergence, or stable
Sobol indices from a small illustrative design. Confidence intervals,
probability estimates, variance decomposition, and convergence diagnostics
require a design and sample size that actually support them. State conclusions
as applying to the recorded draws and model.
