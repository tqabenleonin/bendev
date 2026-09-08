import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from ..models import AgentResult, Task


class AgentAdapter(ABC):
    name: str

    @abstractmethod
    def run(self, task: Task, cwd: Path) -> AgentResult:
        ...

    @staticmethod
    def has_changes(cwd: Path) -> bool:
        # `git diff` alone misses newly-created untracked files; status catches both.
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True
        ).stdout
        return bool(status.strip())
