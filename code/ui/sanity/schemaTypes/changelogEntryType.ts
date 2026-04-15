import {BellIcon} from '@sanity/icons'
import {defineArrayMember, defineField, defineType} from 'sanity'

export const changelogEntryType = defineType({
  name: 'changelogEntry',
  title: 'Changelog',
  type: 'document',
  icon: BellIcon,
  fields: [
    defineField({
      name: 'title',
      title: 'Title',
      type: 'string',
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'date',
      title: 'Date',
      type: 'date',
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'tags',
      title: 'Tags',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'string',
          options: {
            list: [
              {title: 'Feature', value: 'feature'},
              {title: 'Improvement', value: 'improvement'},
              {title: 'Fix', value: 'fix'},
              {title: 'Breaking', value: 'breaking'},
            ],
          },
        }),
      ],
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
      description: 'Compressed, terse version for caveman mode.',
    }),
  ],
  orderings: [
    {
      title: 'Newest First',
      name: 'dateDesc',
      by: [{field: 'date', direction: 'desc'}],
    },
  ],
  preview: {
    select: {
      title: 'title',
      subtitle: 'date',
    },
  },
})
