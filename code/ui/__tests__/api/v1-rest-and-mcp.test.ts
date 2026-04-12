import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";
import { authenticateUserApiKeyFromAuthorizationHeader, USER_API_KEY_BEARER_EXPECTED } from "@/lib/api-auth";
import {
  listNewsImpactHeadsFromSearchParams,
  getNewsImpactHeadById,
} from "@/lib/api-v1/news-impact-heads-service";
import { createScreeningRunService, appendScreeningRowsService } from "@/lib/api-v1/screenings-run-service";

vi.mock("mcp-handler", () => ({
  createMcpHandler: vi.fn(() => () =>
    Promise.resolve(
      new Response(JSON.stringify({ jsonrpc: "2.0", result: "stub", id: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  ),
}));

vi.mock("@/lib/api-auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-auth")>();
  return {
    ...actual,
    authenticateUserApiKeyFromAuthorizationHeader: vi.fn(),
  };
});

vi.mock("@/lib/api-v1/news-impact-heads-service", () => ({
  listNewsImpactHeadsFromSearchParams: vi.fn(),
  getNewsImpactHeadById: vi.fn(),
}));

vi.mock("@/lib/api-v1/screenings-run-service", () => ({
  createScreeningRunService: vi.fn(),
  appendScreeningRowsService: vi.fn(),
}));

import { GET as newsListGET, OPTIONS as newsListOPTIONS } from "@/app/api/v1/news/impact-heads/route";
import { GET as newsByIdGET, OPTIONS as newsByIdOPTIONS } from "@/app/api/v1/news/impact-heads/[id]/route";
import { POST as runsPOST, OPTIONS as runsOPTIONS } from "@/app/api/v1/screenings/runs/route";
import { POST as rowsPOST, OPTIONS as rowsOPTIONS } from "@/app/api/v1/screenings/runs/[runId]/rows/route";
import { GET as mcpGET, POST as mcpPOST } from "@/app/api/mcp/route";

const mockAuth = vi.mocked(authenticateUserApiKeyFromAuthorizationHeader);
const mockListHeads = vi.mocked(listNewsImpactHeadsFromSearchParams);
const mockGetHead = vi.mocked(getNewsImpactHeadById);
const mockCreateRun = vi.mocked(createScreeningRunService);
const mockAppendRows = vi.mocked(appendScreeningRowsService);

const newsReadKey = {
  ok: true as const,
  key: { keyId: "key-1", userId: "user-1", scopes: ["news:read"] as string[] },
  rawKey: "st_live_0123456789abcdef0123456789abcdef",
};

const screeningsWriteKey = {
  ok: true as const,
  key: { keyId: "key-2", userId: "user-1", scopes: ["screenings:write"] as string[] },
  rawKey: "st_live_fedcba9876543210fedcba9876543210",
};

function req(url: string, init?: RequestInit) {
  return new NextRequest(new URL(url, "http://localhost"), init);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockAuth.mockResolvedValue({ ok: false, reason: "missing_or_malformed_header" });
});

describe("OPTIONS (CORS preflight)", () => {
  it("news impact-heads list returns 204 with Allow headers", async () => {
    const res = await newsListOPTIONS();
    expect(res.status).toBe(204);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("*");
    expect(res.headers.get("Access-Control-Allow-Methods")).toContain("GET");
  });

  it("news impact-heads by id returns 204", async () => {
    const res = await newsByIdOPTIONS();
    expect(res.status).toBe(204);
  });

  it("screenings runs returns 204", async () => {
    const res = await runsOPTIONS();
    expect(res.status).toBe(204);
  });

  it("screenings rows returns 204", async () => {
    const res = await rowsOPTIONS();
    expect(res.status).toBe(204);
  });
});

describe("GET /api/v1/news/impact-heads", () => {
  it("returns 401 when Authorization is missing", async () => {
    const res = await newsListGET(req("http://localhost/api/v1/news/impact-heads"));
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.error).toBe(USER_API_KEY_BEARER_EXPECTED);
    expect(mockListHeads).not.toHaveBeenCalled();
  });

  it("returns 400 when the list service rejects query params", async () => {
    mockAuth.mockResolvedValue(newsReadKey);
    mockListHeads.mockResolvedValue({
      ok: false,
      status: 400,
      message: "'limit' must be a positive integer",
    });
    const res = await newsListGET(req("http://localhost/api/v1/news/impact-heads?limit=0"));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("'limit' must be a positive integer");
    expect(mockListHeads).toHaveBeenCalledTimes(1);
  });

  it("returns 200 and JSON body when auth and service succeed", async () => {
    mockAuth.mockResolvedValue(newsReadKey);
    mockListHeads.mockResolvedValue({
      ok: true,
      body: { data: [], pagination: { limit: 20, offset: 0, total: 0 } },
    });
    const res = await newsListGET(req("http://localhost/api/v1/news/impact-heads"));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.data).toEqual([]);
    expect(body.pagination).toEqual({ limit: 20, offset: 0, total: 0 });
    expect(mockListHeads).toHaveBeenCalledTimes(1);
  });
});

