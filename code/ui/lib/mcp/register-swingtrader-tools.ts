import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { AuthInfo } from "@modelcontextprotocol/sdk/server/auth/types.js";
import { z } from "zod";
import {
  getNewsImpactHeadById,
  listNewsImpactHeadsFromSearchParams,
} from "@/lib/api-v1/news-impact-heads-service";
import {
  appendScreeningRowsService,
  createScreeningRunService,
} from "@/lib/api-v1/screenings-run-service";
import { SCREENINGS_WRITE_SCOPE } from "@/lib/api-v1/screenings-api";
import type { ValidatedKey } from "@/lib/api-auth";

function keyFromAuthInfo(auth: AuthInfo | undefined): ValidatedKey | null {
  if (!auth) return null;
  const keyId = auth.extra?.keyId;
  if (typeof keyId !== "string") return null;
  return { keyId, userId: auth.clientId, scopes: auth.scopes };
}

function scopeDenied(scope: string) {
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify({
          error: `Forbidden: this key does not have the '${scope}' scope`,
        }),
      },
    ],
    isError: true as const,
  };
}

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }],
  };
}

function serviceError(message: string) {
  return {
    content: [{ type: "text" as const, text: message }],
    isError: true as const,
  };
}

const listImpactHeadsSchema = z.object({
  limit: z.number().int().min(1).max(100).optional(),
  offset: z.number().int().min(0).optional(),
  sort: z.string().max(64).optional(),
  fields: z.string().max(512).optional(),
  include_article: z.boolean().optional(),
  article_id: z.number().int().positive().optional(),
  cluster: z.string().max(64).optional(),
  ticker: z.string().max(12).optional(),
  from: z.string().max(40).optional(),
  to: z.string().max(40).optional(),
  min_confidence: z.number().min(0).max(1).optional(),
});

const getImpactHeadSchema = z.object({
  id: z.number().int().positive(),
  fields: z.string().max(512).optional(),
  include_article: z.boolean().optional(),
});

const createRunSchema = z.object({
  scan_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  source: z.string().min(1).max(128),
  market_json: z.record(z.string(), z.unknown()).optional(),
  result_json: z.record(z.string(), z.unknown()).optional(),
});

const appendRowsSchema = z.object({
  run_id: z.number().int().positive(),
  rows: z
    .array(
      z.object({
        dataset: z.string().min(1).max(64),
        row_data: z.record(z.string(), z.unknown()),
        symbol: z.string().max(32).optional(),
      }),
    )
    .min(1),
});

