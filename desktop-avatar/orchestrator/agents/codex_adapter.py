import subprocess
import sys
from pathlib import Path

from ..config import config
from ..models import AgentResult, Task
from .base import AgentAdapter


class CodexAdapter(AgentAdapter):
    name = "codex"

    def run(self, task: Task, cwd: Path) -> AgentResult:
        prompt = (
            f"Resolve GitHub issue #{task.issue_number}: {task.title}\n\n"
            f"{task.body}\n\n"
            "Make the necessary code changes directly in this repository."
        )
        try:
            proc = subprocess.run(
                [
                    config.codex_cli,
                    "exec",
                    "-",  # read the prompt from stdin: avoids argv newline-mangling on Windows .cmd shims
                    "--sandbox", "workspace-write",
                ],
                input=prompt,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=1800,
                shell=sys.platform == "win32",  # npm-installed CLIs are .cmd shims on Windows
            )
        except subprocess.TimeoutExpired as exc:
            return AgentResult(success=False, diff_present=False, logs="", error=f"timed out: {exc}")

        return AgentResult(
            success=proc.returncode == 0,
            diff_present=self.has_changes(cwd),
            logs=proc.stdout + proc.stderr,
            error=None if proc.returncode == 0 else proc.stderr,
        )
