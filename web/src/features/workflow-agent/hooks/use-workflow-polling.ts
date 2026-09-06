'use client';

import * as React from 'react';

const NORMAL_POLL_INTERVAL_MS = 7500;
const FAST_POLL_INTERVAL_MS = 2000;

interface WorkflowPollingOptions {
  enabled: boolean;
  fast: boolean;
  refresh: () => Promise<void>;
}

/**
 * Poll a workflow without overlapping requests and without keeping the page
 * active while it is hidden. The callback is kept in a ref so state updates do
 * not restart the timer on every response.
 */
export function useWorkflowPolling({
  enabled,
  fast,
  refresh
}: WorkflowPollingOptions): void {
  const refreshRef = React.useRef(refresh);
  const inFlightRef = React.useRef(false);

  React.useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  React.useEffect(() => {
    if (!enabled) return;

    let disposed = false;
    let timer: number | undefined;

    const clearTimer = () => {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    };

    const schedule = () => {
      clearTimer();
      if (disposed || document.visibilityState === 'hidden') return;
      timer = window.setTimeout(async () => {
        timer = undefined;
        if (disposed || document.visibilityState === 'hidden') return;
        if (!inFlightRef.current) {
          inFlightRef.current = true;
          try {
            await refreshRef.current();
          } finally {
            inFlightRef.current = false;
          }
        }
        schedule();
      }, fast ? FAST_POLL_INTERVAL_MS : NORMAL_POLL_INTERVAL_MS);
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        clearTimer();
        return;
      }
      schedule();
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    schedule();
    return () => {
      disposed = true;
      clearTimer();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [enabled, fast]);
}
