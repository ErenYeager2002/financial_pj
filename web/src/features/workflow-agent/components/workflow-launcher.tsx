'use client';

import * as React from 'react';
import Link from 'next/link';
import { format, startOfDay } from 'date-fns';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar, CalendarDayButton } from '@/components/ui/calendar';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import { Icons } from '@/components/icons';
import { ZhiyunCredentialCard } from '@/features/workflow-agent/components/zhiyun-credential-card';
import {
  reusableMaterialSelection,
  selectedMaterialUpdates,
  type WorkflowMaterialFile
} from '@/features/workflow-agent/workflow-materials';
import {
  addWorkflowDate,
  workflowDateRangeSelection,
  workflowDateRangeSummary,
  toggleWorkflowDate,
  validateWorkflowDateRange,
  workflowInitialDateSelection,
  workflowInitialDateSelectionKey,
  workflowDateKey
} from '@/features/workflow-agent/workflow-date-selection';
import type {
  SkillDetail,
  WorkflowBatchRead,
  WorkflowFetchedSnapshot,
  WorkflowRead,
  WorkflowReusableFilesRead
} from '@/features/platform-api/types';
import { cn } from '@/lib/utils';

interface WorkflowLauncherProps {
  skills: SkillDetail[];
  workflows: WorkflowRead[];
  batches: WorkflowBatchRead[];
  initialSkillId?: string;
  initialDates?: string[];
  initialReusableFiles: WorkflowReusableFilesRead | null;
}

type ReconciliationExecutionMode = 'workflow' | 'pi_harness';

function skillExecutionModes(skill: SkillDetail | undefined): ReconciliationExecutionMode[] {
  const modes = skill?.execution_modes ?? [];
  return modes.length ? modes : ['workflow'];
}

function defaultSkillExecutionMode(skill: SkillDetail | undefined): ReconciliationExecutionMode {
  const modes = skillExecutionModes(skill);
  const configured = skill?.default_execution_mode;
  return configured && modes.includes(configured) ? configured : modes[0];
}

interface WorkflowDateInteraction {
  begin: (target: Date, event: React.PointerEvent<HTMLButtonElement>) => void;
  enter: (target: Date, event: React.PointerEvent<HTMLButtonElement>) => void;
  click: (target: Date, event: React.MouseEvent<HTMLButtonElement>) => void;
  selectedKeys: ReadonlySet<string>;
}

const WorkflowDateInteractionContext = React.createContext<WorkflowDateInteraction | null>(null);

function WorkflowCalendarDayButton(
  props: React.ComponentProps<typeof CalendarDayButton>
): React.JSX.Element {
  const interaction = React.useContext(WorkflowDateInteractionContext);
  const dateKey = workflowDateKey(props.day.date);
  const selected = interaction?.selectedKeys.has(dateKey) ?? false;
  return (
    <CalendarDayButton
      {...props}
      data-workflow-date={dateKey}
      data-workflow-selected={selected}
      aria-pressed={selected}
      className={cn(
        props.className,
        'data-[workflow-selected=true]:bg-primary data-[workflow-selected=true]:text-primary-foreground data-[workflow-selected=true]:ring-2 data-[workflow-selected=true]:ring-primary/40 data-[workflow-selected=true]:hover:bg-primary/90 data-[workflow-selected=true]:hover:text-primary-foreground'
      )}
      onPointerDown={(event) => interaction?.begin(props.day.date, event)}
      onPointerEnter={(event) => interaction?.enter(props.day.date, event)}
      onClick={(event) => interaction?.click(props.day.date, event)}
    />
  );
}

const WORKFLOW_CALENDAR_COMPONENTS = { DayButton: WorkflowCalendarDayButton };

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    awaiting_date: '等待选择日期',
    awaiting_files: '等待材料',
    preparing: '后台处理中',
    awaiting_apply_confirmation: '等待确认写入',
    waiting_approval: '等待管理员审批',
    applying: '写入中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    queued: '排队中'
  };
  return labels[stage] ?? stage;
}

function batchStateLabel(state: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    cancelling: '取消中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消'
  };
  return labels[state] ?? state;
}

function responseMessage(response: Response, fallback: string): Promise<string> {
  return response
    .json()
    .then((body: unknown) => {
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        return body.detail;
      }
      return fallback;
    })
    .catch(() => fallback);
}

