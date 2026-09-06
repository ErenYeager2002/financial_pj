'use client';

import { IconChevronLeft, IconChevronRight } from '@tabler/icons-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import {
  COLLECTION_PAGE_SIZE,
  clampCollectionPage,
  collectionPageCount,
  collectionPageSizeForWidth,
  type ResponsiveCollectionPageSize,
  paginateCollection
} from '@/components/ui/collection-pagination-core';
import { cn } from '@/lib/utils';

interface CollectionPaginationControlsProps {
  ariaLabel: string;
  page: number;
  pageCount: number;
  total: number;
  onPageChange: (page: number) => void;
}

function subscribeToViewport(onStoreChange: () => void): () => void {
  window.addEventListener('resize', onStoreChange);
  return () => window.removeEventListener('resize', onStoreChange);
}

function viewportWidthSnapshot(): number {
  return window.innerWidth;
}

function serverViewportWidthSnapshot(): number {
  return 0;
}

export function useResponsiveCollectionPageSize(sizes: ResponsiveCollectionPageSize): number {
  const width = React.useSyncExternalStore(
    subscribeToViewport,
    viewportWidthSnapshot,
    serverViewportWidthSnapshot
  );
  return collectionPageSizeForWidth(sizes, width);
}

export function useCollectionPagination<T>(items: readonly T[], pageSize = COLLECTION_PAGE_SIZE) {
  const [page, setPage] = React.useState(1);
  const previousPageSizeRef = React.useRef(pageSize);
  const current = paginateCollection(items, page, pageSize);

  React.useEffect(() => {
    setPage((value) => {
      const previousPageSize = previousPageSizeRef.current;
      const firstVisibleIndex = (value - 1) * previousPageSize;
      previousPageSizeRef.current = pageSize;
      return clampCollectionPage(
        Math.floor(firstVisibleIndex / pageSize) + 1,
        items.length,
        pageSize
      );
    });
  }, [items.length, pageSize]);

  return { ...current, setPage };
}

export function useResponsiveCollectionPagination<T>(
  items: readonly T[],
  sizes: ResponsiveCollectionPageSize
) {
  return useCollectionPagination(items, useResponsiveCollectionPageSize(sizes));
}

export function CollectionPaginationControls({
  ariaLabel,
  page,
  pageCount,
  total,
  onPageChange
}: CollectionPaginationControlsProps): React.JSX.Element | null {
  if (pageCount <= 1) return null;

  return (
    <div
      className='mt-3 flex flex-wrap items-center justify-end gap-2'
      role='group'
      aria-label={`${ariaLabel}分页`}
    >
      <Button
        type='button'
        variant='outline'
        className='min-h-11 min-w-11'
        disabled={page <= 1}
        aria-label={`${ariaLabel}上一页`}
        onClick={() => onPageChange(page - 1)}
      >
        <IconChevronLeft />
        <span className='hidden sm:inline'>上一页</span>
      </Button>
      <p className='min-w-32 text-center text-sm text-muted-foreground' aria-live='polite'>
        第 {page} / {pageCount} 页 · 共 {total} 项
      </p>
      <Button
        type='button'
        variant='outline'
        className='min-h-11 min-w-11'
        disabled={page >= pageCount}
        aria-label={`${ariaLabel}下一页`}
        onClick={() => onPageChange(page + 1)}
      >
        <span className='hidden sm:inline'>下一页</span>
        <IconChevronRight />
      </Button>
    </div>
  );
}

interface PaginatedCollectionProps {
  ariaLabel: string;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
  startAtEnd?: boolean;
  followEnd?: boolean;
  pageSize?: number;
  responsivePageSize?: ResponsiveCollectionPageSize;
}

export function PaginatedCollection({
  ariaLabel,
  children,
  className,
  contentClassName,
  startAtEnd = false,
  followEnd = false,
  pageSize = COLLECTION_PAGE_SIZE,
  responsivePageSize
}: PaginatedCollectionProps): React.JSX.Element {
  const resolvedPageSize = useResponsiveCollectionPageSize(
    responsivePageSize ?? { base: pageSize }
  );
  const childItems = React.Children.toArray(children);
  const total = childItems.length;
  const lastPage = collectionPageCount(total, resolvedPageSize);
  const [page, setPage] = React.useState(() => (startAtEnd ? lastPage : 1));
  const viewportRef = React.useRef<HTMLDivElement>(null);
  const previousTotalRef = React.useRef(total);
  const previousPageSizeRef = React.useRef(resolvedPageSize);
  const current = paginateCollection(childItems, page, resolvedPageSize);

  React.useEffect(() => {
    setPage((value) => {
      if (followEnd && total > previousTotalRef.current) return lastPage;
      const firstVisibleIndex = (value - 1) * previousPageSizeRef.current;
      return clampCollectionPage(
        Math.floor(firstVisibleIndex / resolvedPageSize) + 1,
        total,
        resolvedPageSize
      );
    });
    previousTotalRef.current = total;
    previousPageSizeRef.current = resolvedPageSize;
  }, [followEnd, lastPage, resolvedPageSize, total]);

  function changePage(nextPage: number) {
    setPage(nextPage);
    viewportRef.current?.scrollTo({ top: 0, behavior: 'auto' });
  }

  return (
    <div className={className}>
      <div
        ref={viewportRef}
        role='region'
        aria-label={`${ariaLabel}，每页最多 ${current.pageSize} 项`}
        data-collection-viewport=''
        className='max-h-[36rem] overflow-y-auto overscroll-contain rounded-lg pr-2 [scrollbar-gutter:stable] outline-none focus-visible:ring-3 focus-visible:ring-ring/50'
      >
        <div className={cn('min-w-0', contentClassName)}>{current.items}</div>
      </div>
      <CollectionPaginationControls
        ariaLabel={ariaLabel}
        page={current.page}
        pageCount={current.pageCount}
        total={current.total}
        onPageChange={changePage}
      />
    </div>
  );
}

interface PaginatedTableBodyProps {
  ariaLabel: string;
  children: React.ReactNode;
  colSpan: number;
  className?: string;
}

export function PaginatedTableBody({
  ariaLabel,
  children,
  colSpan,
  className
}: PaginatedTableBodyProps): React.JSX.Element {
  const rows = React.Children.toArray(children);
  const current = useCollectionPagination(rows);

  return (
    <>
      <tbody className={className}>{current.items}</tbody>
      {current.pageCount > 1 ? (
        <tfoot>
          <tr>
            <td colSpan={colSpan} className='border-t bg-background px-3 py-2'>
              <CollectionPaginationControls
                ariaLabel={ariaLabel}
                page={current.page}
                pageCount={current.pageCount}
                total={current.total}
                onPageChange={current.setPage}
              />
            </td>
          </tr>
        </tfoot>
      ) : null}
    </>
  );
}
