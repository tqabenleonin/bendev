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
