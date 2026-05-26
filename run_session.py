#!/usr/bin/env python3
"""Run a single Tri-Model session non-interactively."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from agent_forge import Orchestrator
from agent_forge.teams.polymath import POLYMATH_TRI

question = (
    "Why do outpatient behavioral health clinics consistently struggle with "
    "clinician retention — even well-funded ones — and what specific operational "
    "changes have the strongest evidence for reducing turnover without sacrificing "
    "patient access or outcomes?"
)

orchestrator = Orchestrator(narrate_mode="off")

# Patch the end-session prompt to auto-export and exit
_original_end = orchestrator._end_session.__func__

def _patched_end(self, goal, team, round_num):
    # Export the session, then exit cleanly
    try:
        path = self._export_session()
        from rich.console import Console
        Console(force_terminal=True).print(f"  [bold green]Exported to {path}[/]")
    except Exception as e:
        print(f"  Export failed: {e}")
    self._print_done()

orchestrator._end_session = _patched_end.__get__(orchestrator)
orchestrator.run(goal=question, team=POLYMATH_TRI)
