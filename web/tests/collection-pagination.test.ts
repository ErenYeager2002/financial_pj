import assert from 'node:assert/strict';
import test from 'node:test';

import {
  COLLECTION_PAGE_SIZE,
  clampCollectionPage,
  collectionPageCount,
  collectionPageSizeForWidth,
  paginateCollection
} from '../src/components/ui/collection-pagination-core.ts';

test('collection pagination defaults to five items per page', () => {
  assert.equal(COLLECTION_PAGE_SIZE, 5);
  assert.deepEqual(paginateCollection([1, 2, 3, 4, 5, 6, 7], 1).items, [1, 2, 3, 4, 5]);
  assert.deepEqual(paginateCollection([1, 2, 3, 4, 5, 6, 7], 2).items, [6, 7]);
});

test('collection pagination reports empty and exact-page ranges correctly', () => {
  assert.deepEqual(paginateCollection([], 1), {
    items: [],
    page: 1,
    pageCount: 1,
    start: 0,
    end: 0,
    total: 0,
    pageSize: 5
  });
  assert.equal(collectionPageCount(5), 1);
  assert.equal(collectionPageCount(6), 2);
});

test('collection pagination clamps invalid pages after data changes', () => {
  assert.equal(clampCollectionPage(-3, 12), 1);
  assert.equal(clampCollectionPage(99, 12), 3);
  assert.equal(clampCollectionPage(Number.NaN, 12), 1);
  assert.equal(paginateCollection([1, 2, 3], 4).page, 1);
});

test('collection pagination supports layout-specific page sizes', () => {
  const items = [1, 2, 3, 4, 5, 6, 7];
  assert.deepEqual(paginateCollection(items, 1, 6).items, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(paginateCollection(items, 2, 6).items, [7]);
  assert.equal(collectionPageCount(13, 6), 3);
  assert.equal(clampCollectionPage(5, 13, 6), 3);
});

test('responsive collection capacity follows platform breakpoints', () => {
  const skillSizes = { base: 2, md: 4, xl: 6 };
  assert.equal(collectionPageSizeForWidth(skillSizes, 390), 2);
  assert.equal(collectionPageSizeForWidth(skillSizes, 768), 4);
  assert.equal(collectionPageSizeForWidth(skillSizes, 1280), 6);

  const permissionSizes = { base: 5, md: 6, lg: 8 };
  assert.equal(collectionPageSizeForWidth(permissionSizes, 640), 5);
  assert.equal(collectionPageSizeForWidth(permissionSizes, 900), 6);
  assert.equal(collectionPageSizeForWidth(permissionSizes, 1440), 8);
});
