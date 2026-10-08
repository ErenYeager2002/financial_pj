import type { PiDialog } from './pi-dialogs';

export type PiModel = { id: string; provider: string; name?: string };
export type PiDeliveryReceipt = {
  client_request_id: string;
  delivery_state: 'prepared' | 'dispatching' | 'pi_accepted' | 'rejected' | 'unknown';
  updated_at: string;
};

export type PiEvent = {
  sequence: number;
  generation?: number;
  kind: string;
  event?: Record<string, unknown>;
};

export type PiPoll = {
  running: boolean;
  generation?: number;
  activity?: { busy: boolean; phase: string } | null;
  mode?: string;
  instance_id?: string;
  events: PiEvent[];
  next: number;
  gap?: boolean;
  pending_dialogs?: PiDialog[];
};
