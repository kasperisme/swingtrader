/**
 * IndexedDB cache for global chart view state (zoom level, price pan).
 * Shared across all tickers — restores the user's preferred zoom and pan on every load.
 * Reads happen in parallel with the OHLC fetch; writes are fire-and-forget / debounced.
 */

const DB_NAME = "swingtrader-charts";
const STORE = "chart-views";
const DB_VERSION = 1;
const GLOBAL_KEY = "global";

export interface ChartViewState {
  viewportBars: number;
  priceOffset: number;
  storedAt: number;
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

export async function readChartViewCache(): Promise<ChartViewState | null> {
  try {
    const db = await openDb();
    const entry = await new Promise<ChartViewState | undefined>((resolve) => {
      const tx = db.transaction(STORE, "readonly");
      const r = tx.objectStore(STORE).get(GLOBAL_KEY);
      r.onsuccess = () => resolve(r.result as ChartViewState | undefined);
      r.onerror = () => resolve(undefined);
    });
    db.close();
    return entry ?? null;
  } catch {
    return null;
  }
}

/** Fire-and-forget write. */
export function putChartViewCache(state: Omit<ChartViewState, "storedAt">): void {
  void (async () => {
    try {
      const db = await openDb();
      const entry: ChartViewState = { ...state, storedAt: Date.now() };
      await new Promise<void>((resolve) => {
        const tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(entry, GLOBAL_KEY);
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
