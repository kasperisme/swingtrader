import {HomeIcon} from '@sanity/icons'
import {defineArrayMember, defineField, defineType} from 'sanity'

const ICON_OPTIONS = [
  {title: 'Newspaper', value: 'Newspaper'},
  {title: 'Target', value: 'Target'},
  {title: 'Workflow', value: 'Workflow'},
  {title: 'BarChart3', value: 'BarChart3'},
  {title: 'Compass', value: 'Compass'},
  {title: 'Filter', value: 'Filter'},
  {title: 'Shield', value: 'Shield'},
  {title: 'TrendingUp', value: 'TrendingUp'},
  {title: 'Zap', value: 'Zap'},
]

const cardItemFields = [
  defineField({name: 'title', title: 'Title', type: 'string', validation: (R) => R.required()}),
  defineField({name: 'description', title: 'Description', type: 'text', rows: 3}),
  defineField({
    name: 'iconName',
    title: 'Icon',
    type: 'string',
    options: {list: ICON_OPTIONS},
  }),
]

export const landingPageType = defineType({
  name: 'landingPage',
  title: 'Landing Page',
  type: 'document',
  icon: HomeIcon,
  fields: [
    // ── HERO ──────────────────────────────────────────────────────────
    defineField({
      name: 'heroBadgeText',
      title: 'Hero Badge Text',
      type: 'string',
      group: 'hero',
      initialValue: 'For retail & self-directed investors',
    }),
    defineField({
      name: 'heroHeadlinePart1',
      title: 'Hero Headline (first part)',
      type: 'string',
      group: 'hero',
      description: 'Plain text before the highlighted span',
      initialValue: 'The news moves stocks.',
    }),
    defineField({
      name: 'heroHeadlineHighlight',
      title: 'Hero Headline Highlight',
      type: 'string',
      group: 'hero',
      description: 'Amber-colored portion of the headline',
      initialValue: 'Know which ones.',
    }),
    defineField({
      name: 'heroDescription',
      title: 'Hero Description',
      type: 'text',
      rows: 3,
      group: 'hero',
    }),
    defineField({
      name: 'heroPrimaryCtaLabel',
      title: 'Primary CTA Label',
      type: 'string',
      group: 'hero',
      initialValue: 'Get Early Access',
    }),
    defineField({
      name: 'heroSecondaryCtaLabel',
      title: 'Secondary CTA Label',
      type: 'string',
      group: 'hero',
      initialValue: 'See How It Works',
    }),

    // ── BENTO FEATURES ────────────────────────────────────────────────
    defineField({
      name: 'benefitsSectionLabel',
      title: 'Section Label',
      type: 'string',
      group: 'benefits',
      initialValue: 'Why it works',
    }),
    defineField({
      name: 'benefitsHeading',
      title: 'Heading',
      type: 'string',
      group: 'benefits',
      initialValue: 'Built for how retail investors actually research',
    }),
    defineField({
      name: 'benefitsSubheading',
      title: 'Subheading',
      type: 'text',
      rows: 2,
      group: 'benefits',
    }),
    defineField({
      name: 'benefitCards',
      title: 'Benefit Cards',
      type: 'array',
      group: 'benefits',
      of: [defineArrayMember({type: 'object', fields: cardItemFields})],
      validation: (R) => R.max(3),
    }),

    // ── HOW IT WORKS ──────────────────────────────────────────────────
    defineField({
      name: 'howItWorksSectionLabel',
      title: 'Section Label',
      type: 'string',
      group: 'howItWorks',
      initialValue: 'How it works',
    }),
    defineField({
      name: 'howItWorksHeading',
      title: 'Heading',
      type: 'string',
      group: 'howItWorks',
      initialValue: 'Three steps, no terminal',
    }),
    defineField({
      name: 'howItWorksSteps',
      title: 'Steps',
      type: 'array',
      group: 'howItWorks',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({name: 'label', title: 'Step Label', type: 'string', validation: (R) => R.required()}),
            defineField({name: 'detail', title: 'Detail', type: 'text', rows: 3}),
          ],
        }),
      ],
      validation: (R) => R.max(5),
    }),

    // ── PRODUCT VALUES ────────────────────────────────────────────────
    defineField({
      name: 'productValuesSectionLabel',
      title: 'Section Label',
      type: 'string',
      group: 'productValues',
      initialValue: 'What you get',
    }),
    defineField({
      name: 'productValuesHeading',
      title: 'Heading',
      type: 'string',
      group: 'productValues',
      initialValue: 'Signal, not noise',
    }),
    defineField({
      name: 'productValueItems',
      title: 'Value Items',
      type: 'array',
      group: 'productValues',
      of: [defineArrayMember({type: 'object', fields: cardItemFields})],
      validation: (R) => R.max(6),
    }),

    // ── STRAIGHT ANSWERS / TRUST ──────────────────────────────────────
    defineField({
      name: 'trustSectionLabel',
      title: 'Section Label',
      type: 'string',
      group: 'trust',
      initialValue: 'Straight answers',
    }),
    defineField({
      name: 'trustHeading',
      title: 'Heading',
      type: 'string',
      group: 'trust',
      initialValue: 'Common questions',
    }),
    defineField({
      name: 'trustItems',
      title: 'Trust Items',
      type: 'array',
      group: 'trust',
      of: [defineArrayMember({type: 'object', fields: cardItemFields})],
      validation: (R) => R.max(6),
    }),

    // ── FINAL CTA ─────────────────────────────────────────────────────
    defineField({
      name: 'ctaSectionLabel',
      title: 'Section Label',
      type: 'string',
      group: 'cta',
      initialValue: 'Early access',
    }),
    defineField({
      name: 'ctaHeading',
      title: 'Heading',
      type: 'string',
      group: 'cta',
      initialValue: 'Smarter homework for your portfolio.',
    }),
    defineField({
      name: 'ctaDescription',
      title: 'Description',
      type: 'text',
      rows: 3,
      group: 'cta',
    }),
    defineField({
      name: 'ctaFootnote',
      title: 'Footnote',
      type: 'string',
      group: 'cta',
      initialValue: 'No credit card. No terminal subscription.',
    }),

    // ── PRICING ───────────────────────────────────────────────────────
    defineField({
      name: 'pricingSectionLabel',
      title: 'Section Label',
      type: 'string',
      group: 'pricing',
      initialValue: 'Pricing',
    }),
    defineField({
      name: 'pricingHeading',
      title: 'Heading',
      type: 'string',
      group: 'pricing',
      initialValue: 'Simple, transparent pricing',
    }),
    defineField({
      name: 'pricingSubheading',
      title: 'Subheading',
      type: 'text',
      rows: 2,
      group: 'pricing',
    }),
    defineField({
      name: 'pricingFounderNote',
      title: 'Founder Rate Note',
      type: 'string',
      group: 'pricing',
      description: 'Shown below the CTA on the current phase card',
      initialValue: 'Your price is locked for life. Cancel any time — but once you cancel, the founder rate is gone.',
    }),
    defineField({
      name: 'pricingPlans',
      title: 'Pricing Plans',
      type: 'array',
      group: 'pricing',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({name: 'name', title: 'Plan Name', type: 'string', validation: (R) => R.required()}),
            defineField({name: 'price', title: 'Price', type: 'string', description: 'e.g. "$19" or "Free"'}),
            defineField({name: 'billingNote', title: 'Billing Note', type: 'string', description: 'e.g. "per month" or "forever free"'}),
            defineField({name: 'description', title: 'Description', type: 'text', rows: 2}),
            defineField({
              name: 'features',
              title: 'Features',
              type: 'array',
              of: [defineArrayMember({type: 'string'})],
            }),
            defineField({name: 'ctaLabel', title: 'CTA Label', type: 'string', initialValue: 'Get Started'}),
            defineField({name: 'badge', title: 'Badge', type: 'string', description: 'e.g. "Most Popular" — leave blank for no badge'}),
            defineField({name: 'isHighlighted', title: 'Highlighted (featured plan)', type: 'boolean', initialValue: false}),
            defineField({name: 'spotLimit', title: 'Spot Limit', type: 'number', description: 'Max signups at this price. Leave blank for unlimited.'}),
            defineField({name: 'isCurrentPhase', title: 'Current Phase', type: 'boolean', initialValue: false, description: 'Mark the plan that is actively being sold right now'}),
          ],
          preview: {
            select: {title: 'name', subtitle: 'price'},
          },
        }),
      ],
      validation: (R) => R.max(4),
    }),

    // ── OFFER ─────────────────────────────────────────────────────────
    defineField({
      name: 'offerSectionLabel',
      title: 'Section Label',
      type: 'string',
      group: 'offer',
      initialValue: 'Limited-time offer',
    }),
    defineField({
      name: 'offerHeading',
      title: 'Heading',
      type: 'string',
      group: 'offer',
      initialValue: 'Lock in early-access pricing',
    }),
    defineField({
      name: 'offerSubheading',
      title: 'Subheading',
      type: 'text',
      rows: 2,
      group: 'offer',
    }),
    defineField({
      name: 'offerBadge',
      title: 'Badge Text',
      type: 'string',
      group: 'offer',
      description: 'e.g. "Early Bird" or "Founding Member"',
      initialValue: 'Early Bird',
    }),
    defineField({
      name: 'offerOriginalPrice',
      title: 'Original Price',
      type: 'string',
      group: 'offer',
      description: 'e.g. "$29/mo"',
    }),
    defineField({
      name: 'offerDiscountedPrice',
      title: 'Discounted Price',
      type: 'string',
      group: 'offer',
      description: 'e.g. "$9/mo"',
    }),
    defineField({
      name: 'offerSavingsText',
      title: 'Savings Text',
      type: 'string',
      group: 'offer',
      description: 'e.g. "Save 69%" or "60% off forever"',
    }),
    defineField({
      name: 'offerDescription',
      title: 'Description',
      type: 'text',
      rows: 3,
      group: 'offer',
    }),
    defineField({
      name: 'offerFeatures',
      title: 'Included Features',
      type: 'array',
      group: 'offer',
      of: [defineArrayMember({type: 'string'})],
    }),
    defineField({
      name: 'offerCtaLabel',
      title: 'CTA Label',
      type: 'string',
      group: 'offer',
      initialValue: 'Claim Early Access',
    }),
    defineField({
      name: 'offerUrgencyText',
      title: 'Urgency Text',
      type: 'string',
      group: 'offer',
      description: 'e.g. "Only 50 spots remaining"',
    }),
    defineField({
      name: 'offerExpiryText',
      title: 'Expiry Text',
      type: 'string',
      group: 'offer',
      description: 'e.g. "Offer ends April 30"',
    }),

    // ── TICKER THEMES ─────────────────────────────────────────────────
    defineField({
      name: 'tickerThemes',
      title: 'Ticker Themes',
      type: 'array',
      group: 'ticker',
      description: 'Scrolling ticker labels shown in the hero section',
      of: [defineArrayMember({type: 'string'})],
    }),
  ],

  groups: [
    {name: 'hero', title: 'Hero'},
    {name: 'benefits', title: 'Benefits'},
    {name: 'howItWorks', title: 'How It Works'},
    {name: 'productValues', title: 'Product Values'},
    {name: 'trust', title: 'Straight Answers'},
    {name: 'pricing', title: 'Pricing'},
    {name: 'offer', title: 'Offer'},
    {name: 'cta', title: 'Final CTA'},
    {name: 'ticker', title: 'Ticker'},
  ],

  preview: {
    prepare: () => ({title: 'Landing Page'}),
  },
})
