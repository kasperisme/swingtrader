const DEFAULT_PAGE_SIZE = 1000;

/**
 * Pages through a Supabase query until a short page is returned.
 *
 * PostgREST applies a default row cap (~1000), so unbounded `.select()` calls
 * silently truncate. Use this helper any time you need the full result set.
 */
export async function fetchAllPaged<Row>(
  query: (from: number, to: number) => PromiseLike<{
    data: Row[] | null;
    error: { message: string } | null;
  }>,
  pageSize: number = DEFAULT_PAGE_SIZE,
): Promise<{ data: Row[]; error: string | null }> {
  const out: Row[] = [];
  let from = 0;
  while (true) {
    const to = from + pageSize - 1;
    const { data, error } = await query(from, to);
    if (error) return { data: out, error: error.message };
    const rows = data ?? [];
    out.push(...rows);
    if (rows.length < pageSize) break;
    from += pageSize;
  }
  return { data: out, error: null };
}
