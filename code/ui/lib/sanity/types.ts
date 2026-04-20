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

export type LandingPricingPlan = {
  name: string;
  price: string | null;
  billingNote: string | null;
  annualLabel: string | null;
  phase2Price: string | null;
  phase2AnnualLabel: string | null;
  phase3Price: string | null;
  phase3AnnualLabel: string | null;
  description: string | null;
  features: string[] | null;
  ctaLabel: string | null;
  badge: string | null;
  isHighlighted: boolean | null;
  spotLimit: number | null;
  isCurrentPhase: boolean | null;
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
  pricingSectionLabel: string | null;
  pricingHeading: string | null;
  pricingSubheading: string | null;
  pricingFounderNote: string | null;
  pricingPlans: LandingPricingPlan[] | null;
  offerSectionLabel: string | null;
  offerHeading: string | null;
  offerSubheading: string | null;
  offerBadge: string | null;
  offerOriginalPrice: string | null;
  offerDiscountedPrice: string | null;
  offerSavingsText: string | null;
  offerDescription: string | null;
  offerFeatures: string[] | null;
  offerCtaLabel: string | null;
  offerUrgencyText: string | null;
  offerExpiryText: string | null;
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
