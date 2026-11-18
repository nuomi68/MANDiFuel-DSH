"""Read-only, deterministic evidence from saved OFFBEAT inputs and fields.

No agents, frontend, network, solver execution, or modification of case files.
"""
VERSION = '1.0'


def engine_revision():
    import hashlib
    from pathlib import Path
    folder=Path(__file__).resolve().parent;root=folder.parents[1]
    paths=sorted(folder.glob('*.py'))+[root/'skills/extract-offbeat-results/scripts'/name for name in ['result_api.py','openfoam_parser.py']]
    return hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()[:20]


def verify_case(case, *, workspace=None, time='latest', checks=None):
    from .checks import verify_case as run
    return run(case, workspace=workspace, time=time, checks=checks)
