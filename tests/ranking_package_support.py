from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def bootstrap_route_tool_package() -> None:
    route_package = sys.modules.setdefault("route", types.ModuleType("route"))
    route_package.__path__ = [str(ROOT / "route")]
    tool_package = sys.modules.setdefault("route.tool", types.ModuleType("route.tool"))
    tool_package.__path__ = [str(ROOT / "route" / "tool")]
