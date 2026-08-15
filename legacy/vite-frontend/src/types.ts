export type UserRole = 'finance_user' | 'skill_admin'

export interface UserSession {
  user_id: string
  username: string
  display_name: string
  role: UserRole
  department_id: string
  must_change_password?: boolean
}

export interface SkillPermission {
  skill_id: string
  can_run: boolean
  can_upload: boolean
  can_create_draft: boolean
  requires_approval: boolean
}

export interface AdminUser {
  id: string
  username: string
  display_name: string
  role: UserRole
  department_id: string
  status: 'active' | 'disabled'
  must_change_password: boolean
  permissions: SkillPermission[]
  created_at: string
}

export interface FileInputSpec {
  role: string
  name: string
  description: string
  required: boolean
  multiple: boolean
  min_files?: number
  extensions: string[]
  max_size_mb?: number
}

export interface JsonSchemaProperty {
  type?: 'string' | 'number' | 'integer' | 'boolean'
  title?: string
  description?: string
  default?: string | number | boolean
  minimum?: number
  maximum?: number
  enum?: Array<string | number>
}

export interface SkillManifest {
  schema_version?: number
  id: string
  name: string
  version?: string
  status?: 'draft' | 'published' | 'disabled'
  category?: string
  categories?: string[]
  description: string
  estimated_minutes?: number
  output_summary?: string
  action_label?: string
  popular?: boolean
  execution_mode?: 'standard' | 'guided_workflow'
  blocked_reason?: string
  tags: string[]
  file_inputs: FileInputSpec[]
  input_schema: {
    type: 'object'
    properties?: Record<string, JsonSchemaProperty>
    required?: string[]
  }
  output_schema?: Record<string, unknown>
  handler?: {
    adapter: 'python' | 'rpa' | 'http' | 'workflow'
    entrypoint?: string
    endpoint?: string
    worker_pool?: string
  }
  runtime?: {
    timeout_seconds: number
    memory_mb: number
    concurrency_limit: number
    network_access: boolean
  }
  risk: {
    level: 'read_only' | 'write' | 'external_action'
    requires_confirmation: boolean
    modifies_uploaded_files?: boolean
  }
  progress_stages?: Array<{ key: string; label: string }>
  result_presentation?: { metrics: Array<{ key: string; label: string }> }
  permissions?: {
    run: string
    manage: string
  }
  skill_hash?: string
  commit_sha?: string
  source?: string
}

export interface UploadedFile {
  id: string
  name: string
  role: string
  size_bytes: number
  sha256: string
  kind: string
}

export interface ModelConnection {
  id: string
  provider: string
  provider_name: string
  api_key_hint: string
  models: string[]
  selected_model: string
  status: string
  last_checked_at: string
  created_at: string
}

export type ProviderDiscoveryMode = 'api' | 'manual' | 'hybrid'

export interface ModelProviderInfo {
  id: string
  name: string
  discovery_mode: ProviderDiscoveryMode
  allow_manual_model: boolean
  admin_only: boolean
}

export interface ServiceCredential {
  service: string
  configured: boolean
  account_hint: string
  updated_at?: string
}

export interface RunResultFile {
  name: string
  file_id: string
  size_bytes: number
  sha256: string
  download_url: string
}

export interface RunRecord {
  id: string
  owner_id: string
  owner_name: string
  skill_id: string
  skill_name: string
  skill_version: string
  skill_commit: string
  model_provider: string
  model_name: string
  state: string
  progress: number
  progress_message: string
  message: string
  parameters: Record<string, unknown>
  files: Record<string, unknown>
  result: {
    status?: string
    summary?: Record<string, number | string>
    output_files?: RunResultFile[]
    warnings?: string[]
  }
  error_message: string
  confirmation_required: boolean
  confirmed_by: string
  cancel_requested: boolean
  created_at: string
  queued_at?: string
  started_at?: string
  finished_at?: string
}

export interface RunEvent {
  id: number
  type: string
  state: string
  progress?: number
  message: string
  data: Record<string, unknown>
  created_at: string
}

export interface WorkflowMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  data: Record<string, unknown>
  created_at: string
}

export interface WorkflowAction {
  id: string
  name: string
  state: string
  error_message: string
  created_at: string
  finished_at?: string
}

export interface WorkflowFile {
  file_id: string
  name: string
  size_bytes: number
  sha256: string
}

export interface WorkflowRecord {
  id: string
  owner_id: string
  skill_id: string
  skill_name: string
  skill_version: string
  model_provider: string
  model_name: string
  state: string
  stage: string
  reconciliation_date: string
  batch_id?: string
  batch_sequence: number
  requires_confirmation: boolean
  files: Record<string, WorkflowFile[]>
  artifacts: RunResultFile[]
  progress: number
  progress_message: string
  error_message: string
  messages: WorkflowMessage[]
  actions: WorkflowAction[]
  created_at: string
  updated_at: string
}

export interface WorkflowBatchRecord {
  id: string
  owner_id: string
  skill_id: string
  skill_name: string
  skill_version: string
  model_provider: string
  model_name: string
  reconciliation_dates: string[]
  state: string
  progress: number
  progress_message: string
  error_message: string
  workflows: WorkflowRecord[]
  created_at: string
  updated_at: string
}

export interface PlatformHealth {
  status: string
  name: string
  environment: string
  skills: number
  registry_errors: Array<{ path: string; error: string }>
  configured_workers: Record<string, number>
  configured_execution_capacity: number
}
