/** Article row for News Trends + screenings (server + client). */
export interface ArticleImpact {
  published_at: string;
  impact_json: Record<string, number>;
  /** Mean confidence across `news_impact_heads` rows for this article; drives weighted period averages. */
  confidence?: number | null;
  id?: number | null;
  title?: string | null;
  url?: string | null;
  source?: string | null;
  slug?: string | null;
  image_url?: string | null;
  created_at?: string | null;
}
