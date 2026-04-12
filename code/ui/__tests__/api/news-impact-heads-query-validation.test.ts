import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";
import { authenticateUserApiKeyFromAuthorizationHeader } from "@/lib/api-auth";

vi.mock("@/lib/api-auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-auth")>();
  return {
    ...actual,
    authenticateUserApiKeyFromAuthorizationHeader: vi.fn(),
  };
});

import { GET } from "@/app/api/v1/news/impact-heads/route";

const mockAuth = vi.mocked(authenticateUserApiKeyFromAuthorizationHeader);

describe("GET /api/v1/news/impact-heads — query validation (real service, no DB)", () => {
  beforeEach(() => {
    mockAuth.mockResolvedValue({
      ok: true,
      key: { keyId: "k", userId: "u", scopes: ["news:read"] },
      rawKey: "st_live_0123456789abcdef0123456789abcdef",
    });
  });

  it("returns 400 when limit is zero", async () => {
    const res = await GET(
      new NextRequest(new URL("http://localhost/api/v1/news/impact-heads?limit=0")),
    );
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toContain("limit");
  });
});
