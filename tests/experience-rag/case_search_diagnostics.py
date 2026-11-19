#!/usr/bin/env python3
"""Inspect old case-RAG top results for several equivalent spherical-shell queries."""
import json
from pathlib import Path
import subprocess
import sys

CASE = Path(__file__).resolve().parents[2] / "rag" / "query.py"
QUERIES = (
    "spherical shell pressure Cartesian stress tensor radial stress symmetry",
    "hollow spherical shell pressure",
    "spherical shell internal pressure stress small strain",
    "球壳 内外压力 球坐标 应力",
)


def main() -> int:
    for query in QUERIES:
        proc = subprocess.run([sys.executable, "-B", str(CASE), "--query", query,
                               "--limit", "5", "--compact"], capture_output=True,
                              text=True, encoding="utf-8", check=True)
        payload = json.loads(proc.stdout)
        rows = payload.get("candidates", [])
        summaries = []
        for row in rows:
            if isinstance(row, dict):
                summaries.append({key: value for key, value in row.items()
                                  if key in {"card_name", "card_path", "rank", "score"}})
        print(json.dumps({"query": query, "status": payload.get("status"),
                          "top_level_keys": list(payload), "result_count": len(rows),
                          "result_keys": sorted(rows[0]) if rows and isinstance(rows[0], dict) else [],
                          "results": summaries}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
