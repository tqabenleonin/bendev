from ..models import AgentName
from .base import AgentAdapter
from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter

AGENTS: dict[AgentName, AgentAdapter] = {
    AgentName.CLAUDE: ClaudeAdapter(),
    AgentName.CODEX: CodexAdapter(),
}
