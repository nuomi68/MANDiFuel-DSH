"""Public Study continuation interface; implementation is bundled at the plugin root."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'lib'))
from mandifuel_run.study import Study  # noqa: E402, F401
from mandifuel_run.optimization import run_optuna  # noqa: E402, F401
