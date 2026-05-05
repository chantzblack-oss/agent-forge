from __future__ import annotations

import copy
import sys
import types
from unittest.mock import patch


def _install_rich_stub() -> None:
    if "rich" in sys.modules:
        return
    rich_mod = types.ModuleType("rich")
    console_mod = types.ModuleType("rich.console")
    panel_mod = types.ModuleType("rich.panel")
    prompt_mod = types.ModuleType("rich.prompt")
    table_mod = types.ModuleType("rich.table")
    text_mod = types.ModuleType("rich.text")
    box_mod = types.ModuleType("rich.box")

    class Console:
        def __init__(self, *args, **kwargs):
            pass

        def print(self, *args, **kwargs):
            pass

        def rule(self, *args, **kwargs):
            pass

    class Panel:
        def __init__(self, *args, **kwargs):
            pass

    class Prompt:
        @staticmethod
        def ask(*args, **kwargs):
            return "done"

    class IntPrompt:
        @staticmethod
        def ask(*args, **kwargs):
            return 1

    class Table:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *args, **kwargs):
            pass

    class Text:
        def __init__(self, *args, **kwargs):
            pass

        def append(self, *args, **kwargs):
            pass

    console_mod.Console = Console
    console_mod.Group = list
    panel_mod.Panel = Panel
    prompt_mod.Prompt = Prompt
    prompt_mod.IntPrompt = IntPrompt
    table_mod.Table = Table
    text_mod.Text = Text
    box_mod.ROUNDED = None
    box_mod.SIMPLE = None

    rich_mod.box = box_mod
    sys.modules["rich"] = rich_mod
    sys.modules["rich.console"] = console_mod
    sys.modules["rich.panel"] = panel_mod
    sys.modules["rich.prompt"] = prompt_mod
    sys.modules["rich.table"] = table_mod
    sys.modules["rich.text"] = text_mod
    sys.modules["rich.box"] = box_mod


_install_rich_stub()

from agent_forge.engine import Orchestrator
from agent_forge.teams.core import RESEARCH_LAB


def test_multi_agent_team_run_complex_prompt() -> None:
    team = copy.deepcopy(RESEARCH_LAB)
    team.max_rounds = 1

    def fake_call(self, system: str, user_prompt: str) -> str:
        if self.role == "leader":
            if "FINAL ROUND" in user_prompt or "FINAL DELIVERABLE" in user_prompt:
                return "## Synthesis\nGrid transition can work with phased storage buildout and market reform. [COMPLETE]"
            return "## Plan\n@Analyst quantify costs. @Contrarian risks. @Synthesizer integrate. @Reviewer audit. [DONE]"
        return "## Findings\n- Simulated evidence and tradeoffs. [DONE]"

    with patch("agent_forge.agent._CLAUDE_PATH", "/usr/bin/claude"), patch(
        "agent_forge.agent.Agent._call_cli", new=fake_call
    ):
        orch = Orchestrator(narrate_mode="off")
        orch.run(
            "Should the US transition its entire electric grid to 100% renewables by 2035 while maintaining affordability and reliability?",
            team,
        )

    assert len(orch._transcript) >= 2
    joined = "\n".join(x["content"] for x in orch._transcript)
    assert "[COMPLETE]" in joined
