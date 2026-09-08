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
