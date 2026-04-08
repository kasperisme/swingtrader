export type BlogPostPreview = {
  _id: string;
  title: string;
  slug: string;
  excerpt: string;
  publishedAt: string;
  authorName: string | null;
};

export type BlogPost = BlogPostPreview & {
  bodyText: string;
};
