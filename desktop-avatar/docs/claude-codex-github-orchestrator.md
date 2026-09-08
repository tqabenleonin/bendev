# Claude Code / Codex GitHub Orchestrator — Build Spec

**Audience:** an LLM coding agent (e.g. Claude Code) reading this file at the start
of a task, in a *different* repository than the one this was first built in.

**Goal:** stand up a small Python service that polls a GitHub repo for issues
labeled for a specific coding agent, runs that agent (Claude Code or Codex CLI)
headlessly against an isolated git worktree, and opens a PR with the result.
Nothing ever pushes straight to `main` — every change lands as a reviewable PR.

If the user hands you this file and asks you to set this up in their current
project, do the following, in order:

1. Read the **Prerequisites** section and verify each item (don't assume).
2. Ask the user only the things marked "user decision" below — everything else,
   just build.
3. Create the files exactly as specified in **File-by-file spec**, adjusted only
   for the target repo's own `owner/name`.
4. Follow **Setup steps** to wire up labels, auth, and the local clone.
5. Run the **Validation procedure** end-to-end before telling the user it works.
6. Read **Known pitfalls** *before* debugging any failure you hit — most failure
   modes in this system have already been solved once; check here first.

---

## Architecture overview

```
GitHub (issues/PRs/pushes)
        │
        ▼
 ┌─────────────────┐      ┌──────────────┐      ┌───────────────────┐
 │  GitHub Watcher  │─────▶│  Task Store  │◀────▶│      Router        │
 │   (polling)      │      │  (SQLite)    │      │ (labels → agent)    │
 └─────────────────┘      └──────────────┘      └─────────┬─────────┘
                                                            │
                                    ┌───────────────────────┼───────────────────────┐
                                    ▼                                               ▼
                          ┌───────────────────┐                         ┌───────────────────┐
                          │ ClaudeCodeAdapter │                         │   CodexAdapter    │
                          │ (subprocess: claude -p) │                   │ (subprocess: codex exec) │
                          └─────────┬─────────┘                         └─────────┬─────────┘
                                    │                                             │
                                    └──────────────────┬──────────────────────────┘
                                                        ▼
                                          ┌───────────────────────────┐
                                          │  Git Worktree + PR Manager │
                                          │  (branch, commit, push,    │
                                          │   open/update PR)          │
                                          └───────────────────────────┘
```

**Task lifecycle:** an issue gets labeled `agent:claude` or `agent:codex` →
watcher picks it up on the next poll → a fresh git worktree + branch is created
→ the corresponding CLI runs headlessly in that worktree → if it produced a
diff, commit/push/open-PR and relabel `agent:done`; if it failed or made no
changes, relabel `agent:failed` with a comment explaining why → worktree and
branch are always torn down afterward, success or failure.

**Routing philosophy** (a starting point, not a hard rule — adjust per project):
- **Claude Code**: multi-file refactors, architecture/design decisions,
  security-sensitive changes, review of the other agent's output, anything
  needing repo-wide context or long-horizon planning.
- **Codex**: bounded, well-specified tasks — implement a described function,
  add tests for existing code, small clearly-scoped bug fixes. Good for
  fanning out many small parallel tasks cheaply.
- Routing is driven entirely by which label a human (or issue template) puts
  on the issue — there is no automatic classifier. `router.py` is a deliberate
  no-op and the extension point if you want one later.

---

## Prerequisites — verify, don't assume

Run these checks before writing any code:

- `python --version` — 3.10+ (uses `X | None` union syntax, `dict[K, V]` generics).
- `git --version` — needs worktree support (any reasonably modern git has it).
- `gh --version` and `gh auth status` — must show an authenticated account with
  at least `repo` scope. This orchestrator reuses that cached token instead of
  asking the user to mint a separate PAT.
- `claude --version` — Claude Code CLI installed and logged in.
- `codex --version` — Codex CLI installed and logged in.
- A **local clone** of the target GitHub repo, reachable at whatever path you'll
  put in `REPO_LOCAL_PATH`. If it doesn't exist yet, `gh repo create` +
  `git push` it, or clone an existing one.

**User decisions to ask about, don't guess:**
- Which repo (`owner/name`) this targets, if not already obvious from context.
- Whether polling (simple, no public endpoint) or webhooks (real-time, needs a
  reachable URL) — this spec implements **polling**; treat webhooks as a swap-in
  replacement for `github_watcher.py` if the user wants that instead.
- Whether to actually push/create things on GitHub (repo creation, label
  creation, opening a real test PR) — these are visible, hard-to-fully-reverse
  actions; confirm before doing them, the same as any other git push.

---

## Setup steps

1. `pip install PyGithub python-dotenv`
2. Create five labels on the target repo:
   `agent:claude`, `agent:codex`, `agent:in-progress`, `agent:done`, `agent:failed`
   ```
   gh label create "agent:claude" --color "6366F1" --description "Route this issue to Claude Code" --repo <owner>/<repo>
   gh label create "agent:codex" --color "10B981" --description "Route this issue to Codex" --repo <owner>/<repo>
   gh label create "agent:in-progress" --color "F59E0B" --description "An agent is currently working this issue" --repo <owner>/<repo>
   gh label create "agent:done" --color "22C55E" --description "Agent opened a PR for this issue" --repo <owner>/<repo>
   gh label create "agent:failed" --color "EF4444" --description "Agent run failed - see comment" --repo <owner>/<repo>
   ```
3. Create `.env` (gitignored) with at minimum:
   ```
   GITHUB_TOKEN=
   GITHUB_REPO=<owner>/<repo>
   REPO_LOCAL_PATH=<path to a local clone of the target repo>
   WORKTREE_BASE_DIR=./worktrees
   DB_PATH=./orchestrator.db
   POLL_INTERVAL_SECONDS=60
   CLAUDE_CLI_PATH=claude
   CODEX_CLI_PATH=codex
   ```
   Leave `GITHUB_TOKEN` blank — `config.py` falls back to `gh auth token` at
   runtime, so no separate credential needs to be stored.
4. Add to `.gitignore`: `.env`, `__pycache__/`, `*.pyc`, `orchestrator.db`,
   `orchestrator_run.log`, `worktrees/`, and the repo-local-path folder if it
   lives inside this same project.

---

## File-by-file spec

Create a Python package `orchestrator/` with this exact structure. The code
below is the validated, bug-fixed version — reproduce it as-is rather than
rewriting from a general description, especially the two Windows-specific
`subprocess` details called out inline (see **Known pitfalls** for why).

### `orchestrator/config.py`

```python
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
```

### `orchestrator/models.py`

```python
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
```

### `orchestrator/store.py`

```python
import sqlite3
from contextlib import contextmanager
from typing import Optional

from .config import config
from .models import Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    issue_number INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    branch TEXT,
    pr_url TEXT,
    error TEXT
);
"""


class TaskStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or config.db_path)
        with self._conn() as conn:
            conn.execute(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_tracked(self, issue_number: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tasks WHERE issue_number = ?", (issue_number,)
            ).fetchone()
            return row is not None

    def save(self, task: Task) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO tasks (issue_number, title, agent, status, branch, pr_url, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(issue_number) DO UPDATE SET
                    title = excluded.title,
                    agent = excluded.agent,
                    status = excluded.status,
                    branch = excluded.branch,
                    pr_url = excluded.pr_url,
                    error = excluded.error
                """,
                (
                    task.issue_number,
                    task.title,
                    task.agent.value,
                    task.status.value,
                    task.branch,
                    task.pr_url,
                    task.error,
                ),
            )
```

### `orchestrator/github_watcher.py`

```python
from github import Github

from .config import config
from .models import AgentName, Task
from .store import TaskStore


class GitHubWatcher:
    """Polls the target repo for issues labeled for an agent and not yet processed.

    Routing is label-driven: `agent:claude` / `agent:codex` on an issue picks the
    agent directly. This is the extension point if polling should be swapped for
    webhooks later.
    """

    def __init__(self, store: TaskStore):
        self.gh = Github(config.github_token)
        self.repo = self.gh.get_repo(config.github_repo)
        self.store = store

    def poll_new_tasks(self) -> list[Task]:
        new_tasks = []
        for issue in self.repo.get_issues(state="open"):
            if issue.pull_request is not None:
                continue  # PRs show up in get_issues() too; skip them

            labels = {label.name for label in issue.labels}
            if config.label_in_progress in labels or config.label_done in labels:
                continue

            if config.label_claude in labels:
                agent = AgentName.CLAUDE
            elif config.label_codex in labels:
                agent = AgentName.CODEX
            else:
                continue

            if self.store.is_tracked(issue.number):
                continue

            new_tasks.append(
                Task(issue_number=issue.number, title=issue.title, body=issue.body or "", agent=agent)
            )
        return new_tasks

    def mark_in_progress(self, issue_number: int) -> None:
        self.repo.get_issue(issue_number).add_to_labels(config.label_in_progress)

    def mark_done(self, issue_number: int, pr_url: str) -> None:
        issue = self.repo.get_issue(issue_number)
        issue.remove_from_labels(config.label_in_progress)
        issue.add_to_labels(config.label_done)
        issue.create_comment(f"Automated PR opened: {pr_url}")

    def mark_failed(self, issue_number: int, error: str) -> None:
        issue = self.repo.get_issue(issue_number)
        issue.remove_from_labels(config.label_in_progress)
        issue.add_to_labels(config.label_failed)
        issue.create_comment(f"Agent run failed:\n```\n{error[:1500]}\n```")
```

### `orchestrator/router.py`

```python
from .models import Task


class Router:
    """Routing is currently fully determined by GitHub labels, resolved in
    GitHubWatcher.poll_new_tasks(). This class is the extension point for
    heuristic or LLM-based routing later (e.g. falling back to file-count /
    diff-size heuristics when no agent label is present).
    """

    def route(self, task: Task) -> Task:
        return task
```

### `orchestrator/git_manager.py`

```python
import subprocess
from pathlib import Path

from github import Github

from .config import config
from .models import Task


class GitManager:
    def __init__(self):
        self.gh = Github(config.github_token)
        self.repo = self.gh.get_repo(config.github_repo)

    def create_worktree(self, task: Task) -> Path:
        branch = f"agent/{task.agent.value}/issue-{task.issue_number}"
        worktree_path = config.worktree_base_dir / f"issue-{task.issue_number}"

        subprocess.run(["git", "fetch", "origin"], cwd=config.repo_local_path, check=True)
        # A prior crashed/interrupted run may have left this branch behind; drop it so retries don't collide.
        subprocess.run(["git", "branch", "-D", branch], cwd=config.repo_local_path, check=False)
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path), "origin/main"],
            cwd=config.repo_local_path,
            check=True,
        )
        task.branch = branch
        return worktree_path

    def commit_and_push(self, task: Task, worktree_path: Path) -> None:
        subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Automated fix for #{task.issue_number} (via {task.agent.value})"],
            cwd=worktree_path,
            check=True,
        )
        subprocess.run(["git", "push", "-u", "origin", task.branch], cwd=worktree_path, check=True)

    def open_pull_request(self, task: Task) -> str:
        pr = self.repo.create_pull(
            title=f"[{task.agent.value}] {task.title}",
            body=f"Automated resolution of #{task.issue_number} by `{task.agent.value}`.\n\nCloses #{task.issue_number}.",
            head=task.branch,
            base="main",
        )
        return pr.html_url

    def remove_worktree(self, worktree_path: Path, branch: str | None = None) -> None:
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path), "--force"],
            cwd=config.repo_local_path,
            check=False,
        )
        if branch:
            subprocess.run(["git", "branch", "-D", branch], cwd=config.repo_local_path, check=False)
```

### `orchestrator/agents/base.py`

```python
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
```

### `orchestrator/agents/claude_adapter.py`

```python
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
```

**Do NOT add `shell=True` here.** `claude` on most installs is a real native
executable, not a shim — adding `shell=True` gains nothing and reintroduces the
argv-newline bug described below.

### `orchestrator/agents/codex_adapter.py`

```python
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
```

### `orchestrator/agents/__init__.py`

```python
from ..models import AgentName
from .base import AgentAdapter
from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter

AGENTS: dict[AgentName, AgentAdapter] = {
    AgentName.CLAUDE: ClaudeAdapter(),
    AgentName.CODEX: CodexAdapter(),
}
```

### `orchestrator/main.py`

```python
import logging
import time

from .agents import AGENTS
from .config import config
from .git_manager import GitManager
from .github_watcher import GitHubWatcher
from .models import Task, TaskStatus
from .router import Router
from .store import TaskStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("orchestrator")


def process_task(task: Task, watcher: GitHubWatcher, git_mgr: GitManager, store: TaskStore) -> None:
    log.info("Processing issue #%s with agent=%s", task.issue_number, task.agent.value)
    watcher.mark_in_progress(task.issue_number)
    task.status = TaskStatus.RUNNING
    store.save(task)

    worktree_path = git_mgr.create_worktree(task)
    store.save(task)

    try:
        result = AGENTS[task.agent].run(task, worktree_path)

        if not result.success:
            task.status = TaskStatus.FAILED
            task.error = result.error
            store.save(task)
            watcher.mark_failed(task.issue_number, result.error or "unknown error")
            return

        if not result.diff_present:
            task.status = TaskStatus.FAILED
            task.error = "agent completed but produced no changes"
            store.save(task)
            watcher.mark_failed(task.issue_number, task.error)
            return

        git_mgr.commit_and_push(task, worktree_path)
        task.pr_url = git_mgr.open_pull_request(task)
        task.status = TaskStatus.DONE
        store.save(task)
        watcher.mark_done(task.issue_number, task.pr_url)
    finally:
        git_mgr.remove_worktree(worktree_path, task.branch)


def main() -> None:
    config.validate()
    config.worktree_base_dir.mkdir(parents=True, exist_ok=True)

    store = TaskStore()
    watcher = GitHubWatcher(store)
    router = Router()
    git_mgr = GitManager()

    log.info(
        "Orchestrator started. Watching %s every %ss", config.github_repo, config.poll_interval_seconds
    )
    while True:
        try:
            for task in watcher.poll_new_tasks():
                task = router.route(task)
                task.status = TaskStatus.ROUTED
                store.save(task)
                try:
                    process_task(task, watcher, git_mgr, store)
                except Exception as exc:
                    log.exception("Task #%s failed", task.issue_number)
                    watcher.mark_failed(task.issue_number, str(exc))
        except Exception:
            log.exception("Polling cycle failed")
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    main()
```

### `requirements.txt`

```
PyGithub>=2.3
python-dotenv>=1.0
```

---

## Known pitfalls (read before debugging a failure)

These are real bugs hit and fixed while building this the first time. If
something in a new project fails in one of these ways, it's almost certainly
this, not a new problem — check here before re-diagnosing from scratch.

1. **Windows + npm-shim CLIs truncate multiline prompts.** `codex` (and any
   npm-installed CLI) is a `.cmd` shim on Windows. `subprocess.run(["codex", ...])`
   without `shell=True` fails outright with `WinError 2` (Python won't resolve
   `PATHEXT` on a bare command name). But adding `shell=True` routes the call
   through `cmd.exe`, which **silently truncates the argument at its first
   embedded newline** — a multiline issue-body prompt becomes just its first
   line, with no error raised. This happens whether or not you set
   `shell=True` yourself, because Windows internally reinvokes `.cmd` files via
   `cmd.exe` regardless. **Fix:** never pass a multiline string as a CLI
   argument on Windows. Pipe it via stdin instead (`"-"` as the prompt arg,
   `input=prompt` in `subprocess.run`). This is why `codex_adapter.py` looks
   the way it does above. `claude`'s CLI is usually a real `.exe`, not a shim —
   don't add `shell=True` to that adapter, or you'll manufacture the same bug
   for no reason.

2. **`git diff --stat` misses new files.** It only shows changes to files git
   already tracks. An agent that *creates* a new file (the common case) will
   read as "no changes" and get silently discarded if you check with
   `git diff`. Use `git status --porcelain` instead (see `AgentAdapter.has_changes`)
   — it catches both modified and untracked-new files.

3. **Worktree/branch cleanup must be unconditional.** If cleanup only happens
   on the explicit success/failure return paths, an unhandled exception mid-run
   skips it entirely, leaving a stale worktree and branch that collide with the
   next retry attempt (`git worktree add -b <branch>` fails if `<branch>`
   already exists). Put cleanup in a `finally` block (see `process_task` above),
   and make `create_worktree` itself defensive by force-deleting any
   same-named local branch before creating the new one.

4. **On Windows, don't manage background processes with git-bash `ps`/`kill`.**
   Git-bash's `ps` shows MSYS-translated PIDs that do **not** match real Windows
   process IDs, so `kill <pid>` from that `ps` output can silently fail to kill
   anything, or kill the wrong thing. Use PowerShell instead:
   `Get-Process | Where-Object { $_.ProcessName -match "python" }` and
   `Stop-Process -Id <id> -Force` with the real PIDs it reports. This matters a
   lot here because leaving a duplicate poller running against the same repo
   causes two instances to race on the same worktree/branch/SQLite file.

---

## Validation procedure

Before telling the user this works:

1. `pip install -r requirements.txt`.
2. Confirm config resolves: run a short Python snippet that imports `config`,
   prints `config.github_repo`, `bool(config.github_token)`, and calls
   `config.validate()`.
3. Open one small, well-scoped test issue and label it (`agent:codex` is
   cheapest to test with first). E.g. "add a function that returns a fixed
   string, in a new file."
4. Start `python -m orchestrator.main` as a **single** background instance —
   verify via `Get-Process` (see pitfall 4) that exactly one instance is
   running before waiting on it.
5. Confirm end-to-end: `gh pr list --repo <owner>/<repo>` shows a new PR, and
   `gh pr diff <number>` shows the expected file change. Check the issue got
   relabeled `agent:done` with a comment linking the PR.
6. Kill the background instance when done — don't leave an unattended agent
   loop running against a real repo without the user knowing it's running.

---

## Adapting this to a new repo

The only things that change per-project:
- `.env`'s `GITHUB_REPO` and `REPO_LOCAL_PATH`.
- The routing split in the **Architecture overview** section, if the project's
  actual task mix suggests a different Claude/Codex division of labor.
- Optionally, `router.py`, if the user wants heuristic or auto-classified
  routing instead of pure GitHub labels.

Everything else — the file layout, the subprocess invocations, the pitfalls —
is project-agnostic and should be reproduced as-is.
