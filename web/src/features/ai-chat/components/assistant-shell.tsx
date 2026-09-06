import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface AssistantShellProps {
  header: ReactNode;
  notice?: ReactNode;
  transcript: ReactNode;
  composer: ReactNode;
  context?: ReactNode;
}

export function AssistantShell({
  header,
  notice,
  transcript,
  composer,
  context
}: AssistantShellProps) {
  return (
    <div
      className={cn(
        'platform-assistant-shell',
        context && 'platform-assistant-with-context'
      )}
    >
      <section className='platform-assistant-chat rounded-xl border bg-background'>
        {header}
        {notice && <div className='shrink-0 px-4 pt-4'>{notice}</div>}
        {transcript}
        {composer}
      </section>
      {context}
    </div>
  );
}
