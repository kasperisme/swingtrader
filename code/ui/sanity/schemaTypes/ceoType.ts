import {UserIcon} from '@sanity/icons'
import {defineArrayMember, defineField, defineType} from 'sanity'

/**
 * An editorial profile of a public-company CEO.
 *
 * OPTIONAL by design. Every CEO in the universe already has a page at
 * /ceos/<slug>, built from `swingtrader.company_ceos` (FMP: who, title, SEC
 * proxy pay, the leadership team). This document adds what data cannot — a
 * portrait we hold a licence for, and a biography — to the people worth
 * writing one for. `slug` is the join and must equal the directory's slug
 * exactly, which is the CEO's name as FMP lists it, honorifics dropped and
 * middle initials kept ("timothy-d-cook", not "tim-cook"). Copy it from the
 * page URL rather than guessing it.
 *
 * `body` / `cavemanBody` follow the same contract as posts, docs and traders:
 * always write both.
 */
export const ceoType = defineType({
  name: 'ceo',
  title: 'CEO',
  type: 'document',
  icon: UserIcon,
  fields: [
    defineField({
      name: 'name',
      title: 'Name',
      type: 'string',
      description: 'Display name, e.g. "Jensen Huang". Overrides the data name on the page.',
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'slug',
      title: 'Slug',
      type: 'slug',
      description:
        'Must match the /ceos/<slug> URL of the data page exactly (e.g. "timothy-d-cook" — copy it from the URL). '
        + 'A slug with no matching data page is never shown.',
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'knownFor',
      title: 'Known for',
      type: 'string',
      description: 'One line under the name. e.g. "Co-founded Nvidia in 1993"',
      validation: (Rule) => Rule.max(120),
    }),
    defineField({
      name: 'image',
      title: 'Portrait',
      type: 'image',
      options: {hotspot: true},
      description:
        'Only a portrait we hold a licence for — in practice a free-licensed Wikimedia '
        + 'Commons image. Fill credit + creditUrl for anything not public domain. No '
        + 'portrait renders the typographic mark, which is the designed default.',
      fields: [
        defineField({name: 'alt', title: 'Alt text', type: 'string'}),
        defineField({name: 'credit', title: 'Credit line', type: 'string'}),
        defineField({
          name: 'creditUrl',
          title: 'Credit link',
          type: 'url',
          validation: (Rule) => Rule.uri({scheme: ['http', 'https']}),
        }),
      ],
    }),
    defineField({
      name: 'summary',
      title: 'Summary',
      type: 'text',
      rows: 3,
      description: 'Lead paragraph and meta description',
    }),
    defineField({name: 'body', title: 'Biography', type: 'blockContent'}),
    defineField({
      name: 'cavemanBody',
      title: 'Caveman Biography',
      type: 'blockContent',
      description: 'Same substance, ~70% fewer words. Always fill this in.',
    }),
    defineField({
      name: 'links',
      title: 'External links',
      type: 'array',
      description: 'Wikipedia first — it becomes the structured-data sameAs.',
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
  ],
  preview: {
    select: {title: 'name', subtitle: 'knownFor', media: 'image'},
  },
})
