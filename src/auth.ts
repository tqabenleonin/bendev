import {
  ConfidentialClientApplication,
  PublicClientApplication,
  type AuthenticationResult,
} from "@azure/msal-node";
import { DEFAULT_SCOPE, loadConfig } from "./config.js";

// Well-known public client ID (Microsoft Azure CLI) used only as a fallback so that
// interactive device-code login works out of the box without requiring callers to
// register their own Azure AD app. Overridden by POWER_AUTOMATE_CLIENT_ID when set.
const FALLBACK_PUBLIC_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46";

let cachedToken: { value: string; expiresAt: number } | null = null;
let confidentialApp: ConfidentialClientApplication | null = null;
let publicApp: PublicClientApplication | null = null;

function authority(tenantId?: string): string {
  return `https://login.microsoftonline.com/${tenantId ?? "organizations"}`;
}

async function acquireViaClientCredentials(
  tenantId: string,
  clientId: string,
  clientSecret: string,
): Promise<AuthenticationResult | null> {
  if (!confidentialApp) {
    confidentialApp = new ConfidentialClientApplication({
      auth: { clientId, clientSecret, authority: authority(tenantId) },
    });
  }
  return confidentialApp.acquireTokenByClientCredential({ scopes: [DEFAULT_SCOPE] });
}

async function acquireViaDeviceCode(
  tenantId: string | undefined,
  clientId: string,
): Promise<AuthenticationResult | null> {
  if (!publicApp) {
    publicApp = new PublicClientApplication({
      auth: { clientId, authority: authority(tenantId) },
    });
  }

  const accounts = await publicApp.getTokenCache().getAllAccounts();
  if (accounts.length > 0) {
    const silent = await publicApp
      .acquireTokenSilent({ account: accounts[0], scopes: [DEFAULT_SCOPE] })
      .catch(() => null);
    if (silent) return silent;
  }

  return publicApp.acquireTokenByDeviceCode({
    scopes: [DEFAULT_SCOPE],
    deviceCodeCallback: (response) => {
      // MCP servers speak protocol over stdout, so device-code instructions must go to stderr.
      console.error(`\n[FlowAgent] Sign in required: ${response.message}\n`);
    },
  });
}

/**
 * Resolves an access token for the Power Automate Management API using whichever
 * auth mode is configured via environment variables, in priority order:
 *   1. POWER_AUTOMATE_ACCESS_TOKEN - a pre-acquired bearer token (simplest, good for testing)
 *   2. POWER_AUTOMATE_CLIENT_ID + POWER_AUTOMATE_CLIENT_SECRET (+ TENANT_ID) - service principal
 *   3. POWER_AUTOMATE_TENANT_ID (+ optional CLIENT_ID) - interactive device-code login
 */
export async function getAccessToken(): Promise<string> {
  const config = loadConfig();

  if (config.accessToken) {
    return config.accessToken;
  }

  if (cachedToken && cachedToken.expiresAt > Date.now() + 30_000) {
    return cachedToken.value;
  }

  let result: AuthenticationResult | null;

  if (config.clientId && config.clientSecret) {
    if (!config.tenantId) {
      throw new Error(
        "POWER_AUTOMATE_TENANT_ID is required when using service principal auth (POWER_AUTOMATE_CLIENT_ID/SECRET).",
      );
    }
    result = await acquireViaClientCredentials(config.tenantId, config.clientId, config.clientSecret);
  } else if (config.tenantId || config.clientId) {
    result = await acquireViaDeviceCode(config.tenantId, config.clientId ?? FALLBACK_PUBLIC_CLIENT_ID);
  } else {
    throw new Error(
      "No Power Automate credentials configured. Set one of: POWER_AUTOMATE_ACCESS_TOKEN, " +
        "POWER_AUTOMATE_CLIENT_ID + POWER_AUTOMATE_CLIENT_SECRET + POWER_AUTOMATE_TENANT_ID, or " +
        "POWER_AUTOMATE_TENANT_ID (for interactive device-code login). See README.md for setup.",
    );
  }

  if (!result?.accessToken) {
    throw new Error("Failed to acquire a Power Automate access token.");
  }

  cachedToken = {
    value: result.accessToken,
    expiresAt: result.expiresOn?.getTime() ?? Date.now() + 60_000,
  };
  return cachedToken.value;
}
