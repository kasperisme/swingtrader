export type DocPagePreview = {
  _id: string;
  title: string;
  slug: string;
  section: string | null;
  order: number | null;
  description: string;
};

export type DocPage = DocPagePreview & {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  cavemanBody?: any[];
};

export type BlogPostPreview = {
  _id: string;
  title: string;
  slug: string;
  excerpt: string;
  publishedAt: string;
  authorName: string | null;
  readingTimeMinutes: number | null;
};

export type BlogPost = BlogPostPreview & {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  cavemanBody?: any[];
};
