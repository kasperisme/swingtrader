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
    body,
    cavemanBody
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

export const newsPublishersQuery = `
  *[_type == "newsPublisher"] | order(name asc) {
    _id,
    name,
    "slug": slug.current,
    "iconUrl": icon.asset->url,
    website
  }
`;

export const legalPageBySlugQuery = `
  *[_type == "legalPage" && slug.current == $slug][0] {
    _id,
    title,
    "slug": slug.current,
    "description": coalesce(description, ""),
    updatedAt,
    body
  }
`;

export const changelogEntriesQuery = `
  *[_type == "changelogEntry"] | order(date desc) {
    _id,
    title,
    date,
    tags,
    body,
    cavemanBody
  }
`;

export const landingPageQuery = `
  *[_type == "landingPage"][0] {
    heroBadgeText,
    heroHeadlinePart1,
    heroHeadlineHighlight,
    heroDescription,
    heroPrimaryCtaLabel,
    heroSecondaryCtaLabel,
    benefitsSectionLabel,
    benefitsHeading,
    benefitsSubheading,
    benefitCards[] { title, description, iconName },
    howItWorksSectionLabel,
    howItWorksHeading,
    howItWorksSteps[] { label, detail },
    productValuesSectionLabel,
    productValuesHeading,
    productValueItems[] { title, description, iconName },
    trustSectionLabel,
    trustHeading,
    trustItems[] { title, description, iconName },
    pricingSectionLabel,
    pricingHeading,
    pricingSubheading,
    pricingFounderNote,
    pricingPlans[] { name, price, billingNote, annualLabel, phase2Price, phase2AnnualLabel, phase3Price, phase3AnnualLabel, description, features, ctaLabel, badge, isHighlighted, spotLimit, isCurrentPhase },
    offerSectionLabel,
    offerHeading,
    offerSubheading,
    offerBadge,
    offerOriginalPrice,
    offerDiscountedPrice,
    offerSavingsText,
    offerDescription,
    offerFeatures,
    offerCtaLabel,
    offerUrgencyText,
    offerExpiryText,
    ctaSectionLabel,
    ctaHeading,
    ctaDescription,
    ctaFootnote,
    tickerThemes
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
    cavemanBody,
    "readingTimeMinutes": round(length(pt::text(body)) / 5 / 200)
  }
`;

// ── Traders ─────────────────────────────────────────────────────────────────
// The reference layer behind /arena: the investors whose approaches the
// competing agents implement.

export const traderPreviewsQuery = `
  *[_type == "trader" && defined(slug.current)] | order(order asc, name asc) {
    "slug": slug.current,
    name,
    knownFor,
    style,
    lifespan,
    nationality,
    tags,
    summary,
    arenaAgentSlug,
    "imageUrl": image.asset->url
  }
`;

export const traderBySlugQuery = `
  *[_type == "trader" && slug.current == $slug][0] {
    "slug": slug.current,
    name,
    knownFor,
    style,
    lifespan,
    nationality,
    tags,
    summary,
    arenaAgentSlug,
    keyIdeas[]{title, text},
    books[]{title, year},
    links[]{label, url},
    body,
    cavemanBody,
    "imageUrl": image.asset->url
  }
`;

export const traderSlugListQuery = `
  *[_type == "trader" && defined(slug.current)] {
    "slug": slug.current
  }
`;
