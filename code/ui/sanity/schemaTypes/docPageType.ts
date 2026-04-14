import {BookIcon} from '@sanity/icons'
import {defineArrayMember, defineField, defineType} from 'sanity'

export const docPageType = defineType({
  name: 'docPage',
  title: 'Documentation',
  type: 'document',
  icon: BookIcon,
  fields: [
    defineField({
      name: 'title',
      title: 'Title',
      type: 'string',
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'slug',
      title: 'Slug',
      type: 'slug',
      options: {source: 'title'},
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'section',
      title: 'Section',
      type: 'string',
      description: 'Group docs under a section heading (e.g. "Getting Started", "Screener")',
    }),
    defineField({
      name: 'order',
      title: 'Order',
      type: 'number',
      description: 'Sort order within the section (lower numbers appear first)',
      initialValue: 0,
    }),
    defineField({
      name: 'description',
      title: 'Description',
      type: 'text',
      rows: 2,
      description: 'Short summary shown on the docs index page',
    }),
    defineField({
      name: 'body',
      title: 'Body',
      type: 'blockContent',
    }),
    defineField({
      name: 'cavemanBody',
      title: 'Caveman Body',
      type: 'blockContent',
      description: 'Compressed, terse version for caveman mode. Less word. More understand.',
    }),
  ],
  orderings: [
    {
      title: 'Section / Order',
      name: 'sectionOrder',
      by: [
        {field: 'section', direction: 'asc'},
        {field: 'order', direction: 'asc'},
      ],
    },
  ],
  preview: {
    select: {
      title: 'title',
      subtitle: 'section',
    },
  },
})
