import {UserIcon} from '@sanity/icons'
import {defineArrayMember, defineField, defineType} from 'sanity'

/**
 * A famous trader or investor.
 *
 * The reference layer behind the Arena: each competing agent implements one of
 * these people's publicly-known approaches, and its page links here rather than
 * off to Wikipedia. `arenaAgentSlug` is the join — a soft reference by slug
 * because the agents live in Supabase, not Sanity.
 *
 * `body` / `cavemanBody` follow the same contract as posts and docs: always
 * write both.
 */
export const traderType = defineType({
  name: 'trader',
  title: 'Trader',
  type: 'document',
  icon: UserIcon,
  groups: [
    {name: 'identity', title: 'Identity', default: true},
    {name: 'approach', title: 'Approach'},
    {name: 'content', title: 'Biography'},
  ],
  fields: [
    defineField({
      name: 'name',
      title: 'Name',
      type: 'string',
      group: 'identity',
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'slug',
      title: 'Slug',
      type: 'slug',
      group: 'identity',
      options: {source: 'name'},
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'knownFor',
      title: 'Known for',
      type: 'string',
      group: 'identity',
      description: 'One line, shown on the directory card. e.g. "The Big Short"',
      validation: (Rule) => Rule.max(120),
    }),
    defineField({
      name: 'lifespan',
      title: 'Years',
      type: 'string',
      group: 'identity',
      description: 'e.g. "b. 1930" or "1930–2024"',
    }),
    defineField({
      name: 'nationality',
      title: 'Nationality',
      type: 'string',
      group: 'identity',
    }),
    defineField({
      name: 'image',
      title: 'Portrait',
      type: 'image',
      group: 'identity',
      options: {hotspot: true},
      fields: [defineField({name: 'alt', title: 'Alt text', type: 'string'})],
    }),
    defineField({
      name: 'order',
      title: 'Sort order',
      type: 'number',
      group: 'identity',
      initialValue: 0,
      description: 'Lower appears first on the directory',
    }),

    defineField({
      name: 'style',
      title: 'Style',
      type: 'string',
      group: 'approach',
      description:
        'The approach in a phrase, used as the directory subtitle. e.g. "Value investing"',
    }),
    defineField({
      name: 'tags',
      title: 'Tags',
      type: 'array',
      group: 'approach',
      of: [defineArrayMember({type: 'string'})],
      options: {
        layout: 'tags',
        list: [
          {title: 'Value', value: 'value'},
          {title: 'Growth', value: 'growth'},
          {title: 'Momentum', value: 'momentum'},
          {title: 'Quant', value: 'quant'},
          {title: 'Macro', value: 'macro'},
          {title: 'Contrarian', value: 'contrarian'},
          {title: 'Index', value: 'index'},
          {title: 'Technical', value: 'technical'},
          {title: 'News-driven', value: 'news'},
          {title: 'Social arbitrage', value: 'social'},
          {title: 'Academic', value: 'academic'},
        ],
      },
    }),
    defineField({
      name: 'keyIdeas',
      title: 'Key ideas',
      type: 'array',
      group: 'approach',
      description: 'The two to five things this person is actually worth reading for',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({name: 'title', title: 'Idea', type: 'string'}),
            defineField({name: 'text', title: 'Explanation', type: 'text', rows: 3}),
          ],
          preview: {select: {title: 'title', subtitle: 'text'}},
        }),
      ],
    }),
    defineField({
      name: 'books',
      title: 'Books',
      type: 'array',
      group: 'approach',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({name: 'title', title: 'Title', type: 'string'}),
            defineField({name: 'year', title: 'Year', type: 'number'}),
          ],
          preview: {select: {title: 'title', subtitle: 'year'}},
        }),
      ],
    }),
    defineField({
      name: 'links',
      title: 'External links',
      type: 'array',
      group: 'approach',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({name: 'label', title: 'Label', type: 'string'}),
            defineField({
              name: 'url',
              title: 'URL',
              type: 'url',
              validation: (Rule) => Rule.uri({scheme: ['http', 'https']}),
            }),
          ],
          preview: {select: {title: 'label', subtitle: 'url'}},
        }),
      ],
    }),

    // The join back to the Arena. A slug rather than a reference, because the
    // agents are rows in Supabase — Sanity has no document to point at.
    defineField({
      name: 'arenaAgentSlug',
      title: 'Arena agent slug',
      type: 'string',
      group: 'approach',
      description:
        'The /arena agent that implements this approach, e.g. "barren-wuffett". Links the two pages together in both directions.',
    }),

    defineField({
      name: 'summary',
      title: 'Summary',
      type: 'text',
      rows: 3,
      group: 'content',
      description: 'Shown on the directory and used as the meta description',
    }),
    defineField({
      name: 'body',
      title: 'Biography',
      type: 'blockContent',
      group: 'content',
    }),
    defineField({
      name: 'cavemanBody',
      title: 'Caveman Biography',
      type: 'blockContent',
      group: 'content',
      description: 'Same substance, ~70% fewer words. Always fill this in.',
    }),
  ],
  orderings: [
    {
      title: 'Sort order',
      name: 'orderAsc',
      by: [
        {field: 'order', direction: 'asc'},
        {field: 'name', direction: 'asc'},
      ],
    },
  ],
  preview: {
    select: {title: 'name', subtitle: 'style', media: 'image'},
  },
})
