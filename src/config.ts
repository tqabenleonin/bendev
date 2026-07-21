export interface FlowAgentConfig {
  tenantId?: string;
  clientId?: string;
  clientSecret?: string;
  accessToken?: string;
  defaultEnvironmentId?: string;
}

const RESOURCE = "https://service.flow.microsoft.com/";
export const FLOW_API_BASE = "https://api.flow.microsoft.com";
export const API_VERSION = "2016-11-01";
export const DEFAULT_SCOPE = `${RESOURCE}.default`;

export function loadConfig(): FlowAgentConfig {
  return {
    tenantId: process.env.POWER_AUTOMATE_TENANT_ID,
    clientId: process.env.POWER_AUTOMATE_CLIENT_ID,
    clientSecret: process.env.POWER_AUTOMATE_CLIENT_SECRET,
    accessToken: process.env.POWER_AUTOMATE_ACCESS_TOKEN,
    defaultEnvironmentId: process.env.POWER_AUTOMATE_ENVIRONMENT_ID,
  };
}
