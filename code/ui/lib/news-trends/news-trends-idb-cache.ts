/**
 * IndexedDB cache for News Trends client payloads (fast revisit / filters).
 * Reads are optional hydration; writes are fire-and-forget after network success.
 * Bump `CACHE_SCHEMA` when API shape or lookback semantics change.
 */

import type { ArticleImpact } from "@/app/protected/news-trends/news-trends-types";
import type {
  ClusterTrendRow,
  DimensionTrendRow,
} from "@/app/protected/news-trends/news-trends-series";

const DB_NAME = "swingtrader-news-trends";
const STORE = "payloads";
const DB_VERSION = 1;

/** Keep aligned with `NEWS_TRENDS_LOOKBACK_DAYS` in `load-news-trends.ts`. */
export const NEWS_TRENDS_CACHE_LOOKBACK_DAYS = 400;
export const NEWS_TRENDS_CACHE_SCHEMA = 1;

export type NewsTrendsCacheKey =
  | "clusterDaily"
  | "articles"
  | "clusterHourly"
  | "dimensionDaily"
  | "dimensionHourly";

interface CacheEnvelope<T> {
  schema: number;
  lookbackDays: number;
  storedAt: number;
  payload: T;
}

const TTL_MS: Record<NewsTrendsCacheKey, number> = {
  clusterDaily: 24 * 60 * 60 * 1000,
  articles: 2 * 60 * 60 * 1000,
  clusterHourly: 24 * 60 * 60 * 1000,
  dimensionDaily: 24 * 60 * 60 * 1000,
  dimensionHourly: 24 * 60 * 60 * 1000,
};

function isFresh<T>(
  entry: CacheEnvelope<T> | null | undefined,
  key: NewsTrendsCacheKey,
): boolean {
  if (!entry) return false;
  if (entry.schema !== NEWS_TRENDS_CACHE_SCHEMA) return false;
  if (entry.lookbackDays !== NEWS_TRENDS_CACHE_LOOKBACK_DAYS) return false;
  return Date.now() - entry.storedAt < TTL_MS[key];
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Fire-and-forget persist (non-blocking). */
export function putNewsTrendsCache<T>(
  key: NewsTrendsCacheKey,
  payload: T,
): void {
  void (async () => {
    try {
      const db = await openDb();
      const envelope: CacheEnvelope<T> = {
        schema: NEWS_TRENDS_CACHE_SCHEMA,
        lookbackDays: NEWS_TRENDS_CACHE_LOOKBACK_DAYS,
        storedAt: Date.now(),
        payload,
      };
      await new Promise<void>((resolve) => {
        const tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(envelope, key);
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
        tx.onabort = () => resolve();
      });
      db.close();
    } catch {
      // non-fatal
    }
  })();
}

async function getEnvelope<T>(
  key: NewsTrendsCacheKey,
): Promise<CacheEnvelope<T> | null> {
  try {
    const db = await openDb();
    const entry = await new Promise<CacheEnvelope<T> | undefined>((resolve) => {
      const tx = db.transaction(STORE, "readonly");
      const r = tx.objectStore(STORE).get(key);
      r.onsuccess = () =>
        resolve(r.result != null ? (r.result as CacheEnvelope<T>) : undefined);
      r.onerror = () => resolve(undefined);
    });
    db.close();
    return entry ?? null;
  } catch {
    return null;
  }
}

export type NewsTrendsHydrationBundle = {
  articles: ArticleImpact[] | null;
  clusterHourly: ClusterTrendRow[] | null;
  dimensionDaily: DimensionTrendRow[] | null;
  dimensionHourly: DimensionTrendRow[] | null;
};

/** Single open + parallel reads; does not block first paint (caller runs in useEffect). */
export async function readNewsTrendsHydrationBundle(): Promise<NewsTrendsHydrationBundle> {
  const empty: NewsTrendsHydrationBundle = {
    articles: null,
    clusterHourly: null,
    dimensionDaily: null,
    dimensionHourly: null,
  };
  try {
    const db = await openDb();
    const keys: NewsTrendsCacheKey[] = [
      "articles",
      "clusterHourly",
      "dimensionDaily",
      "dimensionHourly",
    ];
    const out = { ...empty };
    await Promise.all(
      keys.map(
        (key) =>
          new Promise<void>((resolve) => {
            const tx = db.transaction(STORE, "readonly");
            const r = tx.objectStore(STORE).get(key);
            r.onsuccess = () => {
              const env = r.result as
                | CacheEnvelope<
                    | ArticleImpact[]
                    | ClusterTrendRow[]
                    | DimensionTrendRow[]
                  >
                | undefined;
              if (env && isFresh(env, key)) {
                if (key === "articles")
                  out.articles = env.payload as ArticleImpact[];
                else if (key === "clusterHourly")
                  out.clusterHourly = env.payload as ClusterTrendRow[];
                else if (key === "dimensionDaily")
                  out.dimensionDaily = env.payload as DimensionTrendRow[];
                else if (key === "dimensionHourly")
                  out.dimensionHourly = env.payload as DimensionTrendRow[];
              }
              resolve();
            };
            r.onerror = () => resolve();
          }),
      ),
    );
    db.close();
    return out;
  } catch {
    return empty;
  }
}
