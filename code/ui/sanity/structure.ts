import type {StructureResolver} from 'sanity/structure'

// https://www.sanity.io/docs/structure-builder-cheat-sheet
export const structure: StructureResolver = (S) =>
  S.list()
    .title('Content')
    .items([
      S.listItem().title('Documentation').child(
        S.documentTypeList('docPage').title('Documentation Pages'),
      ),
      S.divider(),
      S.documentTypeListItem('post').title('Posts'),
      S.documentTypeListItem('category').title('Categories'),
      S.documentTypeListItem('author').title('Authors'),
      S.divider(),
      S.listItem().title('Legal Pages').child(
        S.documentTypeList('legalPage').title('Legal Pages'),
      ),
      S.listItem().title('News Publishers').child(
        S.documentTypeList('newsPublisher').title('News Publishers'),
      ),
      S.divider(),
      ...S.documentTypeListItems().filter(
        (item) => item.getId() && !['docPage', 'post', 'category', 'author', 'legalPage', 'newsPublisher'].includes(item.getId()!),
      ),
    ])
