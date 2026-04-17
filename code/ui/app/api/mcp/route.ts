import { createMcpHandler } from "mcp-handler";
import { runMcpWithUserApiKeyAuth } from "@/lib/mcp/mcp-api-key-gateway";
import { registerSwingtraderMcpTools } from "@/lib/mcp/register-swingtrader-tools";

export const maxDuration = 60;

/**
 * Model Context Protocol (Streamable HTTP) — same process as Next.js API routes.
 *
 * Endpoint: POST /api/mcp  (basePath `/api` → streamable HTTP at `/api/mcp`)
 * Auth: the **same** user API key as v1 REST (`Authorization: Bearer st_live_…`):
 * identical validation RPC, per-minute rate limit (429 + Retry-After), invalid-key timing, and DB-backed scopes.
 * Tool handlers enforce `news:read` / `screenings:write` / `relationships:read` the same way as the matching REST routes.
 *
 * Cursor example (Streamable HTTP):
 *   { "url": "https://<host>/api/mcp", "headers": { "Authorization": "Bearer st_live_…" } }
 *
 * Stdio-only clients: npx -y mcp-remote https://<host>/api/mcp --header "Authorization: Bearer …"
 */
const mcpHandler = createMcpHandler(
  (server) => {
    registerSwingtraderMcpTools(server);
  },
  {
    serverInfo: {
      name: "swingtrader-ui",
      version: "0.1.0",
    },
  },
  {
    basePath: "/api",
    maxDuration: 60,
  },
);

function handler(req: Request) {
  return runMcpWithUserApiKeyAuth(req, mcpHandler);
}

export { handler as GET, handler as POST, handler as DELETE };
