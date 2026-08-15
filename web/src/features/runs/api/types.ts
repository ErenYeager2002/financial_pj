import type {
  RunApproval,
  RunDetail,
  RunEvent,
  RunPage,
  RunStep,
  RunSummary
} from '@/features/platform-api/types';

export type PlatformRunSummary = RunSummary;
export type PlatformRunApproval = RunApproval;
export interface RunMetricSpec {
  key: string;
  label: string;
}

export interface PlatformRunDetail extends RunDetail {
  metric_specs: RunMetricSpec[];
}
export type PlatformRunEvent = RunEvent;
export type PlatformRunStep = RunStep;
export type PlatformRunPage = RunPage;

export interface RunOutputFile {
  fileId: string;
  name: string;
  sizeBytes: number;
  sha256: string;
}

export interface RunRetryResult {
  id: string;
}
