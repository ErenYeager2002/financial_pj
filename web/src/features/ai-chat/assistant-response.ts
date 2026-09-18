import { createElement, type ReactNode } from 'react';
import Markdown, { defaultUrlTransform, type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

function element(
  tag: string,
  className: string,
  children: ReactNode,
  attributes: Record<string, unknown> = {}
) {
  return createElement(tag, { className, ...attributes }, children);
}

const components: Components = {
  h1: ({ children }) =>
    element('h2', 'mt-5 scroll-m-20 text-lg font-semibold tracking-tight first:mt-0', children),
  h2: ({ children }) =>
    element('h3', 'mt-5 scroll-m-20 text-base font-semibold tracking-tight first:mt-0', children),
  h3: ({ children }) =>
    element('h4', 'mt-4 scroll-m-20 text-sm font-semibold first:mt-0', children),
  h4: ({ children }) =>
    element('h5', 'mt-4 scroll-m-20 text-sm font-semibold first:mt-0', children),
  h5: ({ children }) =>
    element('h6', 'mt-4 scroll-m-20 text-xs font-semibold first:mt-0', children),
  h6: ({ children }) =>
    element('h6', 'mt-4 scroll-m-20 text-xs font-semibold first:mt-0', children),
  p: ({ children }) => element('p', 'mt-3 leading-7 text-foreground/90 first:mt-0', children),
  strong: ({ children }) => element('strong', 'font-semibold text-foreground', children),
  ul: ({ children }) =>
    element('ul', 'mt-3 list-disc space-y-1.5 pl-5 marker:text-muted-foreground', children),
  ol: ({ children }) =>
    element('ol', 'mt-3 list-decimal space-y-1.5 pl-5 marker:font-medium', children),
  li: ({ children }) => element('li', 'pl-1 leading-6', children),
  blockquote: ({ children }) =>
    element(
      'blockquote',
      'mt-3 rounded-r-md border-l-2 border-primary/50 bg-muted/50 px-3 py-2 text-muted-foreground',
      children
    ),
  pre: ({ children }) =>
    element(
      'pre',
      'mt-3 overflow-x-auto rounded-lg border bg-muted/60 p-3 font-mono text-xs leading-6',
      children
    ),
  code: ({ children }) =>
    element(
      'code',
      'break-words rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em] text-foreground',
      children
    ),
  a: ({ children, href }) =>
    element(
      'a',
      'break-all font-medium text-primary underline decoration-primary/40 underline-offset-4 hover:decoration-primary',
      children,
      href?.startsWith('http') ? { href, target: '_blank', rel: 'noreferrer noopener' } : { href }
    ),
  table: ({ children }) =>
    element(
      'div',
      'mt-3 overflow-x-auto rounded-lg border',
      element('table', 'w-full border-collapse text-left text-sm', children)
    ),
  thead: ({ children }) => element('thead', 'bg-muted/70', children),
  th: ({ children }) => element('th', 'border-b px-3 py-2 font-semibold text-foreground', children),
  td: ({ children }) => element('td', 'border-b px-3 py-2 align-top', children),
  img: ({ alt }) =>
    element(
      'span',
      'mt-3 block rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground',
      alt ? `图片：${alt}` : '图片已隐藏'
    ),
  hr: () => createElement('hr', { className: 'my-5 border-border' })
};

export function AssistantResponse({ content, resolveFileLink }: { content: string; resolveFileLink?: (href: string) => string | undefined }) {
  return createElement(
    Markdown,
    {
      components: resolveFileLink ? {...components, a: ({children, href}) => {
        const file = href ? resolveFileLink(href) : undefined;
        return file ? element('a', 'break-all font-medium text-primary underline underline-offset-4', children, {href: file, download: true})
          : element('a', 'break-all font-medium text-primary underline underline-offset-4', children,
              href?.startsWith('http') ? {href, target: '_blank', rel: 'noreferrer noopener'} : {href});
      }} : components,
      urlTransform: (url) => resolveFileLink?.(url) ? url : defaultUrlTransform(url),
      remarkPlugins: [remarkGfm],
      skipHtml: true
    },
    content
  );
}
