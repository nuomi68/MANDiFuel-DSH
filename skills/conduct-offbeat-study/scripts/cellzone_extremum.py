#!/usr/bin/env python3
"""Extract one exact-time internal cellZone extremum through the bundled API."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any


PARSER_RELATIVE_PATH = Path(
    "skills/extract-offbeat-results/scripts/openfoam_parser.py"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a value or sigmaCyl hoop extremum from one internal cellZone."
        )
    )
    parser.add_argument("--plugin-root", required=True, type=Path)
    parser.add_argument("--result-root", required=True, type=Path)
    parser.add_argument("--field", required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--component", required=True, choices=("value", "hoop"))
    parser.add_argument("--operation", required=True, choices=("min", "max", "max_abs"))
    parser.add_argument("--time", required=True, help="Exact modeled time or 'latest'.")
    return parser.parse_args()


def load_parser(plugin_root: Path) -> Any:
    expected = (plugin_root.resolve() / PARSER_RELATIVE_PATH).resolve()
    if not expected.is_file():
        raise FileNotFoundError(f"bundled parser not found: {PARSER_RELATIVE_PATH}")

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(expected.parent))
    api = importlib.import_module("openfoam_parser")
    actual = Path(api.__file__).resolve()
    if actual != expected:
        raise RuntimeError(
            f"unexpected parser dependency: {actual}; expected {PARSER_RELATIVE_PATH}"
        )
    return api


def extract(args: argparse.Namespace) -> dict[str, object]:
    api = load_parser(args.plugin_root)
    if args.component == "hoop":
        if args.field != "sigmaCyl":
            raise ValueError("engineering component 'hoop' is supported only for sigmaCyl")
        parser_component = api.cylindrical_symm_tensor_normal_component("hoop")
    else:
        parser_component = "value"

    time_selector = {"latest": True} if args.time == "latest" else {"exact": args.time}
    selected = api.select_cell_field_at_time(
        args.result_root,
        field_selector=args.field,
        zone_name=args.zone,
        component=parser_component,
        **time_selector,
    )
    reduced = api.reduce_cell_selection(selected, operation=args.operation)
    unit = api.canonical_si_unit_for_dimensions(selected.dimensions)
    mesh = selected.context.mesh

    ties = [
        {
            "cell_label": item.cell_label,
            "value": str(item.value),
            "centre": [str(coordinate) for coordinate in item.centre],
        }
        for item in reduced.extrema
    ]
    return {
        "status": "ok",
        "result_root": args.result_root.as_posix(),
        "value": [item["value"] for item in ties],
        "comparison": str(reduced.comparison_value),
        "unit": unit if unit is not None else "unit_unverified",
        "time": str(mesh.modeled_time),
        "time_directory": mesh.time_directory,
        "field": selected.object_name,
        "field_class": selected.class_name,
        "field_kind": selected.field_kind,
        "storage": selected.storage,
        "dimensions": [str(value) for value in selected.dimensions],
        "zone": selected.context.zone_name,
        "component": args.component,
        "parser_component": selected.component,
        "operation": reduced.operation,
        "selected_cell_count": reduced.selected_cell_count,
        "ties": ties,
        "provenance": {
            "field_source": selected.source_path,
            "cell_zones_source": selected.context.cell_zones_source,
            "mesh_sources": [
                {
                    "primitive": source.name,
                    "relative_path": source.relative_path,
                    "instance": source.instance,
                    "instance_time": (
                        str(source.instance_time)
                        if source.instance_time is not None
                        else None
                    ),
                }
                for source in mesh.primitive_sources
            ],
            "parser": PARSER_RELATIVE_PATH.as_posix(),
        },
    }


def main() -> int:
    args = parse_args()
    try:
        payload = extract(args)
        exit_code = 0
    except Exception as exc:
        payload = {
            "status": "extraction_failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "field": args.field,
            "zone": args.zone,
            "component": args.component,
            "operation": args.operation,
            "requested_time": args.time,
        }
        exit_code = 1

    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
