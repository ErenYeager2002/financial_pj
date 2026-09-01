export const COLLECTION_PAGE_SIZE = 5;

export interface ResponsiveCollectionPageSize {
  base: number;
  sm?: number;
  md?: number;
  lg?: number;
  xl?: number;
}

export interface CollectionPage<T> {
  items: T[];
  page: number;
  pageCount: number;
  start: number;
  end: number;
  total: number;
  pageSize: number;
}

export function normalizeCollectionPageSize(pageSize = COLLECTION_PAGE_SIZE): number {
  const normalized = Number.isFinite(pageSize) ? Math.trunc(pageSize) : COLLECTION_PAGE_SIZE;
  return Math.max(1, normalized);
}

export function collectionPageSizeForWidth(
  sizes: ResponsiveCollectionPageSize,
  width: number
): number {
  let pageSize = sizes.base;
  if (width >= 640 && sizes.sm !== undefined) pageSize = sizes.sm;
  if (width >= 768 && sizes.md !== undefined) pageSize = sizes.md;
  if (width >= 1024 && sizes.lg !== undefined) pageSize = sizes.lg;
  if (width >= 1280 && sizes.xl !== undefined) pageSize = sizes.xl;
  return normalizeCollectionPageSize(pageSize);
}

export function collectionPageCount(total: number, pageSize = COLLECTION_PAGE_SIZE): number {
  return Math.max(1, Math.ceil(Math.max(0, total) / normalizeCollectionPageSize(pageSize)));
}

export function clampCollectionPage(
  page: number,
  total: number,
  pageSize = COLLECTION_PAGE_SIZE
): number {
  const normalized = Number.isFinite(page) ? Math.trunc(page) : 1;
  return Math.min(Math.max(normalized, 1), collectionPageCount(total, pageSize));
}

export function paginateCollection<T>(
  items: readonly T[],
  requestedPage: number,
  requestedPageSize = COLLECTION_PAGE_SIZE
): CollectionPage<T> {
  const total = items.length;
  const pageSize = normalizeCollectionPageSize(requestedPageSize);
  const pageCount = collectionPageCount(total, pageSize);
  const page = clampCollectionPage(requestedPage, total, pageSize);
  const startIndex = (page - 1) * pageSize;
  const pageItems = items.slice(startIndex, startIndex + pageSize);

  return {
    items: pageItems,
    page,
    pageCount,
    start: total ? startIndex + 1 : 0,
    end: startIndex + pageItems.length,
    total,
    pageSize
  };
}
