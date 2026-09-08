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
