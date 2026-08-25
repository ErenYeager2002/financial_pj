import type {
  AdminAssistantProfile as GeneratedAdminAssistantProfile,
  AdminSkillDetail as GeneratedAdminSkillDetail,
  AdminUserCreate as GeneratedAdminUserCreate,
  AdminUserRead as GeneratedAdminUser,
  AdminUserUpdate as GeneratedAdminUserUpdate,
  ApprovalDecisionRequest as GeneratedApprovalDecisionRequest,
  ApprovalRecord as GeneratedApprovalRecord,
  AssistantConversationRead as GeneratedAssistantConversation,
  AssistantMessageRead as GeneratedAssistantMessage,
  AssistantStatus as GeneratedAssistantStatus,
  AuditEventRead as GeneratedAuditEvent,
  FeatureControlRead as GeneratedFeatureControl,
  ModelConnectionRead as GeneratedModelConnection,
  ModelProviderRead as GeneratedModelProvider,
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
  TaskCenterItem as GeneratedTaskCenterItem,
  TaskCenterPage as GeneratedTaskCenterPage,
  TaskCenterStateCounts as GeneratedTaskCenterStateCounts,
  ServiceCredentialRead as GeneratedServiceCredentialRead,
  SkillDetail as GeneratedSkillDetail,
  SkillAvailabilityRead as GeneratedSkillAvailability,
  SkillPermissionRead as GeneratedSkillPermission,
  SkillPermissionWrite as GeneratedSkillPermissionWrite,
  SkillReleaseInboxItem as GeneratedSkillReleaseInboxItem,
  SkillReleaseMetadataUpdate as GeneratedSkillReleaseMetadataUpdate,
  SkillReleaseRead as GeneratedSkillRelease,
  SkillRolloutRead as GeneratedSkillRollout,
  SkillSourceBindingRead as GeneratedSkillSourceBinding,
  SkillSourceDiscoveryRead as GeneratedSkillSourceDiscovery,
  SkillSourceUpdateCheckRead as GeneratedSkillSourceUpdateCheck,
  SkillSummary as GeneratedSkillSummary,
  StepRunRead as GeneratedStepRun,
  TaskDiscoveryCheckQueued as GeneratedTaskDiscoveryCheckQueued,
  TaskDiscoveryCheckRequest as GeneratedTaskDiscoveryCheckRequest,
  TaskReminderBoard as GeneratedTaskReminderBoard,
  TaskReminderSubscriptionRead as GeneratedTaskReminderSubscription,
  TaskReminderSubscriptionWrite as GeneratedTaskReminderSubscriptionWrite,
  WorkflowDefinitionRead as GeneratedWorkflowDefinition,
  WorkflowFetchedDataRead as GeneratedWorkflowFetchedData,
  WorkflowMaterialSetRead as GeneratedWorkflowMaterialSet,
  WorkflowRead as GeneratedWorkflowRead,
  WorkflowReusableFilesRead as GeneratedWorkflowReusableFilesRead,
  WorkflowAgentContext as GeneratedWorkflowAgentContext,
  TaskDraft as GeneratedTaskDraft,
  Workbench as GeneratedWorkbench
} from './generated';

export type PlatformUser = GeneratedPlatformUser;
export type AssistantStatus = GeneratedAssistantStatus;
export type AssistantConversation = GeneratedAssistantConversation;
export type AssistantMessage = GeneratedAssistantMessage;
export type AdminAssistantProfile = GeneratedAdminAssistantProfile;
export type AdminUser = GeneratedAdminUser;
export type AdminUserCreate = GeneratedAdminUserCreate;
export type AdminUserUpdate = GeneratedAdminUserUpdate;
export type ModelConnection = GeneratedModelConnection;
export type ModelProvider = GeneratedModelProvider;
export type ObservabilitySummary = GeneratedObservabilitySummary;
export type PlatformSession = GeneratedPlatformUser;
export type SkillSummary = GeneratedSkillSummary;
export type SkillDetail = GeneratedSkillDetail;
export type SkillAvailability = GeneratedSkillAvailability;
export type SkillPermission = GeneratedSkillPermission;
export type SkillPermissionWrite = GeneratedSkillPermissionWrite;
export type SkillRelease = GeneratedSkillRelease;
export type SkillReleaseInboxItem = GeneratedSkillReleaseInboxItem;
export type SkillReleaseMetadataUpdate = GeneratedSkillReleaseMetadataUpdate;
export type SkillRollout = GeneratedSkillRollout;
export type SkillSourceBinding = GeneratedSkillSourceBinding;
export type SkillSourceDiscovery = GeneratedSkillSourceDiscovery;
export type SkillSourceUpdateCheck = GeneratedSkillSourceUpdateCheck;
export type AdminSkillDetail = GeneratedAdminSkillDetail;
export type RunSummary = GeneratedRunSummary;
export type ServiceCredentialRead = GeneratedServiceCredentialRead;
export type RunCreate = GeneratedRunCreate;
export type RunDetail = GeneratedRunDetail;
export type RunPage = GeneratedRunPage;
export type TaskCenterItem = GeneratedTaskCenterItem;
export type TaskCenterPage = GeneratedTaskCenterPage;
export type TaskCenterStateCounts = GeneratedTaskCenterStateCounts;
export type RunActionResponse = GeneratedRunActionResponse;
export type RunApproval = GeneratedRunApproval;
export type RunEvent = GeneratedRunEvent;
export type RunStep = GeneratedStepRun;
export type TaskDiscoveryCheckQueued = GeneratedTaskDiscoveryCheckQueued;
export type TaskDiscoveryCheckRequest = GeneratedTaskDiscoveryCheckRequest;
export type TaskReminderBoard = GeneratedTaskReminderBoard;
export type TaskReminderSubscription = GeneratedTaskReminderSubscription;
export type TaskReminderSubscriptionWrite = GeneratedTaskReminderSubscriptionWrite;
export type WorkflowDefinition = GeneratedWorkflowDefinition;
export type WorkflowFetchedData = GeneratedWorkflowFetchedData;
export type WorkflowMaterialSet = GeneratedWorkflowMaterialSet;
export type WorkflowRead = GeneratedWorkflowRead;
export type WorkflowReusableFilesRead = GeneratedWorkflowReusableFilesRead;
export type WorkflowBatchRead = import('./generated').WorkflowBatchRead;
export type WorkflowAgentContext = GeneratedWorkflowAgentContext;
export type PlatformFile = GeneratedPlatformFile;
export type PlatformFileDetail = GeneratedPlatformFileDetail;
export type PlatformFilePage = GeneratedPlatformFilePage;
export type Workbench = GeneratedWorkbench;
export type AuditEvent = GeneratedAuditEvent;
export type FeatureControl = GeneratedFeatureControl;
export type TaskDraft = GeneratedTaskDraft;
export type ApprovalRecord = GeneratedApprovalRecord;
export type ApprovalDecisionRequest = GeneratedApprovalDecisionRequest;

export interface PlatformErrorBody {
  detail: string;
}
