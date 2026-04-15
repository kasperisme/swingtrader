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

export type NewsPublisher = {
  _id: string;
  name: string;
  slug: string;
  iconUrl: string | null;
  website: string | null;
};

export type LegalPage = {
  _id: string;
  title: string;
  slug: string;
  description: string;
  updatedAt: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any[];
};

export type ChangelogEntry = {
  _id: string;
  title: string;
  date: string;
  tags: string[] | null;
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
