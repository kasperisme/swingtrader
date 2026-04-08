/**
 * IndexedDB cache for FMP stock quotes.
 * TTL: 5 minutes (quotes are live intraday data).
 */

const DB_NAME = "swingtrader-cache";
const STORE = "quotes";
const VERSION = 1;
const TTL_MS = 5 * 60 * 1000; // 5 minutes

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, VERSION);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function isFresh(entry: CacheEntry<unknown>): boolean {
  return Date.now() - entry.timestamp < TTL_MS;
}

export async function getCachedQuote<T>(symbol: string): Promise<T | null> {
  try {
    const db = await openDb();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).get(symbol);
      req.onsuccess = () => {
        const entry = req.result as CacheEntry<T> | undefined;
        resolve(entry && isFresh(entry) ? entry.data : null);
      };
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

export async function setCachedQuote<T>(symbol: string, data: T): Promise<void> {
  try {
    const db = await openDb();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put({ data, timestamp: Date.now() } satisfies CacheEntry<T>, symbol);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch {
    // cache write failure is non-fatal
  }
}

export async function getCachedQuotes<T>(symbols: string[]): Promise<Record<string, T>> {
  try {
    const db = await openDb();
    return new Promise((resolve) => {
      const result: Record<string, T> = {};
      const tx = db.transaction(STORE, "readonly");
      const store = tx.objectStore(STORE);
      let pending = symbols.length;
      if (pending === 0) { resolve(result); return; }
      for (const sym of symbols) {
        const req = store.get(sym);
        req.onsuccess = () => {
          const entry = req.result as CacheEntry<T> | undefined;
          if (entry && isFresh(entry)) result[sym] = entry.data;
          if (--pending === 0) resolve(result);
        };
        req.onerror = () => { if (--pending === 0) resolve(result); };
      }
    });
  } catch {
    return {};
  }
}

export async function setCachedQuotes<T>(entries: Record<string, T>): Promise<void> {
  try {
    const db = await openDb();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE, "readwrite");
      const store = tx.objectStore(STORE);
      for (const [sym, data] of Object.entries(entries)) {
        store.put({ data, timestamp: Date.now() } satisfies CacheEntry<T>, sym);
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch {
    // non-fatal
  }
}
