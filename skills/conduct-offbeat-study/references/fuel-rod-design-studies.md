# Fuel-rod design studies

This card covers fuel-rod design, fabrication, operating histories and uncertain
physical inputs, together with their fuel-performance responses.

## Define the physical contract

Classify each varied quantity as a design or fabrication input, operating
history, uncertainty, or numerical control. Separate independent quantities
from derived solver inputs, and do not interpret a numerical-control effect as
a physical design effect.

When a study spans fabrication, base irradiation or conditioning, a transient,
and cooldown, record that phase chain. A later phase inherits the valid state of
the same point; it does not restart from the common baseline or another point.

Geometry changes can couple radii, gaps, thicknesses, volumes and mesh boundaries.
Nominal design volumes use the prepared geometric dimensions; integrating a
discretized or deformed mesh answers a different volume question.
Fixed gas inventory couples pressure, temperature, composition and free volume.
For power histories, support, normalization, interpolation and knot alignment
define the physical load. Equal terminal value, equal peak and equal time
integral are distinct history constraints. The requested fixed quantities and
active model determine which relationships apply.

## Define a fuel-performance response

Select the requested fuel-performance quantities, adding event time or location
when these are part of the response. Corrosion,
hydrogen and damage responses require the corresponding models to be active.

An event response fixes its phase, region, time window, reduction, and
co-located event time and position. An event not observed in that window is a
distinct outcome, not a solver failure or a zero-valued event.

Do not substitute final time for a history extremum. Keep peak and final values
separate when they answer different questions, and preserve stress or strain
sign unless an absolute functional is requested. An observed regime change, such
as open gap to contact, can change the interpretation of an effect. Use
solver semantics or a supplied threshold, not an invented tolerance. Compute a
margin or declare feasibility only against a supplied or task-authoritative
limit.

The same time-support rule applies to constraints: a requested final-state limit
is evaluated at that state. Replacing it with a history-wide limit changes the
feasible set and is a different study, not an extra validation of this one.

## Apply the selected method in the domain

For screening, preserve the coupled basis in each contrast, report physical
units, and identify regime changes rather than hiding them in one slope.

For UQ, distinguish fabrication, operating, and material or model uncertainty.
Sample independent quantities and derive coupled geometry or state. Treat model
choices as scenarios, report valid and failed counts by relevant regime, and
limit a small design's claims to its draws.

For design or optimization, keep design and operating-scenario identities
separate and evaluate designs on the same prescribed scenarios. Record the
feasibility and aggregation rule, retain the controlling scenario, and keep
objectives separate unless the user supplies a scalarization. Report the best
observed feasible design under the evaluated histories and model.
