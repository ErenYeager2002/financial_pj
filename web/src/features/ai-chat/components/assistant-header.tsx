import type { ReactNode } from 'react';

interface AssistantHeaderProps {
  modelSelector: ReactNode;
  conversationControls?: ReactNode;
}

export function AssistantHeader({ modelSelector, conversationControls }: AssistantHeaderProps) {
  return (
    <header className='shrink-0 border-b px-4 py-3' aria-label='对话工具栏'>
      <div className='flex min-w-0 max-w-full flex-wrap items-center gap-2'>
        {conversationControls}
        <div className='min-w-0 max-w-full'>{modelSelector}</div>
      </div>
    </header>
  );
}
