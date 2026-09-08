from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AgentName(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ROUTED = "routed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    issue_number: int
    title: str
    body: str
    agent: AgentName
    status: TaskStatus = TaskStatus.PENDING
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AgentResult:
    success: bool
    diff_present: bool
    logs: str
    error: Optional[str] = None
