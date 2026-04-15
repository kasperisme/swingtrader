import { type SchemaTypeDefinition } from 'sanity'

import {blockContentType} from './blockContentType'
import {categoryType} from './categoryType'
import {postType} from './postType'
import {authorType} from './authorType'
import {docPageType} from './docPageType'
import {legalPageType} from './legalPageType'
import {newsPublisherType} from './newsPublisherType'
import {changelogEntryType} from './changelogEntryType'

export const schema: { types: SchemaTypeDefinition[] } = {
  types: [blockContentType, categoryType, postType, authorType, docPageType, legalPageType, newsPublisherType, changelogEntryType],
}
