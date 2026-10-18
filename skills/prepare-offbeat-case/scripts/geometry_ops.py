#!/usr/bin/env python3
"""Public Prepare interface; implementation is bundled at the plugin root."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from mandifuel_prepare import geometry_ops as impl  # noqa: E402

if __name__ == "__main__":
    try:
        raise SystemExit(impl.main())
    except (impl.TransformError, OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
else:
    sys.modules[__name__] = impl
