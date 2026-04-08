export const blogPostPreviewsQuery = `
  *[_type == "post"] | order(publishedAt desc) {
    _id,
    title,
    "slug": slug.current,
    "excerpt": coalesce(excerpt, ""),
    publishedAt,
    "authorName": author->name
  }
`;

export const blogPostBySlugQuery = `
  *[_type == "post" && slug.current == $slug][0] {
    _id,
    title,
    "slug": slug.current,
    "excerpt": coalesce(excerpt, ""),
    publishedAt,
    "authorName": author->name,
    "bodyText": coalesce(pt::text(body), "")
  }
`;