export function WorkflowLauncher({
  skills,
  workflows,
  batches,
  initialSkillId = '',
  initialDates = [],
  initialReusableFiles
}: WorkflowLauncherProps): React.JSX.Element {
  const today = React.useMemo(() => startOfDay(new Date()), []);
  const selectedInitialSkill =
    initialSkillId && skills.some((skill) => skill.id === initialSkillId)
      ? initialSkillId
      : (skills[0]?.id ?? '');
  const initialSkill = skills.find((skill) => skill.id === selectedInitialSkill);
  const [skillId, setSkillId] = React.useState(selectedInitialSkill);
  const [executionMode, setExecutionMode] = React.useState<ReconciliationExecutionMode>(() =>
    defaultSkillExecutionMode(initialSkill)
  );
  const [selectedDates, setSelectedDates] = React.useState<Date[]>([]);
  const [dateRangeStart, setDateRangeStart] = React.useState('');
  const [dateRangeEnd, setDateRangeEnd] = React.useState('');
  const [dateError, setDateError] = React.useState('');
  const [materials, setMaterials] = React.useState<Record<string, WorkflowMaterialFile[]>>(() =>
    reusableMaterialSelection(initialReusableFiles, selectedInitialSkill)
  );
  const [materialVersion, setMaterialVersion] = React.useState<number | null>(() =>
    initialReusableFiles?.skill_id === selectedInitialSkill
      ? (initialReusableFiles.material_version ?? null)
      : null
  );
  const [materialsLoading, setMaterialsLoading] = React.useState(false);
  const [materialsError, setMaterialsError] = React.useState('');
  const [materialsRefreshKey, setMaterialsRefreshKey] = React.useState(0);
  const [dirtyRoles, setDirtyRoles] = React.useState<Set<string>>(() => new Set());
  const [uploadingRole, setUploadingRole] = React.useState('');
  const [deletingFileId, setDeletingFileId] = React.useState('');
  const [working, setWorking] = React.useState(false);
  const [zhiyunCredentialConfigured, setZhiyunCredentialConfigured] = React.useState(false);
  const [snapshotOptions, setSnapshotOptions] = React.useState<WorkflowFetchedSnapshot[]>([]);
  const [snapshotOptionsLoading, setSnapshotOptionsLoading] = React.useState(false);
  const [snapshotOptionsError, setSnapshotOptionsError] = React.useState('');
  const [useSnapshot, setUseSnapshot] = React.useState(false);
  const [selectedFetchedBundleId, setSelectedFetchedBundleId] = React.useState('');
  const [error, setError] = React.useState('');
  const appliedInitialDatesKeyRef = React.useRef('');
  const dateDragRef = React.useRef<{
    pointerId: number;
    start: Date;
    active: boolean;
    timer: number;
  } | null>(null);
  const suppressDateClickRef = React.useRef(false);
  const selectedSkill = skills.find((skill) => skill.id === skillId);
  const executionModes = skillExecutionModes(selectedSkill);
  const requiresZhiyunCredential = selectedSkill?.id === 'ar-hexiao-daily' && !useSnapshot;
  const supportsSnapshotReplay = selectedSkill?.id === 'ar-hexiao-daily';
  const replayableOptions = React.useMemo(
    () =>
      snapshotOptions.filter(
        (item) => item.replayable && item.availability === 'replayable_bundle'
      ),
    [snapshotOptions]
  );
  const selectedSnapshot = snapshotOptions.find(
    (item) => item.bundle_id === selectedFetchedBundleId && item.replayable
  );
  const fileInputs = selectedSkill?.file_inputs ?? [];
  const recentTasks = React.useMemo(
    () =>
      [
        ...workflows.map((workflow) => ({ kind: 'workflow' as const, item: workflow })),
        ...batches.map((batch) => ({ kind: 'batch' as const, item: batch }))
      ]
        .toSorted(
          (left, right) =>
            new Date(right.item.updated_at).getTime() - new Date(left.item.updated_at).getTime()
        )
        .slice(0, 50),
    [batches, workflows]
  );

  React.useEffect(() => {
    const parsedInitialDates = workflowInitialDateSelection(
      initialDates,
      skillId,
      selectedInitialSkill,
      today,
      appliedInitialDatesKeyRef.current
    );
    if (skillId === selectedInitialSkill) {
      appliedInitialDatesKeyRef.current = workflowInitialDateSelectionKey(
        selectedInitialSkill,
        initialDates
      );
    } else {
      appliedInitialDatesKeyRef.current = '';
    }
    if (parsedInitialDates !== null) {
      setSelectedDates(parsedInitialDates);
      setDateRangeStart(parsedInitialDates.length ? workflowDateKey(parsedInitialDates[0]) : '');
      setDateRangeEnd(
        parsedInitialDates.length ? workflowDateKey(parsedInitialDates.at(-1) as Date) : ''
      );
    }
    setDateError('');
    setError('');
    setMaterialsError('');
    setSnapshotOptionsError('');
    setUseSnapshot(false);
    setSelectedFetchedBundleId('');
    setDeletingFileId('');
    setDirtyRoles(new Set());
    if (!skillId) {
      setMaterials({});
      setMaterialVersion(null);
      return;
    }
    const controller = new AbortController();
    if (initialReusableFiles?.skill_id !== skillId) setMaterials({});
    setMaterialsLoading(true);
    void fetch(`/api/platform/workflows/reusable-files?skill_id=${encodeURIComponent(skillId)}`, {
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(await responseMessage(response, '已保存任务材料加载失败。'));
        }
        return (await response.json()) as WorkflowReusableFilesRead;
      })
      .then((response) => {
        setMaterials(reusableMaterialSelection(response, skillId));
        setMaterialVersion(response.material_version ?? null);
        setMaterialsError('');
      })
      .catch((loadError: unknown) => {
        if (loadError instanceof DOMException && loadError.name === 'AbortError') return;
        setMaterialsError(
          loadError instanceof Error ? loadError.message : '已保存任务材料加载失败。'
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setMaterialsLoading(false);
      });
    return () => controller.abort();
  }, [
    initialDates,
    initialReusableFiles,
    materialsRefreshKey,
    selectedInitialSkill,
    skillId,
    today
  ]);

  React.useEffect(() => {
    if (!supportsSnapshotReplay || !skillId) {
      setSnapshotOptions([]);
      setSnapshotOptionsLoading(false);
      return;
    }
    const controller = new AbortController();
    setSnapshotOptionsLoading(true);
    setSnapshotOptionsError('');
    fetch(`/api/platform/workflows/fetched-snapshots?skill_id=${encodeURIComponent(skillId)}`, {
      signal: controller.signal,
      cache: 'no-store'
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await responseMessage(response, '取数记录加载失败。'));
        return (await response.json()) as WorkflowFetchedSnapshot[];
      })
      .then((options) => {
        setSnapshotOptions(options);
        const replayable = options.filter(
          (item) => item.replayable && item.availability === 'replayable_bundle'
        );
        setSelectedFetchedBundleId((current) =>
          replayable.some((item) => item.bundle_id === current)
            ? current
            : (replayable[0]?.bundle_id ?? '')
        );
      })
      .catch((loadError: unknown) => {
        if (loadError instanceof DOMException && loadError.name === 'AbortError') return;
        setSnapshotOptionsError(
          loadError instanceof Error ? loadError.message : '取数记录加载失败。'
        );
        setSnapshotOptions([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setSnapshotOptionsLoading(false);
      });
    return () => controller.abort();
  }, [skillId, supportsSnapshotReplay]);

  const addDraggedDate = React.useCallback(
    (target: Date) =>
      setSelectedDates((current) => {
        const next = addWorkflowDate(current, target, today);
        const ordered = next.toSorted((left, right) => left.getTime() - right.getTime());
        setDateRangeStart(ordered.length ? format(ordered[0], 'yyyy-MM-dd') : '');
        setDateRangeEnd(ordered.length ? format(ordered.at(-1) as Date, 'yyyy-MM-dd') : '');
        setDateError('');
        return next;
      }),
    [today]
  );

  const finishDateDrag = React.useCallback((pointerId?: number) => {
    const current = dateDragRef.current;
    if (!current || (pointerId !== undefined && current.pointerId !== pointerId)) return;
    clearTimeout(current.timer);
    if (current.active) {
      suppressDateClickRef.current = true;
      window.setTimeout(() => {
        suppressDateClickRef.current = false;
      }, 200);
    }
    dateDragRef.current = null;
  }, []);

  React.useEffect(() => {
    const finish = (event: PointerEvent) => finishDateDrag(event.pointerId);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    return () => {
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
      finishDateDrag();
    };
  }, [finishDateDrag]);

  const beginDateDrag = React.useCallback(
    (target: Date, event: React.PointerEvent<HTMLButtonElement>) => {
      if (startOfDay(target) > today || event.button !== 0) return;
      finishDateDrag();
      const drag = {
        pointerId: event.pointerId,
        start: target,
        active: false,
        timer: window.setTimeout(() => {
          const current = dateDragRef.current;
          if (!current || current.pointerId !== event.pointerId) return;
          current.active = true;
          addDraggedDate(current.start);
        }, 320)
      };
      dateDragRef.current = drag;
    },
    [addDraggedDate, finishDateDrag, today]
  );

  const enterDateDuringDrag = React.useCallback(
    (target: Date, event: React.PointerEvent<HTMLButtonElement>) => {
      const current = dateDragRef.current;
      if (!current || !current.active || current.pointerId !== event.pointerId) return;
      addDraggedDate(target);
    },
    [addDraggedDate]
  );

  const moveDateDrag = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const current = dateDragRef.current;
      if (!current || !current.active || current.pointerId !== event.pointerId) return;
      const element = document
        .elementFromPoint(event.clientX, event.clientY)
        ?.closest<HTMLElement>('[data-workflow-date]');
      const key = element?.dataset.workflowDate;
      if (!key) return;
      const [year, month, day] = key.split('-').map(Number);
      if (year && month && day) addDraggedDate(new Date(year, month - 1, day));
    },
    [addDraggedDate]
  );

  const clickDate = React.useCallback(
    (target: Date, event: React.MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      if (suppressDateClickRef.current) {
        suppressDateClickRef.current = false;
        return;
      }
      setSelectedDates((current) => {
        const next = toggleWorkflowDate(current, target, today);
        const ordered = next.toSorted((left, right) => left.getTime() - right.getTime());
        setDateRangeStart(ordered.length ? format(ordered[0], 'yyyy-MM-dd') : '');
        setDateRangeEnd(ordered.length ? format(ordered.at(-1) as Date, 'yyyy-MM-dd') : '');
        setDateError(validateWorkflowDateRange(next));
        return next;
      });
    },
    [today]
  );

  function updateDateRange(startValue: string, endValue: string) {
    setDateRangeStart(startValue);
    setDateRangeEnd(endValue);
    const selection = workflowDateRangeSelection(startValue, endValue, today);
    setDateError(selection.error || validateWorkflowDateRange(selection.dates));
    if (!selection.error) setSelectedDates(selection.dates);
  }

  const selectedDateKeys = React.useMemo(
    () => new Set(selectedDates.map(workflowDateKey)),
    [selectedDates]
  );

  const dateInteraction = React.useMemo(
    () => ({
      begin: beginDateDrag,
      enter: enterDateDuringDrag,
      click: clickDate,
      selectedKeys: selectedDateKeys
    }),
    [beginDateDrag, clickDate, enterDateDuringDrag, selectedDateKeys]
  );

  async function deleteUploadedFile(fileId: string) {
    const response = await fetch(`/api/platform/files/${encodeURIComponent(fileId)}`, {
      method: 'DELETE'
    });
    if (!response.ok) throw new Error(await responseMessage(response, '文件删除失败。'));
  }

  async function uploadMaterial(
    role: string,
    multiple: boolean,
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const selected = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (!selected.length || uploadingRole) return;
    const uploads = multiple ? selected : selected.slice(0, 1);
    const previousFiles = materials[role] ?? [];
    setUploadingRole(role);
    setError('');
    const uploaded: Array<{ id: string; name: string }> = [];
    try {
      for (const file of uploads) {
        const form = new FormData();
        form.set('skill_id', skillId);
        form.set('role', role);
        form.set('workflow_upload', 'true');
        form.set('upload', file);
        const response = await fetch('/api/platform/files', { method: 'POST', body: form });
        if (!response.ok) throw new Error(await responseMessage(response, '文件上传失败。'));
        const result = (await response.json()) as { id?: unknown; name?: unknown };
        if (typeof result.id !== 'string') throw new Error('文件上传结果无效。');
        uploaded.push({
          id: result.id,
          name: typeof result.name === 'string' ? result.name : file.name
        });
      }
      setMaterials((current) => ({
        ...current,
        [role]: multiple
          ? [
              ...(current[role] ?? []),
              ...uploaded.map((item) => ({ ...item, source: 'uploaded' as const }))
            ]
          : uploaded.map((item) => ({ ...item, source: 'uploaded' as const }))
      }));
      setDirtyRoles((current) => new Set(current).add(role));
      const previousUploadedIds = previousFiles
        .filter((item) => item.source === 'uploaded')
        .map((item) => item.id);
      if (!multiple && previousUploadedIds.length) {
        const cleanup = await Promise.allSettled(
          previousUploadedIds.map((fileId) => deleteUploadedFile(fileId))
        );
        if (cleanup.some((result) => result.status === 'rejected')) {
          setError('新文件已上传并生效，但旧文件未能自动删除，请到文件中心处理。');
        }
      }
    } catch (uploadError) {
      const uploadedIds = uploaded.map((item) => item.id);
      await Promise.allSettled(uploadedIds.map((fileId) => deleteUploadedFile(fileId)));
      setError(uploadError instanceof Error ? uploadError.message : '文件上传失败。');
    } finally {
      setUploadingRole('');
    }
  }

  async function removeMaterial(role: string, material: WorkflowMaterialFile) {
    if (working || uploadingRole || deletingFileId) return;
    const message =
      material.source === 'saved'
        ? `确认本次任务不再使用“${material.name}”吗？旧任务中的文件不会被删除。`
        : `确认删除本次上传的“${material.name}”吗？`;
    if (!window.confirm(message)) return;
    setDeletingFileId(material.id);
    setError('');
    try {
      if (material.source === 'uploaded') await deleteUploadedFile(material.id);
      setMaterials((current) => ({
        ...current,
        [role]: (current[role] ?? []).filter((item) => item.id !== material.id)
      }));
      setDirtyRoles((current) => new Set(current).add(role));
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : '文件删除失败。');
    } finally {
      setDeletingFileId('');
    }
  }

  async function start() {
    const dates = selectedDates
      .filter((item) => startOfDay(item) <= today)
      .toSorted((left, right) => left.getTime() - right.getTime())
      .map((item) => format(item, 'yyyy-MM-dd'));
    if (!skillId || working || uploadingRole || deletingFileId) return;
    if (!dates.length) {
      setDateError('请至少选择一个核销日期。');
      return;
    }
    if (requiresZhiyunCredential && !zhiyunCredentialConfigured) {
      setError('请先安全保存智云账号和密码。');
      return;
    }
    if (useSnapshot) {
      if (!selectedFetchedBundleId || !selectedSnapshot) {
        setError('请选择一个可回放取数包。');
        return;
      }
      const unavailableDates = dates.filter((item) => !selectedSnapshot.dates.includes(item));
      if (unavailableDates.length) {
        setError(`所选取数包不包含这些日期：${unavailableDates.join('、')}。`);
        return;
      }
    }
    const dateRangeError = validateWorkflowDateRange(selectedDates);
    if (dateRangeError) {
      setDateError(dateRangeError);
      return;
    }
    const rerunSuccessfulDates = skillId === 'ar-hexiao-daily';
    setWorking(true);
    setError('');
    setDateError('');
    try {
      const { files, replace_roles } = selectedMaterialUpdates(materials, dirtyRoles);
      const useBatchEndpoint = dates.length > 1 || rerunSuccessfulDates;
      const endpoint = !useBatchEndpoint
        ? '/api/platform/workflows/start'
        : '/api/platform/workflow-batches/start';
      const body = !useBatchEndpoint
        ? {
            skill_id: skillId,
            execution_mode: executionMode,
            reconciliation_date: dates[0],
            files,
            replace_roles,
            ...(useSnapshot ? { fetched_bundle_id: selectedFetchedBundleId } : {})
          }
        : {
            skill_id: skillId,
            execution_mode: executionMode,
            reconciliation_dates: dates,
            files,
            replace_roles,
            rerun_successful_dates: rerunSuccessfulDates,
            rerun_reason: rerunSuccessfulDates ? '创建任务页默认重新核销所选已成功日期' : '',
            ...(useSnapshot ? { fetched_bundle_id: selectedFetchedBundleId } : {})
          };
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!response.ok) throw new Error(await responseMessage(response, '任务启动失败。'));
      const result = (await response.json()) as { id?: unknown };
      if (typeof result.id !== 'string') throw new Error('任务返回结果无效。');
      window.location.assign(
        !useBatchEndpoint
          ? `/dashboard/workflows/${encodeURIComponent(result.id)}`
          : `/dashboard/workflows/batches/${encodeURIComponent(result.id)}`
      );
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : '任务启动失败。');
    } finally {
      setWorking(false);
    }
  }

  const selectedDateLabel = selectedDates.length
    ? selectedDates
        .toSorted((left, right) => left.getTime() - right.getTime())
        .map((item) => format(item, 'yyyy-MM-dd'))
        .join('、')
    : '尚未选择';
  const dateRangeSummary = workflowDateRangeSummary(selectedDates);
  const todayValue = format(today, 'yyyy-MM-dd');

  return (
    <div className='grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,28rem)]'>
      <Card>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Icons.sparkles className='size-5' /> 新建应收核销任务
          </CardTitle>
        </CardHeader>
        <CardContent className='space-y-5'>
          <label className='grid gap-1.5 text-sm font-medium'>
            执行 Skill
            <select
              className='h-10 rounded-md border bg-background px-3 font-normal'
              value={skillId}
              onChange={(event) => {
                const nextSkillId = event.target.value;
                setSkillId(nextSkillId);
                setExecutionMode(
                  defaultSkillExecutionMode(skills.find((skill) => skill.id === nextSkillId))
                );
                setRerunSuccessfulDates(false);
                setRerunReason('');
              }}
              disabled={working || skills.length === 0}
            >
              {skills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name} · v{skill.version}
                </option>
              ))}
            </select>
          </label>

          {executionModes.length > 1 && (
            <fieldset className='grid gap-2 rounded-lg border p-3'>
              <legend className='px-1 text-sm font-medium'>执行方式</legend>
              <div className='grid gap-2 sm:grid-cols-2'>
                {executionModes.map((mode) => (
                  <label
                    key={mode}
                    className={cn(
                      'flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm',
                      executionMode === mode && 'border-primary bg-primary/5'
                    )}
                  >
                    <input
                      type='radio'
                      name='reconciliation-execution-mode'
                      value={mode}
                      checked={executionMode === mode}
                      disabled={working}
                      onChange={() => setExecutionMode(mode)}
                      className='mt-0.5'
                    />
                    <span>
                      <span className='block font-medium'>
                        {mode === 'pi_harness' ? '受控智能执行' : '工作流执行'}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          {requiresZhiyunCredential && (
            <ZhiyunCredentialCard
              disabled={working}
              onConfiguredChange={setZhiyunCredentialConfigured}
            />
          )}

          {supportsSnapshotReplay && (
            <div className='rounded-lg border p-3'>
              <p className='text-sm font-medium'>取数记录</p>
              <div className='mt-3 grid gap-2 text-sm'>
                <label
                  htmlFor='fetched-data-source-live'
                  aria-label='实时连接智云'
                  className='flex cursor-pointer items-start gap-2'
                >
                  <input
                    id='fetched-data-source-live'
                    aria-label='实时连接智云'
                    type='radio'
                    name='fetched-data-source'
                    checked={!useSnapshot}
                    disabled={working}
                    onChange={() => setUseSnapshot(false)}
                    className='mt-0.5'
                  />
                  <span>
                    <span className='font-medium'>实时连接智云</span>
                    <span className='mt-0.5 block text-xs text-muted-foreground'>
                      需要公司网络和已保存的智云凭据。
                    </span>
                  </span>
                </label>
                <label
                  htmlFor='fetched-data-source-snapshot'
                  aria-label='使用可回放取数包'
                  className='flex cursor-pointer items-start gap-2'
                >
                  <input
                    id='fetched-data-source-snapshot'
                    aria-label='使用可回放取数包'
                    type='radio'
                    name='fetched-data-source'
                    checked={useSnapshot}
                    disabled={working || snapshotOptionsLoading || replayableOptions.length === 0}
                    onChange={() => setUseSnapshot(true)}
                    className='mt-0.5'
                  />
                  <span className='min-w-0 flex-1'>
                    <span className='font-medium'>使用可回放取数包</span>
                  </span>
                </label>
              </div>
              {snapshotOptionsLoading && (
                <p className='mt-2 text-xs text-muted-foreground'>正在读取取数记录…</p>
              )}
              {snapshotOptionsError && (
                <p role='alert' className='mt-2 text-sm text-destructive'>
                  {snapshotOptionsError}
                </p>
              )}
              {useSnapshot && replayableOptions.length > 0 && (
                <label className='mt-3 grid gap-1.5 text-sm font-medium'>
                  选择可回放取数包
                  <select
                    className='h-10 rounded-md border bg-background px-3 font-normal'
                    value={selectedFetchedBundleId}
                    disabled={working}
                    onChange={(event) => setSelectedFetchedBundleId(event.target.value)}
                  >
                    {replayableOptions.map((option) => (
                      <option key={option.bundle_id} value={option.bundle_id}>
                        {option.source_display_id} · {option.dates.join('、')}
                      </option>
                    ))}
                  </select>
                  <span className='text-xs font-normal text-muted-foreground'>
                    只能选择包含所选全部核销日期的取数包。
                  </span>
                </label>
              )}
              {!snapshotOptionsLoading && !snapshotOptionsError && replayableOptions.length === 0 && (
                <p className='mt-2 text-xs text-muted-foreground'>当前没有可回放取数包。</p>
              )}
            </div>
          )}

          <div className='rounded-lg border bg-muted/20 p-3'>
            <div className='flex items-start justify-between gap-3'>
              <div>
                <p className='text-sm font-medium'>选择核销日期</p>
                <p className='mt-1 text-xs text-muted-foreground'>
                  单击选择或取消一天；按住日期后滑动可连续选择多天。今天之后不可选。
                </p>
              </div>
              <div className='flex shrink-0 items-center gap-2'>
                <Badge variant='secondary'>{selectedDates.length} 个核销日</Badge>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={selectedDates.length === 0 || working}
                  onClick={() => {
                    setSelectedDates([]);
                    setDateRangeStart('');
                    setDateRangeEnd('');
                    setDateError('');
                  }}
                >
                  清除全部日期
                </Button>
              </div>
            </div>
            <div className='mt-3 grid gap-3 sm:grid-cols-2'>
              <label className='grid gap-1 text-sm'>
                <span>开始日期</span>
                <input
                  type='date'
                  value={dateRangeStart}
                  max={todayValue}
                  disabled={working}
                  onChange={(event) => updateDateRange(event.target.value, dateRangeEnd)}
                  className='h-10 rounded-md border bg-background px-3'
                />
              </label>
              <label className='grid gap-1 text-sm'>
                <span>结束日期</span>
                <input
                  type='date'
                  value={dateRangeEnd}
                  max={todayValue}
                  disabled={working}
                  onChange={(event) => updateDateRange(dateRangeStart, event.target.value)}
                  className='h-10 rounded-md border bg-background px-3'
                />
              </label>
            </div>
            <p className='mt-2 text-xs text-muted-foreground' aria-live='polite'>
              {dateRangeSummary.dateCount
                ? `${dateRangeSummary.dateCount} 个核销日（包含周末）`
                : '输入开始和结束日期可自动选择连续日期，周末也会包含。'}
            </p>
            {dateError && (
              <p role='alert' className='mt-2 text-sm text-destructive'>
                {dateError}
              </p>
            )}
            <div className='touch-none' onPointerMove={moveDateDrag}>
              <WorkflowDateInteractionContext.Provider value={dateInteraction}>
                <Calendar
                  mode='multiple'
                  selected={selectedDates}
                  disabled={{ after: today }}
                  className='mx-auto mt-2'
                  components={WORKFLOW_CALENDAR_COMPONENTS}
                  autoFocus
                />
              </WorkflowDateInteractionContext.Provider>
            </div>
            <p className='border-t pt-2 text-xs text-muted-foreground'>已选：{selectedDateLabel}</p>
          </div>

          {fileInputs.length > 0 && (
            <div className='space-y-3'>
              <div>
                <div className='flex items-center gap-2'>
                  <p className='text-sm font-medium'>任务材料</p>
                  {materialVersion !== null && (
                    <Badge variant='secondary'>当前业务版本 V{materialVersion}</Badge>
                  )}
                  {materialsLoading && <Badge variant='outline'>正在读取已保存文件</Badge>}
                </div>
              </div>
              {fileInputs.map((input) => {
                const entries = materials[input.role] ?? [];
                return (
                  <div key={input.role} className='rounded-lg border p-3'>
                    <div className='flex items-start justify-between gap-3'>
                      <div className='min-w-0'>
                        <p className='text-sm font-medium'>
                          {input.name}
                          {input.role === 'profit_loss_ledgers' && '（每年一份）'}
                          {input.required && <span className='ml-1 text-destructive'>*</span>}
                        </p>
                        {entries.length > 0 ? (
                          <PaginatedCollection
                            ariaLabel={`${input.name}已选材料`}
                            className='mt-2'
                            contentClassName='space-y-1 text-xs text-muted-foreground'
                          >
                            {entries.map((material) => (
                              <div
                                key={material.id}
                                className='flex items-center gap-2 rounded-md bg-muted/40 px-2 py-1'
                              >
                                <span className='min-w-0 flex-1 truncate'>{material.name}</span>
                                <Badge variant='outline' className='shrink-0 font-normal'>
                                  {material.source === 'saved' ? '已保存，将复用' : '本次上传'}
                                </Badge>
                                <Button
                                  type='button'
                                  variant='ghost'
                                  size='icon'
                                  className='min-h-11 min-w-11 shrink-0 text-muted-foreground hover:text-destructive'
                                  aria-label={`从本次任务移除 ${material.name}`}
                                  title={
                                    material.source === 'saved'
                                      ? '仅从本次任务移除'
                                      : '删除本次上传文件'
                                  }
                                  disabled={
                                    Boolean(uploadingRole) || Boolean(deletingFileId) || working
                                  }
                                  onClick={() => void removeMaterial(input.role, material)}
                                >
                                  {deletingFileId === material.id ? (
                                    <Icons.spinner className='size-4 animate-spin' />
                                  ) : (
                                    <Icons.trash className='size-4' />
                                  )}
                                </Button>
                              </div>
                            ))}
                          </PaginatedCollection>
                        ) : (
                          <p className='mt-2 text-xs text-muted-foreground'>
                            {materialsLoading ? '正在检查平台已保存文件…' : '当前没有可复用文件。'}
                          </p>
                        )}
                      </div>
                      <label className='shrink-0 cursor-pointer rounded-md border px-3 py-2 text-xs font-medium transition-colors hover:bg-muted'>
                        {uploadingRole === input.role
                          ? '上传中…'
                          : entries.length
                            ? input.multiple ? '新增/替换' : '替换当前表'
                            : '选择文件'}
                        <input
                          type='file'
                          className='sr-only'
                          accept={input.extensions?.map((item) => `.${item}`).join(',')}
                          multiple={input.multiple}
                          disabled={
                            materialsLoading ||
                            Boolean(uploadingRole) ||
                            Boolean(deletingFileId) ||
                            working
                          }
                          onChange={(event) =>
                            void uploadMaterial(input.role, input.multiple, event)
                          }
                        />
                      </label>
                    </div>
                  </div>
                );
              })}
              {materialsError && (
                <Alert variant='destructive'>
                  <AlertTitle>已保存任务材料加载失败</AlertTitle>
                  <AlertDescription className='space-y-2'>
                    <p>{materialsError}</p>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      onClick={() => {
                        setMaterialsError('');
                        setMaterialsRefreshKey((current) => current + 1);
                      }}
                    >
                      重新读取
                    </Button>
                  </AlertDescription>
                </Alert>
              )}
            </div>
          )}

          {error && (
            <Alert variant='destructive'>
              <AlertTitle>任务未启动</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button
            type='button'
            className='min-h-10 w-full sm:w-auto'
            onClick={() => void start()}
            disabled={
              working ||
              Boolean(uploadingRole) ||
              Boolean(deletingFileId) ||
              materialsLoading ||
              Boolean(materialsError) ||
              (requiresZhiyunCredential && !zhiyunCredentialConfigured) ||
              !skillId ||
              selectedDates.length === 0
            }
          >
            {working
              ? '提交任务…'
              : selectedDates.length > 1
                ? `开始 ${selectedDates.length} 个核销日任务`
                : '开始任务'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>最近任务</CardTitle>
        </CardHeader>
        <CardContent className='space-y-2'>
          {recentTasks.length ? (
            <PaginatedCollection ariaLabel='最近任务' contentClassName='space-y-2'>
              {recentTasks.map((task) => {
              const isBatch = task.kind === 'batch';
              const target = isBatch
                ? `/dashboard/workflows/batches/${encodeURIComponent(task.item.id)}`
                : `/dashboard/workflows/${encodeURIComponent(task.item.id)}`;
              const destructive = task.item.state === 'failed';
              return (
                <Link
                  key={`${task.kind}-${task.item.id}`}
                  href={target}
                  className='block rounded-lg border p-3 transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring'
                >
                  <div className='flex items-start justify-between gap-2'>
                    <span className='font-medium'>{task.item.skill_name}</span>
                    <Badge variant={destructive ? 'destructive' : 'outline'}>
                      {isBatch ? batchStateLabel(task.item.state) : stageLabel(task.item.stage)}
                    </Badge>
                  </div>
                  <p className='mt-1 text-sm font-medium'>{task.item.display_id}</p>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {isBatch
                      ? `${task.item.reconciliation_dates.length} 个核销日批次`
                      : task.item.reconciliation_date || '日期未设置'}{' '}
                    · {task.item.progress}% · {task.item.progress_message}
                  </p>
                </Link>
              );
              })}
            </PaginatedCollection>
          ) : (
            <p className='rounded-lg border border-dashed p-4 text-sm text-muted-foreground'>
              暂无任务记录。
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
