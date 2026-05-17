import { createHash } from "node:crypto";
import { InferenceClient } from "@huggingface/inference";

export const EMBED_MODEL = "mixedbread-ai/mxbai-embed-large-v1";

const TTL_MS = 24 * 60 * 60 * 1000;
const MAX_ENTRIES = 500;
const MAX_QUERY_CHARS = 500;
const WARMUP_INPUT = "warmup";

type CacheEntry = { embedding: number[]; expiresAt: number };

// Module-scoped in-memory LRU. Persists across requests within the same
// Node instance. Lambdas reset between cold starts; that's fine — even
// per-instance reuse kills the HF call on retries and follow-ups in the
// same session.
const cache = new Map<string, CacheEntry>();

let _client: InferenceClient | null = null;
function client(): InferenceClient {
  if (!_client) _client = new InferenceClient(process.env.HF_TOKEN!);
  return _client;
}

function normalize(query: string): string {
  return query.trim().toLowerCase().replace(/\s+/g, " ").slice(0, MAX_QUERY_CHARS);
}

function cacheKey(normalized: string): string {
  return createHash("sha256").update(`${EMBED_MODEL}:${normalized}`).digest("hex");
}

function lruGet(key: string): number[] | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (entry.expiresAt < Date.now()) {
    cache.delete(key);
    return null;
  }
  cache.delete(key);
  cache.set(key, entry);
  return entry.embedding;
}

function lruSet(key: string, embedding: number[]): void {
  if (cache.size >= MAX_ENTRIES) {
    const first = cache.keys().next().value;
    if (first !== undefined) cache.delete(first);
  }
  cache.set(key, { embedding, expiresAt: Date.now() + TTL_MS });
}

async function callHf(input: string): Promise<number[] | null> {
  const result = (await client().featureExtraction({
    model: EMBED_MODEL,
    inputs: input,
    provider: "hf-inference",
  })) as number[] | number[][];

  // Most models return a flat vector for a single string. Defensive flatten
  // for models that return [[...]].
  const vec = Array.isArray(result) && Array.isArray(result[0])
    ? (result[0] as number[])
    : (result as number[]);

  if (!Array.isArray(vec) || vec.length === 0 || typeof vec[0] !== "number") {
    return null;
  }
  return vec;
}

export async function embedQuery(query: string): Promise<number[] | null> {
  const norm = normalize(query);
  if (!norm) return null;

  const key = cacheKey(norm);
  const cached = lruGet(key);
  if (cached) return cached;

  const vec = await callHf(norm);
  if (vec) lruSet(key, vec);
  return vec;
}

// Bypasses the cache so each call actually round-trips HF and keeps the
// inference pod warm. Used by the page-load warmup endpoint.
export async function warmEmbedding(): Promise<void> {
  await callHf(WARMUP_INPUT);
}

export function embeddingCacheStats(): { size: number; max: number } {
  return { size: cache.size, max: MAX_ENTRIES };
}
