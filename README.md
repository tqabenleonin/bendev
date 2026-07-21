# FlowAgent

An MCP (Model Context Protocol) server that exposes Microsoft Power Automate
flow management as tools for MCP clients (Claude Code, Claude Desktop, etc.).

## Tools

| Tool | Description |
| --- | --- |
| `list_environments` | List accessible Power Platform environments |
| `list_flows` | List flows in an environment |
| `get_flow` | Get a flow's definition and metadata |
| `enable_flow` / `disable_flow` | Turn a flow on/off |
| `list_flow_runs` | List a flow's run history |
| `get_flow_run` | Get details of a specific run |
| `get_flow_trigger_callback_url` | Resolve a trigger's invokable callback URL |
| `trigger_flow` | POST to a trigger's callback URL to start a run |

## Setup

```bash
npm install
npm run build
```

### Authentication

Configure exactly one of the following via environment variables (see
`.env.example`):

1. **Bearer token** — `POWER_AUTOMATE_ACCESS_TOKEN`. Simplest option, e.g. for
   a quick test:
   ```bash
   export POWER_AUTOMATE_ACCESS_TOKEN=$(az account get-access-token \
     --resource https://service.flow.microsoft.com/ --query accessToken -o tsv)
   ```
2. **Service principal** — `POWER_AUTOMATE_TENANT_ID`, `POWER_AUTOMATE_CLIENT_ID`,
   `POWER_AUTOMATE_CLIENT_SECRET`. Requires an Azure AD app registration with
   API permissions granted for the Power Automate / Flow service.
3. **Interactive device-code login** — set `POWER_AUTOMATE_TENANT_ID` (and
   optionally `POWER_AUTOMATE_CLIENT_ID`; falls back to a well-known public
   client if omitted). On first use, FlowAgent prints a device-login URL and
   code to stderr for you to complete in a browser.

Optionally set `POWER_AUTOMATE_ENVIRONMENT_ID` to a default environment so
tools don't need it passed on every call.

### Registering with an MCP client

Add to your MCP client's server config, e.g. `.mcp.json`:

```json
{
  "mcpServers": {
    "flowagent": {
      "command": "node",
      "args": ["/absolute/path/to/bendev/build/index.js"],
      "env": {
        "POWER_AUTOMATE_TENANT_ID": "...",
        "POWER_AUTOMATE_CLIENT_ID": "...",
        "POWER_AUTOMATE_CLIENT_SECRET": "..."
      }
    }
  }
}
```

## Notes

- `trigger_flow` only works for flows with a manually invokable trigger
  (Request/HTTP or manual button trigger) — call `get_flow_trigger_callback_url`
  first to resolve the URL.
- The underlying REST API is the same one used by the Power Automate portal
  (`api.flow.microsoft.com`, `Microsoft.ProcessSimple` provider).
