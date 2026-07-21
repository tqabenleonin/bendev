#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import * as flow from "./powerAutomateClient.js";

const server = new McpServer({ name: "flowagent", version: "0.1.0" });

function toResult(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
}

function toErrorResult(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

function tool<Args extends z.ZodRawShape>(
  name: string,
  config: { title: string; description: string; inputSchema: Args },
  handler: (args: z.objectOutputType<Args, z.ZodTypeAny>) => Promise<unknown>,
) {
  server.registerTool(name, config, (async (args: z.objectOutputType<Args, z.ZodTypeAny>) => {
    try {
      return toResult(await handler(args));
    } catch (error) {
      return toErrorResult(error);
    }
  }) as never);
}

const environmentIdField = z
  .string()
  .optional()
  .describe(
    "Power Platform environment ID. Falls back to POWER_AUTOMATE_ENVIRONMENT_ID if omitted.",
  );

tool(
  "list_environments",
  {
    title: "List Power Platform environments",
    description: "Lists the Power Platform environments the authenticated identity can access.",
    inputSchema: {},
  },
  () => flow.listEnvironments(),
);

tool(
  "list_flows",
  {
    title: "List Power Automate flows",
    description: "Lists the flows in a Power Platform environment.",
    inputSchema: { environmentId: environmentIdField },
  },
  ({ environmentId }) => flow.listFlows(environmentId),
);

tool(
  "get_flow",
  {
    title: "Get a Power Automate flow",
    description: "Gets the definition and metadata for a single flow.",
    inputSchema: { flowId: z.string().describe("The flow's GUID."), environmentId: environmentIdField },
  },
  ({ flowId, environmentId }) => flow.getFlow(flowId, environmentId),
);

tool(
  "enable_flow",
  {
    title: "Enable (turn on) a flow",
    description: "Turns on a currently-disabled flow.",
    inputSchema: { flowId: z.string().describe("The flow's GUID."), environmentId: environmentIdField },
  },
  ({ flowId, environmentId }) => flow.enableFlow(flowId, environmentId),
);

tool(
  "disable_flow",
  {
    title: "Disable (turn off) a flow",
    description: "Turns off a currently-enabled flow.",
    inputSchema: { flowId: z.string().describe("The flow's GUID."), environmentId: environmentIdField },
  },
  ({ flowId, environmentId }) => flow.disableFlow(flowId, environmentId),
);

tool(
  "list_flow_runs",
  {
    title: "List a flow's run history",
    description: "Lists recent runs for a flow, most recent first.",
    inputSchema: { flowId: z.string().describe("The flow's GUID."), environmentId: environmentIdField },
  },
  ({ flowId, environmentId }) => flow.listFlowRuns(flowId, environmentId),
);

tool(
  "get_flow_run",
  {
    title: "Get details of a specific flow run",
    description: "Gets the status, inputs, and outputs of a specific run of a flow.",
    inputSchema: {
      flowId: z.string().describe("The flow's GUID."),
      runId: z.string().describe("The run's identifier, as returned by list_flow_runs."),
      environmentId: environmentIdField,
    },
  },
  ({ flowId, runId, environmentId }) => flow.getFlowRun(flowId, runId, environmentId),
);

tool(
  "get_flow_trigger_callback_url",
  {
    title: "Get a flow trigger's callback URL",
    description:
      "Resolves the invokable callback URL for one of a flow's triggers (e.g. a Manual/HTTP request trigger). " +
      "Use the result with trigger_flow to actually run the flow.",
    inputSchema: {
      flowId: z.string().describe("The flow's GUID."),
      triggerName: z
        .string()
        .default("manual")
        .describe("The trigger's name from the flow definition (commonly 'manual' for Request/HTTP triggers)."),
      environmentId: environmentIdField,
    },
  },
  ({ flowId, triggerName, environmentId }) =>
    flow.getFlowTriggerCallbackUrl(flowId, triggerName, environmentId),
);

tool(
  "trigger_flow",
  {
    title: "Trigger a flow run",
    description:
      "Invokes a flow by POSTing to its trigger callback URL (obtained via get_flow_trigger_callback_url). " +
      "Only works for flows with a manually invokable trigger, such as Request/HTTP or manual button triggers.",
    inputSchema: {
      callbackUrl: z.string().url().describe("The callback URL returned by get_flow_trigger_callback_url."),
      payload: z.unknown().optional().describe("Optional JSON body to send as the trigger input."),
    },
  },
  ({ callbackUrl, payload }) => flow.triggerFlow(callbackUrl, payload),
);

const transport = new StdioServerTransport();
await server.connect(transport);
