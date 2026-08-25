export type RegionLoadResult<T> = { state: 'ready'; data: T } | { state: 'error' };

export type RegionDisplayState<T> = {
  result: RegionLoadResult<T>;
  refreshFailed: boolean;
};

export function initialRegionDisplay<T>(result: RegionLoadResult<T>): RegionDisplayState<T> {
  return { result, refreshFailed: false };
}

export function mergeRegionResult<T>(
  current: RegionDisplayState<T>,
  incoming: RegionLoadResult<T>
): RegionDisplayState<T> {
  if (incoming.state === 'ready') return { result: incoming, refreshFailed: false };
  return current.result.state === 'ready'
    ? { result: current.result, refreshFailed: true }
    : { result: incoming, refreshFailed: true };
}

export function markRegionRefreshFailed<T>(current: RegionDisplayState<T>): RegionDisplayState<T> {
  return { ...current, refreshFailed: true };
}

function errorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object' || !('status' in error)) return undefined;
  return typeof error.status === 'number' ? error.status : undefined;
}

export async function settleRegionLoad<T>(loader: () => Promise<T>): Promise<RegionLoadResult<T>> {
  try {
    return { state: 'ready', data: await loader() };
  } catch (error) {
    if (errorStatus(error) === 401 || errorStatus(error) === 403) throw error;
    return { state: 'error' };
  }
}
