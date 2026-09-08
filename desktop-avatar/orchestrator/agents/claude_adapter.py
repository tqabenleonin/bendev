import subprocess
from pathlib import Path

from ..config import config
from ..models import AgentResult, Task
from .base import AgentAdapter


class ClaudeAdapter(AgentAdapter):
    name = "claude"

    def run(self, task: Task, cwd: Path) -> AgentResult:
        prompt = (
            f"Resolve GitHub issue #{task.issue_number}: {task.title}\n\n"
            f"{task.body}\n\n"
            "Make the necessary code changes directly in this repository. "
            "Do not ask questions; make reasonable assumptions."
        )
        try:
            proc = subprocess.run(
                [
                    config.claude_cli,
                    "-p", prompt,
                    "--permission-mode", "acceptEdits",
                    "--output-format", "json",
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=1800,
            )
        except subprocess.TimeoutExpired as exc:
            return AgentResult(success=False, diff_present=False, logs="", error=f"timed out: {exc}")

        return AgentResult(
            success=proc.returncode == 0,
            diff_present=self.has_changes(cwd),
            logs=proc.stdout + proc.stderr,
            error=None if proc.returncode == 0 else proc.stderr,
        )
