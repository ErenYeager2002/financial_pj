export type PiArtifact = {path: string; size: number};
export type PiDirectoryPage = {entries: {name: string; kind: 'file' | 'directory'; size: number}[]; next_offset: number | null};
export type PiDirectoryQuery = {path: string; offset: number};
type ListDirectory = (query: PiDirectoryQuery, signal: AbortSignal) => Promise<PiDirectoryPage>;
const excluded = new Set(['node_modules', 'venv', '__pycache__', 'site-packages']);

/** Bounded observation; the only dependency can list directories, not mutate them. */
export async function scanPiArtifacts(list: ListDirectory, signal: AbortSignal,
  limits: {maxRequests?: number; maxFiles?: number} = {}) {
  const maxRequests = limits.maxRequests ?? 100;
  const maxFiles = limits.maxFiles ?? 1000;
  if (![maxRequests, maxFiles].every(value => Number.isInteger(value) && value > 0)) throw new Error('Invalid artifact scan limits');
  const queue: PiDirectoryQuery[] = [{path: '', offset: 0}];
  const files: PiArtifact[] = [];
  let requests = 0;
  while (queue.length && requests < maxRequests && files.length < maxFiles) {
    signal.throwIfAborted();
    const current = queue.shift()!;
    const listing = await list(current, signal);
    signal.throwIfAborted();
    requests++;
    for (const entry of listing.entries) {
      if (entry.name.startsWith('.') || excluded.has(entry.name)) continue;
      const path = current.path ? `${current.path}/${entry.name}` : entry.name;
      if (entry.kind === 'file') {
        if (files.length >= maxFiles) return {files, truncated: true};
        files.push({path, size: entry.size});
      } else queue.push({path, offset: 0});
    }
    if (listing.next_offset !== null) queue.push({path: current.path, offset: listing.next_offset});
  }
  return {files, truncated: queue.length > 0};
}
