export const docPagePreviewsQuery = `
  *[_type == "docPage"] | order(section asc, order asc, title asc) {
    _id,
    title,
    "slug": slug.current,
    section,
    order,
    "description": coalesce(description, "")
  }
`;

export const docPageBySlugQuery = `
  *[_type == "docPage" && slug.current == $slug][0] {
    _id,
    title,
    "slug": slug.current,
    section,
    order,
    "description": coalesce(description, ""),
    body
  }
`;

export const docPageSlugListQuery = `
  *[_type == "docPage" && defined(slug.current)] {
    "slug": slug.current
  }
`;

export const blogPostSlugListQuery = `
  *[_type == "post" && defined(slug.current)] {
    "slug": slug.current
  }
`;

export const blogPostPreviewsQuery = `
  *[_type == "post"] | order(publishedAt desc) {
    _id,
    title,
    "slug": slug.current,
    "excerpt": coalesce(excerpt, ""),
    publishedAt,
    "authorName": author->name,
    "readingTimeMinutes": round(length(pt::text(body)) / 5 / 200)
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
    body,
    "readingTimeMinutes": round(length(pt::text(body)) / 5 / 200)
  }
`;
