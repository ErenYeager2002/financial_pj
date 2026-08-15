import type {
  AdminAssistantProfile as GeneratedAdminAssistantProfile,
  AdminSkillDetail as GeneratedAdminSkillDetail,
  AdminUserCreate as GeneratedAdminUserCreate,
  AdminUserRead as GeneratedAdminUser,
  AdminUserUpdate as GeneratedAdminUserUpdate,
  ApprovalDecisionRequest as GeneratedApprovalDecisionRequest,
  ApprovalRecord as GeneratedApprovalRecord,
  AssistantStatus as GeneratedAssistantStatus,
  AuditEventRead as GeneratedAuditEvent,
  ModelConnectionRead as GeneratedModelConnection,
  ObservabilitySummary as GeneratedObservabilitySummary,
  PlatformFile as GeneratedPlatformFile,
  PlatformFileDetail as GeneratedPlatformFileDetail,
  PlatformFilePage as GeneratedPlatformFilePage,
  PlatformUser as GeneratedPlatformUser,
  RunActionResponse as GeneratedRunActionResponse,
  RunApprovalRead as GeneratedRunApproval,
  RunCreate as GeneratedRunCreate,
  RunDetail as GeneratedRunDetail,
  RunEventRead as GeneratedRunEvent,
  RunPage as GeneratedRunPage,
  RunSummary as GeneratedRunSummary,
  SkillDetail as GeneratedSkillDetail,
  SkillPermissionRead as GeneratedSkillPermission,
  SkillPermissionWrite as GeneratedSkillPermissionWrite,
  SkillReleaseInboxItem as GeneratedSkillReleaseInboxItem,
  SkillReleaseMetadataUpdate as GeneratedSkillReleaseMetadataUpdate,
  SkillReleaseRead as GeneratedSkillRelease,
  SkillSummary as GeneratedSkillSummary,
  StepRunRead as GeneratedStepRun,
  WorkflowDefinitionRead as GeneratedWorkflowDefinition,
  TaskDraft as GeneratedTaskDraft,
  Workbench as GeneratedWorkbench
} from './generated';

export type PlatformUser = GeneratedPlatformUser;
export type AssistantStatus = GeneratedAssistantStatus;
export type AdminAssistantProfile = GeneratedAdminAssistantProfile;
export type AdminUser = GeneratedAdminUser;
export type AdminUserCreate = GeneratedAdminUserCreate;
export type AdminUserUpdate = GeneratedAdminUserUpdate;
export type ModelConnection = GeneratedModelConnection;
export type ObservabilitySummary = GeneratedObservabilitySummary;
export type PlatformSession = GeneratedPlatformUser;
export type SkillSummary = GeneratedSkillSummary;
export type SkillDetail = GeneratedSkillDetail;
export type SkillPermission = GeneratedSkillPermission;
export type SkillPermissionWrite = GeneratedSkillPermissionWrite;
export type SkillRelease = GeneratedSkillRelease;
export type SkillReleaseInboxItem = GeneratedSkillReleaseInboxItem;
export type SkillReleaseMetadataUpdate = GeneratedSkillReleaseMetadataUpdate;
export type AdminSkillDetail = GeneratedAdminSkillDetail;
export type RunSummary = GeneratedRunSummary;
export type RunCreate = GeneratedRunCreate;
export type RunDetail = GeneratedRunDetail;
export type RunPage = GeneratedRunPage;
export type RunActionResponse = GeneratedRunActionResponse;
export type RunApproval = GeneratedRunApproval;
export type RunEvent = GeneratedRunEvent;
export type RunStep = GeneratedStepRun;
export type WorkflowDefinition = GeneratedWorkflowDefinition;
export type PlatformFile = GeneratedPlatformFile;
export type PlatformFileDetail = GeneratedPlatformFileDetail;
export type PlatformFilePage = GeneratedPlatformFilePage;
export type Workbench = GeneratedWorkbench;
export type AuditEvent = GeneratedAuditEvent;
export type TaskDraft = GeneratedTaskDraft;
export type ApprovalRecord = GeneratedApprovalRecord;
export type ApprovalDecisionRequest = GeneratedApprovalDecisionRequest;

export interface PlatformErrorBody {
  detail: string;
}
