# Claude / Codex GitHub Orchestrator

Polls a GitHub repo for issues labeled `agent:claude` or `agent:codex`, runs the
corresponding CLI (Claude Code or OpenAI Codex) against an isolated git worktree,
and opens a PR with the result.

## How routing works

Apply one label to an issue:

- `agent:claude` — best for multi-file refactors, architecture/design decisions,
  security-sensitive changes, and anything needing repo-wide context.
- `agent:codex` — best for bounded, well-specified tasks: implement a described
  function, add tests for existing code, small clearly-scoped fixes.

The orchestrator picks up unlabeled-for-progress issues with either label, marks
them `agent:in-progress`, runs the agent, and on success opens a PR and swaps the
label to `agent:done` (or `agent:failed` with a comment explaining why).

## Setup

1. `pip install -r requirements.txt`
2. Install and authenticate the `claude` and `codex` CLIs separately (this
   orchestrator shells out to them — it does not call their APIs directly).
3. Clone the target repo once, locally, and point `REPO_LOCAL_PATH` at it — the
   orchestrator creates git worktrees off this clone for each task.
4. Copy `.env.example` to `.env` and fill in `GITHUB_TOKEN` (repo scope) and
   `GITHUB_REPO` (`owner/name`).
5. Run: `python -m orchestrator.main`

## Notes / things to review before running unattended

- `ClaudeAdapter` runs with `--permission-mode acceptEdits`, and `CodexAdapter`
  with `--sandbox workspace-write`. Review these against your CLI's current
  flags before pointing this at a real repo — both CLIs evolve their
  non-interactive flags across versions.
- Every task runs in its own `git worktree`, so parallel tasks can't collide.
  A failed or empty-diff run tears down its worktree without pushing anything.
- Output lands as a PR, not a direct push to `main` — nothing merges without a
  human (or your CI) approving it.
- `router.py` is a deliberate no-op today (labels decide everything); it's the
  place to add heuristic/auto-classification routing later if you drop the
  label requirement.
