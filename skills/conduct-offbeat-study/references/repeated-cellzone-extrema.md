# Repeated internal cellZone extrema

For ordinary scalar extrema, reuse Extract's established `result_api.extreme`
call. `scripts/cellzone_extremum.py` provides a detailed Decimal reduction over
one internal `cellZone`. It supports `min`, `max` and
`max_abs` and calls the Extract Skill's public `select_cell_field_at_time` and
`reduce_cell_selection` functions.

One call reduces a field at one modeled time. Time-window peaks and other history
reductions use the result extraction series APIs.

The helper supports scalar `value` and the engineering `hoop` component of
OFFBEAT `sigmaCyl`. It accepts `latest` or one exact modeled time, never falls
back to an earlier field, returns every exact tie, and reports `unit_unverified`
rather than guessing a unit. For `max_abs`, JSON `comparison` is the nonnegative
magnitude for an absolute-stress objective or limit. JSON `value` and
`ties[*].value` retain signed extrema for requested tension/compression details;
these signed values are not the absolute response. The scalar API above already
returns the magnitude.

For an exact-final response, reuse Execute's completion state and the established
configured `endTime` as `--time`; do not use `latest` as a substitute. Use
`latest` only when the engineering request explicitly selects the globally
latest available result.

When this detailed response is requested, place the call in the Python extraction
callback. The controller applies it to the completed result roots; an already
retained response is reused. The single-case command syntax is:

```bash
python -B "$PLUGIN_ROOT/skills/conduct-offbeat-study/scripts/cellzone_extremum.py" \
  --plugin-root "$PLUGIN_ROOT" \
  --result-root point-001 \
  --field T \
  --zone fuel \
  --component value \
  --operation max \
  --time "$CONFIGURED_END_TIME"
```

Here `CONFIGURED_END_TIME` is the value from that point's `system/controlDict`.

For cladding hoop stress, pass `--field sigmaCyl --zone cladding`, together with
`--component hoop --operation max_abs`. A successful call emits one concise
JSON record with `status`, values, comparison magnitude, unit, modeled time,
all tied cells, and paths relative to the result or plugin root. Any selection
or reduction exception emits `status: extraction_failed`, preserves its
`error_type`, and exits nonzero. This is an extraction status, separate from the
solver's terminal status.
