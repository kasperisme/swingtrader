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

export type LandingCardItem = {
  title: string;
  description: string;
  iconName: string | null;
};

export type LandingStep = {
  label: string;
  detail: string;
};

export type LandingPage = {
  heroBadgeText: string | null;
  heroHeadlinePart1: string | null;
  heroHeadlineHighlight: string | null;
  heroDescription: string | null;
  heroPrimaryCtaLabel: string | null;
  heroSecondaryCtaLabel: string | null;
  benefitsSectionLabel: string | null;
  benefitsHeading: string | null;
  benefitsSubheading: string | null;
  benefitCards: LandingCardItem[] | null;
  howItWorksSectionLabel: string | null;
  howItWorksHeading: string | null;
  howItWorksSteps: LandingStep[] | null;
  productValuesSectionLabel: string | null;
  productValuesHeading: string | null;
  productValueItems: LandingCardItem[] | null;
  trustSectionLabel: string | null;
  trustHeading: string | null;
  trustItems: LandingCardItem[] | null;
  ctaSectionLabel: string | null;
  ctaHeading: string | null;
  ctaDescription: string | null;
  ctaFootnote: string | null;
  tickerThemes: string[] | null;
};

export type BlogPost = BlogPostPreview & {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  body: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  cavemanBody?: any[];
};
