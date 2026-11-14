#!/usr/bin/env python3
"""Independently verify the paired fuel-rod benchmark using only Python's stdlib.

No MANDiFuel parser/helper is imported and no case is modified or executed.
The sole output is RUN_ROOT/verification.json (or --output).
"""
import argparse
import ast
from bisect import bisect_right
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

POWERS = (10000, 20000, 30000)
FIELDS = ("fuel_T_max_K", "cladding_T_max_K")
DEFAULT_SOURCE = Path("/home/lwz/offbeat/Cases/testCases/exerciseOFFBEAT/case1_solved")


def tokens(text):
    """Tokenize the ASCII subset used by this official case, preserving strings."""
    pattern = r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*|[{}();\[\]]|[^\s{}();\[\]"]+'
    return [x for x in re.findall(pattern, text, re.S)
            if not x.startswith(("//", "/*"))]


def dictionary(items, start=0, end=None):
    """Read nested OpenFOAM dictionaries; scalar/list values remain token lists."""
    end = len(items) if end is None else end
    result = {}
    i = start
    while i < end:
        if items[i] in (";", "}"):
            i += 1
            continue
        key = items[i].strip('"')
        i += 1
        if i < end and items[i] == "{":
            close = matching(items, i, "{", "}")
            result[key] = dictionary(items, i + 1, close)
            i = close + 1
        else:
            value = []
            depth = 0
            while i < end:
                word = items[i]
                if word == ";" and depth == 0:
                    i += 1
                    break
                if word in ("(", "[", "{"):
                    depth += 1
                elif word in (")", "]", "}"):
                    depth -= 1
                value.append(word)
                i += 1
            result[key] = value
    return result


def matching(items, start, opening, closing):
    depth = 0
    for i in range(start, len(items)):
        if items[i] == opening:
            depth += 1
        elif items[i] == closing:
            depth -= 1
            if depth == 0:
                return i
    raise ValueError(f"Unclosed {opening!r} at token {start}")


def read_foam(path):
    result = dictionary(tokens(path.read_text()))
    header = result.get("FoamFile", {})
    if header.get("format", ["ascii"]) != ["ascii"]:
        raise ValueError(f"Only ASCII input is supported: {path}")
    return result


def number(value):
    n = float(value)
    if not math.isfinite(n):
        raise ValueError(f"Nonfinite number: {value}")
    return n


def scalar(value):
    if len(value) != 1:
        raise ValueError(f"Expected scalar, got {value!r}")
    return number(value[0])


def sequence(value):
    if not value or value[0] != "(" or value[-1] != ")":
        raise ValueError(f"Expected parenthesized sequence, got {value!r}")
    return [number(x) for x in value[1:-1]]


def constant_power_on_interval(times, powers, q, start=0, end=1):
    """Check the piecewise-linear history on the modeled interval only.

    OFFBEAT may require a later marker for its next-point lookup even when the
    physical stop time is 1 s. Extra markers are valid if [0, 1] stays constant.
    """
    if len(times) != len(powers) or len(times) < 2:
        return False, {"reason": "time/power lengths differ or have fewer than two markers"}
    if not all(a < b for a, b in zip(times, times[1:])):
        return False, {"reason": "time markers must be strictly increasing"}
    if times[0] > start or times[-1] < end:
        return False, {"reason": "history does not cover the complete modeled interval"}
    samples = sorted({start, end, *(t for t in times if start < t < end)})
    values = []
    for t in samples:
        left = min(max(bisect_right(times, t) - 1, 0), len(times) - 2)
        fraction = (t - times[left]) / (times[left + 1] - times[left])
        values.append(powers[left] + fraction * (powers[left + 1] - powers[left]))
    valid = all(math.isclose(v, q, rel_tol=1e-12, abs_tol=1e-9) for v in values)
    return valid, {"checked_times_seconds": samples, "interpolated_powers_W_per_m": values}


def equivalent(a, b):
    """Allow formatting changes and equivalent numeric spellings only."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))
    try:
        return math.isclose(number(a), number(b), rel_tol=1e-12, abs_tol=1e-14)
    except (ValueError, TypeError):
        return a == b


def cell_zones(path):
    items = tokens(path.read_text())
    if items[:2] != ["FoamFile", "{"]:
        raise ValueError("cellZones has no FoamFile header")
    header_end = matching(items, 1, "{", "}")
    header = dictionary(items, 2, header_end)
    if header.get("format", ["ascii"]) != ["ascii"]:
        raise ValueError("Binary cellZones is unsupported")
    i = header_end + 1
    count = int(items[i])
    i += 1
    if items[i] != "(":
        raise ValueError("cellZones list opener missing")
    i += 1
    zones = {}
    for _ in range(count):
        name = items[i].strip('"')
        i += 1
        if items[i] != "{":
            raise ValueError(f"cellZone {name} has no dictionary")
        end = matching(items, i, "{", "}")
        data = dictionary(items, i + 1, end)
        labels = data["cellLabels"]
        start = labels.index("(")
        expected = int(labels[start - 1])
        values = [int(x) for x in labels[start + 1:-1]]
        if len(values) != expected or len(set(values)) != expected:
            raise ValueError(f"cellZone {name} has invalid label count/duplicates")
        zones[name] = values
        i = end + 1
    return zones


def internal_temperatures(path, expected_cells):
    data = read_foam(path)
    if data.get("dimensions") != ["[", "0", "0", "0", "1", "0", "0", "0", "]"]:
        raise ValueError("T dimensions do not identify temperature in K")
    field = data["internalField"]
    if field[0] == "uniform":
        values = [number(field[1])] * expected_cells
    elif field[:2] == ["nonuniform", "List<scalar>"]:
        count = int(field[2])
        values = sequence(field[3:])
        if count != len(values):
            raise ValueError("T/internalField declared length does not match data")
    else:
        raise ValueError(f"Unsupported T/internalField representation: {field[:3]}")
    if len(values) != expected_cells:
        raise ValueError(f"Expected {expected_cells} cells, found {len(values)}")
    return values, data


def rounding_tolerance(value, significant_digits):
    """One full least-significant written unit; source writePrecision defaults to 6."""
    if value == 0:
        return 10.0 ** (1 - significant_digits)
    return 10.0 ** (math.floor(math.log10(abs(value))) - significant_digits + 1)


def fatal_solver_log(text):
    # OpenFOAM normally prints "Floating point exception trapping enabled".
    # Match actual diagnostics/shell termination lines, never that banner.
    pattern = (r"FOAM FATAL|"
               r"^\s*(?:Segmentation fault|Floating point exception)(?! trapping enabled)(?:\s|\(|$)|"
               r"^\s*[^:\n]+:\s*line\s+\d+:\s*\d+\s+(?:Segmentation fault|Floating point exception)")
    return bool(re.search(pattern, text, re.I | re.M))


def add(checks, name, passed, **evidence):
    checks.append({"check": name, "passed": bool(passed), **evidence})


def case_path(row, workspace):
    path = Path(row["result_root"])
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError(f"Result path is outside its own workspace: {path}")
    return path


def check_case(row, workspace, source):
    checks = []
    q = number(row["q_W_per_m"])
    root = case_path(row, workspace)
    detail = {"q_W_per_m": q, "result_root": str(root), "checks": checks,
              "field_values_available": False, "normal_completion": False}

    def inspect(stage, callback):
        # An absent metadata file must not discard independently readable fields.
        try:
            return callback()
        except (OSError, ValueError, KeyError, TypeError, IndexError, SyntaxError, AttributeError) as exc:
            add(checks, stage, False, error=str(exc))
            return None

    def log_evidence():
        log = (root / "log.offbeat").read_text(errors="replace")
        ends = len(re.findall(r"^\s*End\s*$", log, re.M | re.I))
        fatal = fatal_solver_log(log)
        add(checks, "solver_normal_end", ends == 1 and not fatal, end_markers=ends, fatal_marker=fatal)
        logged_times = [number(x) for x in re.findall(r"^Time\s*=\s*([+\-0-9.eE]+)", log, re.M)]
        add(checks, "solver_terminal_time", bool(logged_times) and logged_times[-1] == 1, logged_times=logged_times)
        detail["normal_completion"] = ends == 1 and not fatal and bool(logged_times) and logged_times[-1] == 1

    inspect("solver_log_readable", log_evidence)
    control = inspect("control_dictionary_readable", lambda: read_foam(root / "system/controlDict")) or {}

    def field_evidence():
        zones = cell_zones(root / "constant/polyMesh/cellZones")
        labels = zones["fuel"] + zones["cladding"]
        add(checks, "material_cell_counts", len(zones["fuel"]) == 30 and len(zones["cladding"]) == 10,
            fuel=len(zones["fuel"]), cladding=len(zones["cladding"]))
        add(checks, "material_partition", sorted(labels) == list(range(40)))
        temperatures, terminal = internal_temperatures(root / "1/T", 40)
        actual = {"fuel_T_max_K": max(temperatures[i] for i in zones["fuel"]),
                  "cladding_T_max_K": max(temperatures[i] for i in zones["cladding"])}
        precision = int(scalar(control.get("writePrecision", ["6"])))
        if precision < 4 or precision > 17:
            raise ValueError(f"Unexpected writePrecision={precision}; review tolerance manually")
        tolerance = {key: rounding_tolerance(value, precision) for key, value in actual.items()}
        detail.update(independent_response=actual, write_precision=precision,
                      rounding_tolerance_K=tolerance, field_values_available=True)
        for key in FIELDS:
            try:
                reported = number(row[key])
                add(checks, "json_" + key, abs(reported - actual[key]) <= tolerance[key],
                    reported=reported, independent=actual[key], tolerance_K=tolerance[key])
            except (KeyError, TypeError, ValueError) as exc:
                add(checks, "json_" + key, False, reported=row.get(key), independent=actual[key], error=str(exc))
        outer = terminal["boundaryField"]["cladOuter"]["value"]
        if outer[0] == "uniform":
            outer_values = [number(outer[1])]
        elif outer[:2] == ["nonuniform", "List<scalar>"]:
            outer_values = sequence(outer[3:])
        else:
            raise ValueError("Cannot read terminal cladOuter values")
        add(checks, "terminal_outer_wall_573K", all(abs(x - 573) <= 1e-6 for x in outer_values), actual=outer_values)
        add(checks, "temperature_order", actual["fuel_T_max_K"] > actual["cladding_T_max_K"] > 573)

    inspect("terminal_field_readable", field_evidence)
    for name, expected in (("startTime", 0), ("endTime", 1), ("deltaT", 1)):
        value = inspect(name + "_readable", lambda name=name: scalar(control[name]))
        add(checks, name, value == expected, actual=value, expected=expected)
    add(checks, "start_from_zero", control.get("startFrom") == ["startTime"], actual=control.get("startFrom"))
    add(checks, "stop_at_end", control.get("stopAt") == ["endTime"], actual=control.get("stopAt"))
    unit = inspect("time_unit_readable", lambda: control.get("userTime", {}).get("type", ["seconds"]))
    add(checks, "seconds_time_unit", unit == ["seconds"], actual=unit)
    adjustable = control.get("adjustableTimeStep")
    add(checks, "fixed_time_step", adjustable in (["false"], ["off"], ["no"], ["0"]), actual=adjustable)
    final_time = inspect("reported_final_time_readable", lambda: number(row["final_time"]))
    add(checks, "reported_final_time_seconds", final_time == 1, actual=row.get("final_time"))

    def physics_evidence():
        solver = read_foam(root / "constant/solverDict")
        schemes = read_foam(root / "system/fvSchemes")
        source_solver = read_foam(source / "constant/solverDict")
        add(checks, "steady_state_temperature", schemes.get("ddtSchemes", {}).get("default") == ["steadyState"],
            actual=schemes.get("ddtSchemes", {}).get("default"))
        heat = solver["heatSourceOptions"]
        times, powers = sequence(heat["timePoints"]), sequence(heat["lhgr"])
        constant, history_evidence = constant_power_on_interval(times, powers, q)
        interpolation = heat.get("timeInterpolationMethod", ["linear"])
        add(checks, "power_history", constant and interpolation == ["linear"],
            timePoints=times, lhgr=powers, interpolation=interpolation, **history_evidence)
        for name in ("axialProfile", "radialProfile"):
            add(checks, name + "_flat", heat.get(name, {}).get("type") == ["flat"])
        for name in ("thermalSolver", "mechanicsSolver", "materialProperties", "heatSource", "burnup", "gapGas", "fgr", "materials"):
            add(checks, "source_" + name, equivalent(solver.get(name), source_solver.get(name)))

    inspect("physics_input_readable", physics_evidence)

    def mesh_evidence():
        mesh = read_foam(root / "system/blockMeshDict")
        source_mesh = read_foam(source / "system/blockMeshDict")
        for key in ("convertToMeters", "vertices", "blocks", "edges", "boundary"):
            add(checks, "source_mesh_" + key, equivalent(mesh.get(key), source_mesh.get(key)))

    inspect("mesh_definition_readable", mesh_evidence)
    if (root / "rodDict").exists():
        def generator_evidence():
            rod = ast.literal_eval((root / "rodDict").read_text())
            source_rod = ast.literal_eval((source / "rodDict").read_text())
            add(checks, "source_rod_geometry", rod == source_rod)
        inspect("optional_generator_readable", generator_evidence)
    else:
        detail["geometry_definition"] = "Direct blockMeshDict; rodDict is optional and absent"

    def boundary_evidence():
        initial = read_foam(root / "0/T")["boundaryField"]
        source_initial = read_foam(source / "0/T")["boundaryField"]
        for key in ("fuelOuter", "cladInner", "cladOuter"):
            add(checks, "source_boundary_" + key, equivalent(initial.get(key), source_initial.get(key)))

    inspect("initial_boundary_readable", boundary_evidence)
    detail["passed"] = all(x["passed"] for x in checks)
    return detail


def read_rows(path):
    if path.suffix == ".json":
        rows = json.loads(path.read_text())
    else:
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
    if not isinstance(rows, list):
        raise ValueError(f"Expected a JSON array: {path}")
    indexed, errors = {}, []
    for index, row in enumerate(rows):
        try:
            q = number(row["q_W_per_m"])
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"row_index": index, "error": str(exc)})
            continue
        if q in indexed:
            errors.append({"row_index": index, "error": f"Duplicate power: {q}"})
            continue
        indexed[q] = row
    if set(indexed) != set(POWERS):
        errors.append({"error": f"Expected exactly powers {POWERS}, got {list(indexed)}"})
    return indexed, errors


def invocation_root(start):
    root = Path(start["cwd"])
    argv = start.get("argv", [])
    if "-case" in argv:
        value = Path(argv[argv.index("-case") + 1])
        root = value if value.is_absolute() else root / value
    return root.resolve()


def check_arm(root, arm, source):
    workspace = root / arm / "workspace"
    checks = []
    result = {"workspace": str(workspace), "checks": checks, "cases": []}
    try:
        run = json.loads((root / arm / "run.json").read_text())
        add(checks, "dsh_completed", run.get("exit_code") == 0 and not run.get("timed_out"),
            exit_code=run.get("exit_code"), timed_out=run.get("timed_out"))
    except (OSError, ValueError) as exc:
        add(checks, "dsh_completed", False, error=str(exc))
    for filename in ("results.json", "results.csv", "temperature_vs_power.svg", "report.md"):
        path = workspace / filename
        add(checks, "artifact_" + filename, path.is_file() and path.stat().st_size > 0)
    try:
        svg = ET.parse(workspace / "temperature_vs_power.svg").getroot()
        add(checks, "svg_well_formed", svg.tag.split("}")[-1] == "svg")
    except (OSError, ET.ParseError) as exc:
        add(checks, "svg_well_formed", False, error=str(exc))
    scripts = [str(p.relative_to(workspace)) for p in workspace.glob("**/*")
               if p.is_file() and p.suffix in (".py", ".sh")
               and len(p.relative_to(workspace).parts) <= 2]
    add(checks, "local_replay_script_present", bool(scripts), files=scripts)
    try:
        rows, errors = read_rows(workspace / "results.json")
        add(checks, "json_three_requested_points", not errors, errors=errors)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        rows = {}
        add(checks, "json_three_requested_points", False, error=str(exc))
    try:
        csv_rows, errors = read_rows(workspace / "results.csv")
        add(checks, "csv_three_requested_points", not errors, errors=errors)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        csv_rows = {}
        add(checks, "csv_three_requested_points", False, error=str(exc))
    for q, row in sorted(rows.items()):
        try:
            case = check_case(row, workspace, source)
        except (OSError, ValueError, KeyError, TypeError, IndexError, SyntaxError) as exc:
            case = {"q_W_per_m": q, "passed": False, "error": str(exc), "checks": [],
                    "field_values_available": False, "normal_completion": False}
        result["cases"].append(case)
        if q in csv_rows and "independent_response" in case:
            other = csv_rows[q]
            for key in FIELDS:
                try:
                    add(checks, f"csv_{q:g}_{key}",
                        abs(number(other[key]) - case["independent_response"][key]) <= case["rounding_tolerance_K"][key])
                except (KeyError, TypeError, ValueError) as exc:
                    add(checks, f"csv_{q:g}_{key}", False, error=str(exc))
            try:
                add(checks, f"csv_{q:g}_root_and_time", case_path(other, workspace) == case_path(row, workspace)
                    and number(other["final_time"]) == 1)
            except (KeyError, TypeError, ValueError) as exc:
                add(checks, f"csv_{q:g}_root_and_time", False, error=str(exc))
    try:
        starts = [json.loads(line) for line in (workspace / "solver-starts.jsonl").read_text().splitlines() if line.strip()]
        add(checks, "exactly_three_recorded_solver_starts", len(starts) == 3, count=len(starts))
        add(checks, "solver_start_budget_respected", len(starts) <= 3, used=len(starts), budget=3)
        result["recorded_solver_starts"] = starts
        result["solver_start_count"] = len(starts)
        result["solver_start_budget_respected"] = len(starts) <= 3
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        starts = []
        result["solver_start_count"] = None
        result["solver_start_budget_respected"] = False
        add(checks, "exactly_three_recorded_solver_starts", False, error=str(exc))
        add(checks, "solver_start_budget_respected", False, error=str(exc), budget=3)
    try:
        expected_roots = [case_path(row, workspace) for row in rows.values()]
        actual_roots = [invocation_root(start) for start in starts]
        add(checks, "one_start_per_reported_case", len(set(expected_roots)) == 3
            and sorted(str(p) for p in actual_roots) == sorted(str(p) for p in expected_roots))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        add(checks, "one_start_per_reported_case", False, error=str(exc))
    cases = sorted((c for c in result["cases"] if "independent_response" in c), key=lambda c: c["q_W_per_m"])
    if len(cases) == 3:
        for key in FIELDS:
            values = [c["independent_response"][key] for c in cases]
            tolerances = [c["rounding_tolerance_K"][key] for c in cases]
            curvature = values[2] - 2 * values[1] + values[0]
            allowed = tolerances[0] + 2 * tolerances[1] + tolerances[2]
            add(checks, key + "_monotonic", values[0] < values[1] < values[2], actual=values)
            add(checks, key + "_linear_increments", abs(curvature) <= allowed,
                second_difference_K=curvature, tolerance_K=allowed)
    result["field_values_available_count"] = sum(c["field_values_available"] for c in result["cases"])
    result["normally_completed_count"] = sum(c["normal_completion"] for c in result["cases"])
    result["passed"] = all(c["passed"] for c in checks) and len(result["cases"]) == 3 and all(c["passed"] for c in result["cases"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--source-case", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.run_root.resolve()
    result = {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "run_root": str(root),
              "source_case": str(args.source_case.resolve()), "verifier": "independent Python standard library",
              "scope": "input retention, ASCII field/zone responses, terminal evidence, artifacts, instrumented solver counts, paired agreement",
              "limitations": ["Solver starts are counts observed by the PATH wrapper; absolute-path bypasses require trace review.",
                              "Artifact existence/XML validity does not establish report/plot semantic quality or replayability.",
                              "Start-only instrumentation does not independently prove serial solver execution.",
                              "This is one paired task; no statistical performance claim is established."]}
    result["arms"] = {arm: check_arm(root, arm, args.source_case.resolve()) for arm in ("bare", "skill")}
    comparison = []
    indexed = {arm: {c["q_W_per_m"]: c for c in data["cases"] if "independent_response" in c}
               for arm, data in result["arms"].items()}
    for q in POWERS:
        if q not in indexed["bare"] or q not in indexed["skill"]:
            add(comparison, f"paired_{q}_available", False)
            continue
        a, b = indexed["bare"][q], indexed["skill"][q]
        for key in FIELDS:
            delta = b["independent_response"][key] - a["independent_response"][key]
            tolerance = a["rounding_tolerance_K"][key] + b["rounding_tolerance_K"][key]
            add(comparison, f"paired_{q}_{key}", abs(delta) <= tolerance,
                skill_minus_bare_K=delta, tolerance_K=tolerance)
    result["paired_comparison"] = comparison
    result["passed"] = all(arm["passed"] for arm in result["arms"].values()) and all(x["passed"] for x in comparison)
    output = args.output.resolve() if args.output else root / "verification.json"
    if any(output.is_relative_to(root / arm / "workspace") for arm in ("bare", "skill")):
        parser.error("Verification output must be outside both model workspaces")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "output": str(output),
                      "arms": {arm: data["passed"] for arm, data in result["arms"].items()}}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
