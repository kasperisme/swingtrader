import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { generateApiKey } from "@/lib/api-auth";

const MAX_KEYS_PER_USER = 10;

// ── GET  /api/user/api-keys ──────────────────────────────────────────────────
// List all (non-deleted) API keys for the authenticated user.
export async function GET() {
  const supabase = await createClient();
  const {
    data: { user },
    error: authErr,
  } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_api_keys")
    .select("id, name, key_prefix, scopes, created_at, last_used_at, expires_at, revoked_at")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: "Failed to fetch keys" }, { status: 500 });
  return NextResponse.json(data ?? []);
}

// ── POST /api/user/api-keys ──────────────────────────────────────────────────
// Create a new API key. Returns the raw key exactly once in the response.
// Body: { name: string, expiresAt?: string (ISO 8601) }
export async function POST(req: NextRequest) {
  const supabase = await createClient();
  const {
    data: { user },
    error: authErr,
  } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!name || name.length > 100) {
    return NextResponse.json(
      { error: "name is required and must be 1–100 characters" },
      { status: 400 },
    );
  }

  const expiresAt = body.expiresAt ?? null;
  if (expiresAt !== null) {
    if (typeof expiresAt !== "string" || isNaN(Date.parse(expiresAt as string))) {
      return NextResponse.json({ error: "expiresAt must be a valid ISO 8601 date" }, { status: 400 });
    }
    if (new Date(expiresAt as string) <= new Date()) {
      return NextResponse.json({ error: "expiresAt must be in the future" }, { status: 400 });
    }
  }

  // Enforce per-user active key limit
  const { count, error: countErr } = await supabase
    .schema("swingtrader")
    .from("user_api_keys")
    .select("id", { count: "exact", head: true })
    .eq("user_id", user.id)
    .is("revoked_at", null);

  if (countErr) return NextResponse.json({ error: "Failed to create key" }, { status: 500 });
  if ((count ?? 0) >= MAX_KEYS_PER_USER) {
    return NextResponse.json(
      { error: `Maximum ${MAX_KEYS_PER_USER} active keys per account` },
      { status: 422 },
    );
  }

  const { key, displayPrefix, hash } = generateApiKey();

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_api_keys")
    .insert({
      user_id: user.id,
      name,
      key_hash: hash,
      key_prefix: displayPrefix,
      scopes: ["news:read"],
      expires_at: expiresAt ?? null,
    })
    .select("id, name, key_prefix, scopes, created_at, expires_at")
    .single();

  if (error) return NextResponse.json({ error: "Failed to create key" }, { status: 500 });

  // key is returned once and never stored — the client must copy it now
  return NextResponse.json({ ...data, key }, { status: 201 });
}

// ── DELETE /api/user/api-keys?id=<uuid> ──────────────────────────────────────
// Revoke a key (soft-delete via revoked_at). Ownership enforced via .eq("user_id").
export async function DELETE(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id") ?? "";
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
    return NextResponse.json({ error: "Valid key id required" }, { status: 400 });
  }

  const supabase = await createClient();
  const {
    data: { user },
    error: authErr,
  } = await supabase.auth.getUser();
  if (authErr || !user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_api_keys")
    .update({ revoked_at: new Date().toISOString() })
    .eq("id", id)
    .eq("user_id", user.id)   // ownership check — prevents revoking other users' keys
    .is("revoked_at", null);  // idempotency guard

  if (error) return NextResponse.json({ error: "Failed to revoke key" }, { status: 500 });
  return NextResponse.json({ ok: true });
}
