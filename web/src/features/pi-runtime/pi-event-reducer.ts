import type { PiEvent, PiPoll } from './pi-protocol';

export type PiCursor = { cursor: number; instance: string; generation?: number };

export type PiPollReduction = {
  cursor: PiCursor;
  events: PiEvent[];
  reset: boolean;
  gap: boolean;
};

/** Keep UI observation tied to one Pi instance and a contiguous event stream. */
export function reducePiPoll(previous: PiCursor, poll: PiPoll): PiPollReduction {
  const instance = poll.instance_id ?? previous.instance;
  const generation = poll.generation ?? previous.generation;
  const identityChanged = Boolean(
    (previous.instance && poll.instance_id && previous.instance !== poll.instance_id) ||
    (previous.generation !== undefined && poll.generation !== undefined &&
      previous.generation !== poll.generation)
  );
  const next = Number.isSafeInteger(poll.next) && poll.next >= 0 ? poll.next : previous.cursor;
  if (identityChanged || next < previous.cursor) {
    return { cursor: { cursor: 0, instance, generation }, events: [], reset: true, gap: false };
  }
  const cursor = { cursor: next, instance, generation };
  if (poll.gap || !Array.isArray(poll.events) || !Number.isSafeInteger(poll.next) || poll.next < 0) {
    return { cursor, events: [], reset: false, gap: true };
  }
  const events: PiEvent[] = [];
  let expected = previous.cursor + 1;
  for (const entry of poll.events) {
    if (!Number.isSafeInteger(entry.sequence) || entry.sequence <= 0 ||
        (entry.generation !== undefined && generation !== undefined &&
          entry.generation !== generation)) {
      return { cursor, events: [], reset: false, gap: true };
    }
    if (entry.sequence <= previous.cursor) continue;
    if (entry.sequence !== expected) {
      return { cursor, events: [], reset: false, gap: true };
    }
    events.push(entry);
    expected += 1;
  }
  if ((next > previous.cursor && events.length === 0) ||
      (events.length > 0 && events[events.length - 1].sequence !== next)) {
    return { cursor, events: [], reset: false, gap: true };
  }
  return { cursor, events, reset: false, gap: false };
}
