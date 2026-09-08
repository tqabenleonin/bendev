import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _resolve_github_token() -> str:
    """Prefer an explicit GITHUB_TOKEN; otherwise reuse the token `gh` already
    has cached for the logged-in user, so no separate credential is stored."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return ""


@dataclass
class Config:
    github_token: str = field(default_factory=_resolve_github_token)
    github_repo: str = os.environ.get("GITHUB_REPO", "")  # "owner/name"
    repo_local_path: Path = Path(os.environ.get("REPO_LOCAL_PATH", "./repo"))
    worktree_base_dir: Path = Path(os.environ.get("WORKTREE_BASE_DIR", "./worktrees"))
    db_path: Path = Path(os.environ.get("DB_PATH", "./orchestrator.db"))
    poll_interval_seconds: int = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
    claude_cli: str = os.environ.get("CLAUDE_CLI_PATH", "claude")
    codex_cli: str = os.environ.get("CODEX_CLI_PATH", "codex")

    label_claude: str = "agent:claude"
    label_codex: str = "agent:codex"
    label_in_progress: str = "agent:in-progress"
    label_done: str = "agent:done"
    label_failed: str = "agent:failed"

    def validate(self) -> None:
        missing = [
            name
            for name, value in [("GITHUB_TOKEN", self.github_token), ("GITHUB_REPO", self.github_repo)]
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


config = Config()
