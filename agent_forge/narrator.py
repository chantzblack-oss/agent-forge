"""Text-to-speech narrator — generates natural spoken summaries of agent output."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
import queue

from rich.console import Console

# Unique voices for each agent — distinct identity in conversation
AGENT_VOICES: dict[str, str] = {
    # ── Core: Storyteller ──
    "Narrator":          "en-US-GuyNeural",
    "Worldbuilder":      "en-GB-RyanNeural",
    "Charactersmith":    "en-US-JennyNeural",
    "Plotweaver":        "en-US-DavisNeural",
    "Editor":            "en-US-AriaNeural",
    # ── Core: Research Lab ──
    "Principal":         "en-US-GuyNeural",
    "Analyst":           "en-US-JennyNeural",
    "Contrarian":        "en-AU-WilliamNeural",
    "Synthesizer":       "en-US-SaraNeural",
    "Reviewer":          "en-US-AriaNeural",
    # ── Core: Debate Club ──
    "Moderator":         "en-US-GuyNeural",
    "Advocate":          "en-US-DavisNeural",
    "Opponent":          "en-GB-SoniaNeural",
    "Judge":             "en-US-AndrewNeural",
    # ── Core: Startup Sim ──
    "CEO":               "en-US-GuyNeural",
    "Engineer":          "en-US-DavisNeural",
    "Designer":          "en-US-JennyNeural",
    "Marketer":          "en-US-AriaNeural",
    "Investor":          "en-GB-RyanNeural",
    # ── Core: Code Shop ──
    "Architect":         "en-US-GuyNeural",
    "Backend":           "en-US-DavisNeural",
    "Frontend":          "en-US-JennyNeural",
    "Tester":            "en-US-SaraNeural",
    "CodeReviewer":      "en-US-AriaNeural",
    # ── Healthcare: Clinical Case ──
    "Attending":         "en-US-GuyNeural",
    "Diagnostician":     "en-US-DavisNeural",
    "Pharmacist":        "en-US-JennyNeural",
    "Specialist":        "en-GB-RyanNeural",
    "EvidenceReviewer":  "en-US-AriaNeural",
    # ── Healthcare: Practice Growth ──
    "PracticeDirector":  "en-US-GuyNeural",
    "RevenueAnalyst":    "en-US-DavisNeural",
    "OpsManager":        "en-AU-WilliamNeural",
    "PatientExperience": "en-US-JennyNeural",
    "ComplianceOfficer": "en-US-AriaNeural",
    # ── Healthcare: Behavioral Health ──
    "ClinicalDirector":  "en-US-GuyNeural",
    "Therapist":         "en-US-SaraNeural",
    "Psychiatrist":      "en-GB-RyanNeural",
    "CareCoordinator":   "en-US-JennyNeural",
    "OutcomesReviewer":  "en-US-AriaNeural",
    # ── Creative: Writers Room ──
    "Showrunner":        "en-US-GuyNeural",
    "StoryBreaker":      "en-US-DavisNeural",
    "DialogueWriter":    "en-US-JennyNeural",
    "PunchUpArtist":     "en-AU-WilliamNeural",
    "NotesExec":         "en-US-AriaNeural",
    # ── Creative: Philosophy Salon ──
    "Host":              "en-US-GuyNeural",
    "Empiricist":        "en-GB-RyanNeural",
    "Ethicist":          "en-US-SaraNeural",
    "Existentialist":    "en-US-DavisNeural",
    "Skeptic":           "en-US-AndrewNeural",
    # ── Creative: D&D Campaign ──
    "DungeonMaster":     "en-US-GuyNeural",
    "Loresmith":         "en-GB-RyanNeural",
    "EncounterDesigner": "en-US-DavisNeural",
    "NPCVoice":          "en-US-JennyNeural",
    "Playtester":        "en-US-AriaNeural",
    # ── Creative: Comedy Writers ──
    "HeadWriter":        "en-US-GuyNeural",
    "JokeSmith":         "en-AU-WilliamNeural",
    "SketchWriter":      "en-US-DavisNeural",
    "Satirist":          "en-GB-SoniaNeural",
    "Audience":          "en-US-AriaNeural",
    # ── Technical: Security Audit ──
    "CISO":              "en-US-GuyNeural",
    "ThreatModeler":     "en-US-DavisNeural",
    "AppSec":            "en-US-JennyNeural",
    "PenTester":         "en-AU-WilliamNeural",
    "GRC":               "en-US-AriaNeural",
    # ── Technical: Data Science ──
    "LeadDS":            "en-US-GuyNeural",
    "DataEngineer":      "en-GB-RyanNeural",
    "MLEngineer":        "en-US-DavisNeural",
    "MLOpsEngineer":     "en-US-JennyNeural",
    "StatsReviewer":     "en-US-AriaNeural",
    # ── Technical: System Design ──
    "PrincipalEngineer": "en-US-GuyNeural",
    "BackendArch":       "en-US-DavisNeural",
    "InfraEngineer":     "en-GB-RyanNeural",
    "SRE":               "en-AU-WilliamNeural",
    "StaffReviewer":     "en-US-AriaNeural",
    # ── Business: Legal Analysis ──
    "GeneralCounsel":    "en-US-GuyNeural",
    "Litigator":         "en-US-DavisNeural",
    "RegulatoryExpert":  "en-GB-RyanNeural",
    "ContractDrafter":   "en-US-JennyNeural",
    "RiskCounsel":       "en-US-AriaNeural",
    # ── Business: Financial Planning ──
    "CFO":               "en-US-GuyNeural",
    "FinancialAnalyst":  "en-US-DavisNeural",
    "TaxAdvisor":        "en-GB-RyanNeural",
    "InvestmentAnalyst": "en-US-JennyNeural",
    "Auditor":           "en-US-AriaNeural",
    # ── Business: Crisis Comms ──
    "CommsDirector":     "en-US-GuyNeural",
    "Spokesperson":      "en-US-DavisNeural",
    "StakeholderMgr":    "en-US-JennyNeural",
    "LegalReview":       "en-US-AriaNeural",
}

ROLE_VOICES: dict[str, str] = {
    "leader":      "en-US-GuyNeural",
    "worker":      "en-US-JennyNeural",
    "critic":      "en-US-AriaNeural",
    "synthesizer": "en-US-SaraNeural",
    "debater":     "en-US-DavisNeural",
    "judge":       "en-US-AndrewNeural",
}

_CLAUDE_PATH: str | None = shutil.which("claude")


class Narrator:
    """Generates natural spoken summaries and plays them with unique agent voices."""

    # Narration modes
    MODE_OFF = "off"
    MODE_HIGHLIGHTS = "highlights"    # leaders + final round only
    MODE_FULL = "full"                # all agents, summarized

    def __init__(self, mode: str = MODE_FULL) -> None:
        self.mode = mode
        self.console = Console(force_terminal=True)
        self._queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._skip_event = threading.Event()
        self._tmp_dir = tempfile.mkdtemp(prefix="agentforge_tts_")

        if mode != self.MODE_OFF:
            self._start_worker()

    def _start_worker(self) -> None:
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            text, voice = item
            if not self._skip_event.is_set():
                try:
                    loop.run_until_complete(self._speak(text, voice))
                except Exception:
                    pass
            self._queue.task_done()

        loop.close()

    async def _speak(self, text: str, voice: str) -> None:
        import edge_tts

        tmp_path = os.path.join(self._tmp_dir, "chunk.mp3")
        communicate = edge_tts.Communicate(text, voice, rate="+8%")
        await communicate.save(tmp_path)

        if os.path.getsize(tmp_path) > 0:
            self._play_audio(tmp_path)

    def _play_audio(self, path: str) -> None:
        import sys as _sys

        try:
            if _sys.platform == "darwin":
                # macOS — afplay is built-in
                subprocess.run(["afplay", path], capture_output=True, timeout=120)
            elif _sys.platform == "win32":
                # Windows — PowerShell MediaPlayer
                uri = path.replace("\\", "/")
                ps_script = (
                    "Add-Type -AssemblyName PresentationCore\n"
                    "$p = New-Object System.Windows.Media.MediaPlayer\n"
                    f"$p.Open([Uri]::new('{uri}'))\n"
                    "$p.Play()\n"
                    "while ($p.NaturalDuration.HasTimeSpan -eq $false) "
                    "{ Start-Sleep -Milliseconds 100 }\n"
                    "$duration = $p.NaturalDuration.TimeSpan.TotalMilliseconds\n"
                    "Start-Sleep -Milliseconds ($duration + 150)\n"
                    "$p.Close()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    capture_output=True,
                    timeout=120,
                )
            else:
                # Linux — try common players in order of likelihood
                for player_cmd in (
                    ["mpv", "--no-terminal", path],
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                    ["paplay", path],
                    ["aplay", path],
                ):
                    if shutil.which(player_cmd[0]):
                        subprocess.run(player_cmd, capture_output=True, timeout=120)
                        break
        except (subprocess.TimeoutExpired, Exception):
            pass

    def _summarize_for_speech(self, text: str, agent_name: str, agent_role: str) -> str:
        """Use a fast Claude call to distill agent output into natural spoken prose."""
        if not _CLAUDE_PATH:
            return ""

        prompt = (
            f"You are converting a written agent response into natural spoken narration. "
            f"The speaker is '{agent_name}' ({agent_role}).\n\n"
            f"RULES:\n"
            f"- Extract ONLY the 2-4 most important points, arguments, or findings\n"
            f"- Write in first person as {agent_name} speaking naturally\n"
            f"- NO URLs, NO markdown, NO tables, NO bullet points, NO brackets\n"
            f"- NO confidence tags like [HIGH] or [MEDIUM]\n"
            f"- NO @mentions or agent names\n"
            f"- NO 'done', 'complete', 'approved' tokens\n"
            f"- Write flowing sentences a human would actually say out loud\n"
            f"- Keep it under 80 words — this is a spoken summary, not a transcript\n"
            f"- Sound like a smart person making their key point in a meeting\n\n"
            f"AGENT OUTPUT TO SUMMARIZE:\n{text[:4000]}"
        )

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)

        try:
            result = subprocess.run(
                [_CLAUDE_PATH, "-p",
                 "--model", "haiku",
                 "--effort", "low",
                 "--no-session-persistence"],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        return ""

    def get_voice(self, agent_name: str, agent_role: str) -> str:
        return AGENT_VOICES.get(agent_name, ROLE_VOICES.get(agent_role, "en-US-AriaNeural"))

    def should_narrate(self, agent_role: str, is_final_round: bool) -> bool:
        """Decide whether to narrate based on mode."""
        if self.mode == self.MODE_OFF:
            return False
        if self.mode == self.MODE_HIGHLIGHTS:
            return agent_role == "leader" or is_final_round
        return True  # MODE_FULL

    def narrate_agent(
        self,
        text: str,
        agent_name: str,
        agent_role: str,
        is_final_round: bool = False,
    ) -> None:
        """Summarize and narrate an agent's response."""
        if not self.should_narrate(agent_role, is_final_round):
            return

        self._skip_event.clear()

        # Generate a natural spoken summary instead of reading raw text
        summary = self._summarize_for_speech(text, agent_name, agent_role)
        if not summary:
            return

        voice = self.get_voice(agent_name, agent_role)
        self._queue.put((summary, voice))

    def narrate_system(self, text: str, voice: str = "en-US-GuyNeural") -> None:
        """Short system announcement (round transitions, etc.)."""
        if self.mode == self.MODE_OFF:
            return
        self._skip_event.clear()
        self._queue.put((text, voice))

    def skip_current(self) -> None:
        """Skip whatever is currently playing/queued."""
        self._skip_event.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    def wait_until_done(self) -> None:
        if self.mode == self.MODE_OFF:
            return
        self._queue.join()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._queue.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        try:
            import shutil as sh
            sh.rmtree(self._tmp_dir, ignore_errors=True)
        except Exception:
            pass