describe("GET /api/v1/news/impact-heads/[id]", () => {
  it("returns 400 for non-numeric id", async () => {
    mockAuth.mockResolvedValue(newsReadKey);
    const res = await newsByIdGET(req("http://localhost/api/v1/news/impact-heads/abc"), {
      params: Promise.resolve({ id: "abc" }),
    });
    expect(res.status).toBe(400);
    expect(mockGetHead).not.toHaveBeenCalled();
  });

  it("returns 200 when service returns a row", async () => {
    mockAuth.mockResolvedValue(newsReadKey);
    mockGetHead.mockResolvedValue({
      ok: true,
      body: { data: { id: 1, cluster: "MACRO_SENSITIVITY" } },
    });
    const res = await newsByIdGET(req("http://localhost/api/v1/news/impact-heads/1"), {
      params: Promise.resolve({ id: "1" }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.data.id).toBe(1);
    expect(mockGetHead).toHaveBeenCalledWith(1, expect.any(URLSearchParams));
  });
});

describe("POST /api/v1/screenings/runs", () => {
  it("returns 401 without bearer token", async () => {
    const res = await runsPOST(
      req("http://localhost/api/v1/screenings/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scan_date: "2025-01-01", source: "test" }),
      }),
    );
    expect(res.status).toBe(401);
    expect(mockCreateRun).not.toHaveBeenCalled();
  });

  it("returns 403 when key lacks screenings:write", async () => {
    mockAuth.mockResolvedValue(newsReadKey);
    const res = await runsPOST(
      req("http://localhost/api/v1/screenings/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${newsReadKey.rawKey}`,
        },
        body: JSON.stringify({ scan_date: "2025-01-01", source: "test" }),
      }),
    );
    expect(res.status).toBe(403);
    expect(mockCreateRun).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid JSON", async () => {
    mockAuth.mockResolvedValue(screeningsWriteKey);
    const res = await runsPOST(
      req("http://localhost/api/v1/screenings/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${screeningsWriteKey.rawKey}`,
        },
        body: "not-json",
      }),
    );
    expect(res.status).toBe(400);
    expect(mockCreateRun).not.toHaveBeenCalled();
  });

  it("returns 201 when create service succeeds", async () => {
    mockAuth.mockResolvedValue(screeningsWriteKey);
    mockCreateRun.mockResolvedValue({
      ok: true,
      data: {
        id: 99,
        created_at: "2025-01-01T00:00:00Z",
        scan_date: "2025-01-01",
        source: "unit-test",
        market_json: null,
        result_json: null,
      },
    });
    const res = await runsPOST(
      req("http://localhost/api/v1/screenings/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${screeningsWriteKey.rawKey}`,
        },
        body: JSON.stringify({ scan_date: "2025-01-01", source: "unit-test" }),
      }),
    );
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.data.id).toBe(99);
    expect(mockCreateRun).toHaveBeenCalledTimes(1);
  });
});

describe("POST /api/v1/screenings/runs/[runId]/rows", () => {
  it("returns 400 for invalid runId", async () => {
    mockAuth.mockResolvedValue(screeningsWriteKey);
    const res = await rowsPOST(
      req("http://localhost/api/v1/screenings/runs/bad/rows", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${screeningsWriteKey.rawKey}`,
        },
        body: JSON.stringify({ rows: [{ dataset: "d", row_data: {} }] }),
      }),
      { params: Promise.resolve({ runId: "bad" }) },
    );
    expect(res.status).toBe(400);
    expect(mockAppendRows).not.toHaveBeenCalled();
  });
});

describe("/api/mcp", () => {
  it("POST returns 401 JSON when Authorization is missing", async () => {
    const res = await mcpPOST(new Request("http://localhost/api/mcp", { method: "POST" }));
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.error).toBe(USER_API_KEY_BEARER_EXPECTED);
  });

  it("GET returns 401 when Authorization is missing", async () => {
    const res = await mcpGET(new Request("http://localhost/api/mcp", { method: "GET" }));
    expect(res.status).toBe(401);
  });

  it("POST forwards to MCP handler after successful API key auth", async () => {
    mockAuth.mockResolvedValue({
      ok: true,
      key: { keyId: "k", userId: "u", scopes: ["news:read", "screenings:write"] },
      rawKey: "st_live_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    });
    const res = await mcpPOST(
      new Request("http://localhost/api/mcp", {
        method: "POST",
        headers: {
          Authorization: "Bearer st_live_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "Content-Type": "application/json",
        },
        body: "{}",
      }),
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.result).toBe("stub");
  });
});