export function registerSwingtraderMcpTools(server: McpServer) {
  server.registerTool(
    "ping",
    {
      title: "Ping",
      description:
        "Health check. Uses the same user API key as v1 REST; returns user_id and scopes from the database.",
      inputSchema: z.object({}),
    },
    async (_args, extra) => {
      const auth = extra.authInfo as AuthInfo | undefined;
      const key = keyFromAuthInfo(auth);
      if (!key) return serviceError("Unauthorized");
      return jsonResult({ ok: true, user_id: key.userId, scopes: key.scopes });
    },
  );

  server.registerTool(
    "news_impact_heads_list",
    {
      title: "List news impact heads",
      description:
        "Lists news impact heads with the same query semantics as GET /api/v1/news/impact-heads. Requires news:read.",
      inputSchema: listImpactHeadsSchema,
    },
    async (raw, extra) => {
      const auth = extra.authInfo as AuthInfo | undefined;
      const key = keyFromAuthInfo(auth);
      if (!key) return serviceError("Unauthorized");
      if (!key.scopes.includes("news:read")) {
        return scopeDenied("news:read");
      }

      const args = listImpactHeadsSchema.safeParse(raw);
      if (!args.success) {
        return serviceError(`Invalid arguments: ${args.error.message}`);
      }

      const sp = new URLSearchParams();
      const a = args.data;
      if (a.limit != null) sp.set("limit", String(a.limit));
      if (a.offset != null) sp.set("offset", String(a.offset));
      if (a.sort != null) sp.set("sort", a.sort);
      if (a.fields != null) sp.set("fields", a.fields);
      if (a.include_article === false) sp.set("include", "");
      else if (a.include_article === true) sp.set("include", "article");
      if (a.article_id != null) sp.set("article_id", String(a.article_id));
      if (a.cluster != null) sp.set("cluster", a.cluster);
      if (a.ticker != null) sp.set("ticker", a.ticker);
      if (a.from != null) sp.set("from", a.from);
      if (a.to != null) sp.set("to", a.to);
      if (a.min_confidence != null) sp.set("min_confidence", String(a.min_confidence));

      const result = await listNewsImpactHeadsFromSearchParams(sp);
      if (!result.ok) return serviceError(`${result.status}: ${result.message}`);
      return jsonResult(result.body);
    },
  );

  server.registerTool(
    "news_impact_head_get",
    {
      title: "Get news impact head",
      description: "Fetches one impact head by id (GET /api/v1/news/impact-heads/{id}). Requires news:read.",
      inputSchema: getImpactHeadSchema,
    },
    async (raw, extra) => {
      const auth = extra.authInfo as AuthInfo | undefined;
      const key = keyFromAuthInfo(auth);
      if (!key) return serviceError("Unauthorized");
      if (!key.scopes.includes("news:read")) {
        return scopeDenied("news:read");
      }

      const args = getImpactHeadSchema.safeParse(raw);
      if (!args.success) {
        return serviceError(`Invalid arguments: ${args.error.message}`);
      }

      const sp = new URLSearchParams();
      if (args.data.fields != null) sp.set("fields", args.data.fields);
      if (args.data.include_article === false) sp.set("include", "");
      else if (args.data.include_article === true) sp.set("include", "article");

      const result = await getNewsImpactHeadById(args.data.id, sp);
      if (!result.ok) return serviceError(`${result.status}: ${result.message}`);
      return jsonResult(result.body);
    },
  );

  server.registerTool(
    "screenings_create_run",
    {
      title: "Create screening run",
      description: "Creates a user_scan_runs row (POST /api/v1/screenings/runs). Requires screenings:write.",
      inputSchema: createRunSchema,
    },
    async (raw, extra) => {
      const auth = extra.authInfo as AuthInfo | undefined;
      const key = keyFromAuthInfo(auth);
      if (!key) return serviceError("Unauthorized");
      if (!key.scopes.includes(SCREENINGS_WRITE_SCOPE)) {
        return scopeDenied(SCREENINGS_WRITE_SCOPE);
      }

      const args = createRunSchema.safeParse(raw);
      if (!args.success) {
        return serviceError(`Invalid arguments: ${args.error.message}`);
      }

      const result = await createScreeningRunService(key, args.data);
      if (!result.ok) return serviceError(`${result.status}: ${result.message}`);
      return jsonResult({ data: result.data });
    },
  );

  server.registerTool(
    "screenings_append_rows",
    {
      title: "Append screening rows",
      description:
        "Appends rows to a run (POST /api/v1/screenings/runs/{runId}/rows). Requires screenings:write.",
      inputSchema: appendRowsSchema,
    },
    async (raw, extra) => {
      const auth = extra.authInfo as AuthInfo | undefined;
      const key = keyFromAuthInfo(auth);
      if (!key) return serviceError("Unauthorized");
      if (!key.scopes.includes(SCREENINGS_WRITE_SCOPE)) {
        return scopeDenied(SCREENINGS_WRITE_SCOPE);
      }

      const args = appendRowsSchema.safeParse(raw);
      if (!args.success) {
        return serviceError(`Invalid arguments: ${args.error.message}`);
      }

      const { run_id, rows } = args.data;
      const result = await appendScreeningRowsService(key, run_id, { rows });
      if (!result.ok) return serviceError(`${result.status}: ${result.message}`);
      return jsonResult({ data: result.data });
    },
  );
}
