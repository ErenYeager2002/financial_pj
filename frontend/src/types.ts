export type UserRole = 'finance_user' | 'skill_admin'

export interface UserSession {
  user_id: string
  display_name: string
  role: UserRole
  department_id: string
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
  schema_version: number
  id: string
  name: string
  version: string
  status: 'draft' | 'published' | 'disabled'
  category: string
  description: string
  blocked_reason?: string
  tags: string[]
  file_inputs: FileInputSpec[]
  input_schema: {
    type: 'object'
    properties?: Record<string, JsonSchemaProperty>
    required?: string[]
  }
  output_schema: Record<string, unknown>
  handler: {
    adapter: 'python' | 'rpa' | 'http'
    entrypoint?: string
    endpoint?: string
    worker_pool?: string
  }
  runtime: {
    timeout_seconds: number
    memory_mb: number
    concurrency_limit: number
    network_access: boolean
  }
  risk: {
    level: 'read_only' | 'write' | 'external_action'
    requires_confirmation: boolean
  }
  permissions: {
    run: string
    manage: string
  }
  skill_hash: string
  commit_sha: string
  source: string
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
