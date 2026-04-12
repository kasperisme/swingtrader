export type ArticleShape = {
  title: string;
  url: string | null;
  slug: string | null;
  source: string | null;
  created_at: string;
} | null;

export type ImpactHeadJson = {
  id: number;
  article_id: number;
  article: ArticleShape;
  cluster: string;
  scores: unknown;
  reasoning: unknown;
  confidence: number;
  model: string;
  created_at: string;
};

const FIELD_KEYS = [
  "id",
  "article_id",
  "article",
  "cluster",
  "scores",
  "reasoning",
  "confidence",
  "model",
  "created_at",
] as const;

export const IMPACT_HEAD_FIELD_SET: ReadonlySet<string> = new Set(FIELD_KEYS);

export function shapeImpactHeadRow(row: {
  id: number;
  article_id: number;
  cluster: string;
  scores_json: unknown;
  reasoning_json: unknown;
  confidence: number;
  model: string;
  created_at: string;
  news_articles: ArticleShape;
}): ImpactHeadJson {
  return {
    id: row.id,
    article_id: row.article_id,
    article: row.news_articles,
    cluster: row.cluster,
    scores: row.scores_json,
    reasoning: row.reasoning_json,
    confidence: row.confidence,
    model: row.model,
    created_at: row.created_at,
  };
}

export function pickImpactHeadFields(
  row: ImpactHeadJson,
  fields: string[] | null,
): Record<string, unknown> {
  if (fields === null) {
    return { ...row };
  }
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    out[f] = row[f as keyof ImpactHeadJson];
  }
  return out;
}
