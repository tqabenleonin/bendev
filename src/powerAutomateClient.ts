import { API_VERSION, FLOW_API_BASE, loadConfig } from "./config.js";
import { getAccessToken } from "./auth.js";

export class PowerAutomateApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
  ) {
    super(`Power Automate API request failed (${status}): ${body}`);
  }
}

async function request<T>(
  method: string,
  path: string,
  options: { query?: Record<string, string>; body?: unknown } = {},
): Promise<T> {
  const token = await getAccessToken();
  const url = new URL(`${FLOW_API_BASE}${path}`);
  url.searchParams.set("api-version", API_VERSION);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    url.searchParams.set(key, value);
  }

  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  const text = await response.text();
  if (!response.ok) {
    throw new PowerAutomateApiError(response.status, text);
  }
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

function resolveEnvironmentId(environmentId?: string): string {
  const resolved = environmentId ?? loadConfig().defaultEnvironmentId;
  if (!resolved) {
    throw new Error(
      "No environmentId provided and POWER_AUTOMATE_ENVIRONMENT_ID is not set. " +
        "Use list_environments to find one, then pass it explicitly or set the env var.",
    );
  }
  return resolved;
}

export function listEnvironments() {
  return request("GET", "/providers/Microsoft.ProcessSimple/environments");
}

export function listFlows(environmentId?: string) {
  const env = resolveEnvironmentId(environmentId);
  return request("GET", `/providers/Microsoft.ProcessSimple/environments/${env}/flows`);
}

export function getFlow(flowId: string, environmentId?: string) {
  const env = resolveEnvironmentId(environmentId);
  return request("GET", `/providers/Microsoft.ProcessSimple/environments/${env}/flows/${flowId}`);
}

export function enableFlow(flowId: string, environmentId?: string) {
  const env = resolveEnvironmentId(environmentId);
  return request(
    "POST",
    `/providers/Microsoft.ProcessSimple/environments/${env}/flows/${flowId}/start`,
  );
}

export function disableFlow(flowId: string, environmentId?: string) {
  const env = resolveEnvironmentId(environmentId);
  return request(
    "POST",
    `/providers/Microsoft.ProcessSimple/environments/${env}/flows/${flowId}/stop`,
  );
}

export function listFlowRuns(flowId: string, environmentId?: string) {
  const env = resolveEnvironmentId(environmentId);
  return request(
    "GET",
    `/providers/Microsoft.ProcessSimple/environments/${env}/flows/${flowId}/runs`,
  );
}

export function getFlowRun(flowId: string, runId: string, environmentId?: string) {
  const env = resolveEnvironmentId(environmentId);
  return request(
    "GET",
    `/providers/Microsoft.ProcessSimple/environments/${env}/flows/${flowId}/runs/${runId}`,
  );
}

export function getFlowTriggerCallbackUrl(
  flowId: string,
  triggerName: string,
  environmentId?: string,
) {
  const env = resolveEnvironmentId(environmentId);
  return request(
    "POST",
    `/providers/Microsoft.ProcessSimple/environments/${env}/flows/${flowId}/triggers/${triggerName}/listCallbackUrl`,
  );
}

export async function triggerFlow(callbackUrl: string, payload?: unknown) {
  const response = await fetch(callbackUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload !== undefined ? JSON.stringify(payload) : undefined,
  });
  const text = await response.text();
  if (!response.ok) {
    throw new PowerAutomateApiError(response.status, text);
  }
  return { status: response.status, body: text ? safeJsonParse(text) : undefined };
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
