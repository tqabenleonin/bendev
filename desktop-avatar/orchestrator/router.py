from .models import Task


class Router:
    """Routing is currently fully determined by GitHub labels, resolved in
    GitHubWatcher.poll_new_tasks(). This class is the extension point for
    heuristic or LLM-based routing later (e.g. falling back to file-count /
    diff-size heuristics when no agent label is present).
    """

    def route(self, task: Task) -> Task:
        return task
