"""Re-solve the eight frozen inputs independently, without starting DSH."""
import argparse
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reference import values
from tasks import ROOT, TASKS


def calibrate(task, root):
    task_id = task[0]
    case = root / "calibration" / task_id
    shutil.copytree(root / task_id / "source-case", case)
    command = """
        source "$1"
        source "$MANDIFUEL_OPENFOAM_BASHRC" >/dev/null 2>&1
        export PATH="$MANDIFUEL_OFFBEAT_BIN:$PATH"
        exec bash Allrun
    """
    with (case / "calibration.log").open("wb") as log:
        process = subprocess.run(
            ["bash", "-c", command, "calibration", ROOT / "configs/launcher.env"],
            cwd=case, stdout=log, stderr=subprocess.STDOUT, timeout=360,
        )
    item = {"exit_code": process.returncode}
    if process.returncode == 0:
        item["values"] = list(values(task, case))
    return task_id, item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    (root / "calibration").mkdir(exist_ok=False)
    tasks = [task for task in TASKS if task[3] == "solve"]
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = dict(pool.map(lambda task: calibrate(task, root), tasks))
    (root / "calibration.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
