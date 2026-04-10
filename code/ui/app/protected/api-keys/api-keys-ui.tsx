"use client";

import { useState } from "react";
import { Copy, Check, Trash2, Plus, KeyRound, RefreshCw } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

// ── Small helpers ─────────────────────────────────────────────────────────────

function fmt(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function isExpired(key: ApiKey) {
  return key.expires_at !== null && new Date(key.expires_at) <= new Date();
}

function keyStatus(key: ApiKey): "active" | "revoked" | "expired" {
  if (key.revoked_at) return "revoked";
  if (isExpired(key)) return "expired";
  return "active";
}

// ── CopyButton ────────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        });
      }}
      className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs bg-muted hover:bg-muted/80 transition-colors"
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

// ── NewKeyDialog ──────────────────────────────────────────────────────────────

function NewKeyDialog({
  onCreated,
  onClose,
}: {
  onCreated: (key: ApiKey & { key: string }) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/user/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, expiresAt: expiresAt || null }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "Failed to create key");
      onCreated(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-lg border bg-background p-6 shadow-xl">
        <h2 className="text-lg font-semibold mb-4">Create API Key</h2>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium">Name</label>
            <input
              type="text"
              maxLength={100}
              placeholder="e.g. production, CI pipeline"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="rounded border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium">
              Expiry <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <input
              type="date"
              value={expiresAt}
              min={new Date(Date.now() + 86_400_000).toISOString().slice(0, 10)}
              onChange={(e) => setExpiresAt(e.target.value)}
              className="rounded border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <div className="flex justify-end gap-2 mt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded px-4 py-2 text-sm border hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded px-4 py-2 text-sm bg-foreground text-background hover:opacity-90 disabled:opacity-50 transition-opacity flex items-center gap-2"
            >
              {loading && <RefreshCw className="h-3 w-3 animate-spin" />}
              Create key
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── NewKeyReveal ──────────────────────────────────────────────────────────────

function NewKeyReveal({ rawKey, onClose }: { rawKey: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-lg border bg-background p-6 shadow-xl">
        <h2 className="text-lg font-semibold mb-1">Save your API key</h2>
        <p className="text-sm text-muted-foreground mb-4">
          This is the only time the full key will be shown. Store it somewhere safe — it{" "}
          <strong>cannot</strong> be retrieved again.
        </p>
        <div className="flex items-center gap-2 rounded border bg-muted px-3 py-2 font-mono text-sm break-all">
          <span className="flex-1 select-all">{rawKey}</span>
          <CopyButton text={rawKey} />
        </div>
        <button
          onClick={onClose}
          className="mt-4 w-full rounded px-4 py-2 text-sm bg-foreground text-background hover:opacity-90 transition-opacity"
        >
          I&apos;ve saved it — close
        </button>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function ApiKeysUI({ initialKeys }: { initialKeys: ApiKey[] }) {
  const [keys, setKeys] = useState<ApiKey[]>(initialKeys);
  const [showCreate, setShowCreate] = useState(false);
  const [newRawKey, setNewRawKey] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeConfirm, setRevokeConfirm] = useState<string | null>(null);

  function handleCreated(result: ApiKey & { key: string }) {
    const { key: rawKey, ...meta } = result;
    setKeys((prev) => [meta, ...prev]);
    setShowCreate(false);
    setNewRawKey(rawKey);
  }

  async function handleRevoke(id: string) {
    setRevoking(id);
    try {
      const res = await fetch(`/api/user/api-keys?id=${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setKeys((prev) =>
        prev.map((k) =>
          k.id === id ? { ...k, revoked_at: new Date().toISOString() } : k,
        ),
      );
    } finally {
      setRevoking(null);
      setRevokeConfirm(null);
    }
  }

  const activeCount = keys.filter((k) => keyStatus(k) === "active").length;

  return (
    <>
      {showCreate && (
        <NewKeyDialog onCreated={handleCreated} onClose={() => setShowCreate(false)} />
      )}
      {newRawKey && (
        <NewKeyReveal rawKey={newRawKey} onClose={() => setNewRawKey(null)} />
      )}

      {/* Header row */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {activeCount} active key{activeCount !== 1 ? "s" : ""} · max 10
        </p>
        <button
          onClick={() => setShowCreate(true)}
          disabled={activeCount >= 10}
          className="inline-flex items-center gap-2 rounded px-3 py-2 text-sm bg-foreground text-background hover:opacity-90 disabled:opacity-40 transition-opacity"
        >
          <Plus className="h-4 w-4" />
          New API key
        </button>
      </div>

      {/* Key list */}
      {keys.length === 0 ? (
        <div className="mt-8 flex flex-col items-center gap-3 text-muted-foreground">
          <KeyRound className="h-10 w-10 opacity-30" />
          <p className="text-sm">No API keys yet. Create one to get started.</p>
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {keys.map((key) => {
            const status = keyStatus(key);
            return (
              <div
                key={key.id}
                className={`rounded-lg border p-4 flex flex-col sm:flex-row sm:items-start gap-3 ${
                  status !== "active" ? "opacity-50" : ""
                }`}
              >
                {/* Key info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm">{key.name}</span>
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                        status === "active"
                          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                          : status === "revoked"
                          ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                          : "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
                      }`}
                    >
                      {status}
                    </span>
                    {key.scopes.map((s) => (
                      <span
                        key={s}
                        className="text-xs px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                  <div className="mt-1 font-mono text-xs text-muted-foreground">
                    {key.key_prefix}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span>Created {fmt(key.created_at)}</span>
                    {key.last_used_at && <span>Last used {fmt(key.last_used_at)}</span>}
                    {key.expires_at && <span>Expires {fmt(key.expires_at)}</span>}
                    {key.revoked_at && <span>Revoked {fmt(key.revoked_at)}</span>}
                  </div>
                </div>

                {/* Revoke */}
                {status === "active" && (
                  <div className="flex-shrink-0">
                    {revokeConfirm === key.id ? (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">Revoke?</span>
                        <button
                          onClick={() => handleRevoke(key.id)}
                          disabled={revoking === key.id}
                          className="text-xs text-red-600 hover:underline disabled:opacity-50"
                        >
                          {revoking === key.id ? "Revoking…" : "Yes, revoke"}
                        </button>
                        <button
                          onClick={() => setRevokeConfirm(null)}
                          className="text-xs text-muted-foreground hover:underline"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setRevokeConfirm(key.id)}
                        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-red-600 transition-colors"
                        title="Revoke key"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Revoke
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
