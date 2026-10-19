export type Role = 'admin' | 'leader' | 'member' | 'viewer'
export type DataClassification = 'public' | 'internal' | 'private' | 'restricted'
export type ChatModelPolicy = 'inherit'

export type JsonRecord = Record<string, unknown>

export interface User {
  id: string
  email: string
  display_name: string
  status: string
  is_super_admin: boolean
  is_builtin: boolean
  created_at: string
}

export type FeedbackType =
  | 'useful'
  | 'not_useful'
  | 'citation_error'
  | 'knowledge_gap'

export interface Membership {
  team_id: string
  team_name: string
  role: Role
  status: string
}

export interface InvitationView {
  id: string
  team_id: string
  team_name: string
  email: string
  role: Role
  status: string
  expires_at: string
  created_at: string
  accepted_at: string | null
  token?: string
  invitation_url?: string
}

export interface Me {
  user: User
  memberships: Membership[]
}

export interface Team {
  id: string
  name: string
  description: string | null
  role: Role
  version: number
  created_at: string
  updated_at: string
}

export interface KnowledgeBase {
  id: string
  team_id: string
  name: string
  description: string | null
  status: string
  default_model_policy_mode: string
  document_count: number
  version: number
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseMemberView {
  kb_id: string
  user_id: string
  email: string
  display_name: string
  status: string
}

export interface KnowledgeBaseMembersUpdateInput {
  team_id: string
  kb_id: string
  user_ids: string[]
}

export interface DocumentView {
  id: string
  knowledge_base_id: string
  file_name: string
  source_type: string
  product: string | null
  version_values: string[]
  visibility: string
  data_classification: string
  doc_status: string
  deleted_at: string | null
  purged_at: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface DocumentDetailView extends DocumentView {
  owner_user_id: string
  current_version_id: string | null
  source_uri: string | null
  version_family: string | null
}

export interface DocumentVersion {
  id: string
  document_id?: string
  content_fingerprint: string
  file_size_bytes: number
  status: string
  index_generation: string | null
  chunk_count: number
  created_at: string
}

export interface DocumentGrantView {
  id: string
  user_id: string
  granted_by: string
  created_at: string
}

export interface ChunkView {
  id: string
  document_id: string
  content: string
  heading_path: string[]
  source_locator: JsonRecord
  status: string
  version: number
  created_at: string
  updated_at: string
}

export interface ChunkHistoryView {
  id: string
  action: string
  old_content: string | null
  new_content: string | null
  actor_id: string
  created_at: string
}

export interface IngestionRun {
  id: string
  document_version_id: string
  status: string
  current_stage: string | null
  stage_progress_pct: number
  error_code: string | null
  retryable: boolean
  created_at: string
  updated_at: string
}

export interface ChatView {
  id: string
  team_id: string
  user_id: string
  title: string
  knowledge_base_ids: string[]
  version: number
  created_at: string
  updated_at: string
}

export interface CitationView {
  citation_id?: string
  chunk_id?: string
  document_version_id?: string
  document_name?: string
  excerpt?: string
  heading_path?: string[]
  page_no?: number
  source_url?: string
  source_locator?: JsonRecord
}

export interface MessageView {
  id: string
  chat_id: string
  role: string
  content: string
  status: string
  trace_id: string | null
  citation_ids?: Array<string | CitationView>
  citations?: Array<string | CitationView>
  citation?: CitationView
  refusal_reason: string | null
  created_at: string
}

export interface ChatFilters {
  knowledge_base_ids: string[]
  product: string | null
  version_values: string[]
}

export interface AskChatInput {
  team_id: string
  chat_id: string
  provider_id: string
  model_id: string
  question: string
  filters: ChatFilters
  model_policy: ChatModelPolicy
  stream: boolean
}

export interface FacetView {
  products: string[]
  versions: string[]
  sources: string[]
  knowledge_base_ids: string[]
}

export interface TeamMemberView {
  team_id: string
  user_id: string
  email: string
  display_name: string
  role: Exclude<Role, 'admin'>
  status: string
  joined_at: string
}

export interface MemberUpdateInput {
  role?: Exclude<Role, 'admin'>
  status?: 'active' | 'disabled'
}

export interface TransferDocumentsInput {
  team_id: string
  from_user_id: string
  to_user_id: string
}

export interface TransferDocumentsResult {
  from_user_id: string
  to_user_id: string
  transferred_documents: number
  transferred_chunks: number
}

export interface SourceConnection {
  id: string
  team_id: string
  kb_id: string
  source_type: string
  repo_url: string
  branch: string
  path_filters: string[]
  credentials_id: string | null
  status: string
  sync_cursor: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface CredentialView {
  id: string
  name: string
  secret_masked: string
  created_at: string
}

export interface ModelPolicy {
  mode: string
  allowed_provider_ids: string[]
  max_data_classification: string
  allow_chat_history: boolean
  allow_document_metadata: boolean
  require_redaction: boolean
  version: number
}

export interface ModelProvider {
  id: string
  name: string
  provider_type: ProviderType | string
  base_url?: string
  model_ids?: string[]
  status: string
  has_api_key: boolean
  api_key_masked?: string
  api_key_updated_at?: string | null
}

export type ProviderType =
  | 'openai_responses'
  | 'openai_chat_completions'
  | 'anthropic_messages'

export interface ProviderModelsInput {
  provider_type: ProviderType
  base_url: string
  api_key: string
}

export interface ModelCall {
  id: string
  provider_id: string | null
  model_id: string
  purpose: string
  classification: string
  external: boolean
  cost_micros: number
  latency_ms: number
  created_at: string
}

export interface TraceView {
  id: string
  trace_id: string
  team_id: string
  chat_id: string
  message_id: string
  engine_mode: string
  original_query: string
  rewritten_query: string | null
  filters: JsonRecord
  bm25_candidates: JsonRecord[]
  dense_candidates: JsonRecord[]
  rrf_candidates: JsonRecord[]
  rerank_candidates: JsonRecord[]
  final_context: JsonRecord[]
  stage_latency_ms: Record<string, number>
  degraded: boolean
  error_code: string | null
  model: JsonRecord
  feedback: TraceFeedback[]
  created_at: string
}

export interface TraceFeedback {
  id: string
  feedback_type: string
  comment: string | null
  created_at: string
}

export interface EvaluationDataset {
  id: string
  name: string
  description: string | null
  case_count: number
  version: number
  created_at?: string
}

export interface EvaluationCase {
  id: string
  dataset_id: string
  query_id: string
  query_type: string
  query: string
  relevant_chunk_ids: string[]
  filters: JsonRecord
  relevance: JsonRecord
  created_at: string
}

export interface EvaluationRun {
  id: string
  dataset_id: string
  engine_mode: string
  status: string
  baseline_run_id: string | null
  provider_id: string
  model_id: string
  created_at: string
}

export interface EvaluationReport {
  run_id: string
  status: string
  metrics: Record<string, number | JsonRecord>
  report: JsonRecord
}

export interface AuditLogView {
  id: string
  team_id: string
  actor_id: string
  action: string
  resource_type: string
  resource_id: string
  details: JsonRecord
  created_at: string
}

export interface IndexGeneration {
  id: string
  team_id: string
  status: string
  chunk_count: number
  embedding_model: string
  error_message: string | null
  validation_errors: string[]
  created_at: string
  validated_at: string | null
  activated_at: string | null
}

export interface GenerationValidation {
  generation_id: string
  passed: boolean
  errors: string[]
  checked_chunks: number
  validated_at: string | null
}

export interface GenerationReindexRun {
  generation_id: string
  status: string
  execution_mode: 'inline' | 'celery'
  task_id: string | null
  passed: boolean | null
  checked_chunks: number
  errors: string[]
}

export interface GenerationReindexResult {
  generation: IndexGeneration
  run: GenerationReindexRun
}

export interface HealthView {
  status: string
}

export interface VersionView {
  version: string
}

export interface PageMeta {
  next_cursor: string | null
  has_more: boolean
  request_id: string
}

export interface Envelope<T> {
  data: T
  meta: {
    request_id: string
  }
}

export interface PageEnvelope<T> {
  data: T[]
  meta: PageMeta
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user?: User
}

export interface TeamCreateInput {
  name: string
  description?: string | null
}

export interface TeamUpdateInput extends TeamCreateInput {
  team_id: string
}

export interface KnowledgeBaseInput {
  team_id: string
  name: string
  description?: string | null
}

export interface KnowledgeBaseUpdateInput extends KnowledgeBaseInput {
  kb_id: string
}

export interface PasswordChangeInput {
  old_password: string
  new_password: string
}

export interface AdminUserCreateInput {
  email: string
  display_name: string
  password: string
  team_id: string
  role: 'leader' | 'member' | 'viewer'
}

export interface AdminUserUpdateInput {
  user_id: string
  status?: 'active' | 'disabled'
  team_id?: string
  role?: 'leader' | 'member' | 'viewer'
}

export interface AdminUserUpdateResult extends User {
  membership?: Membership
}

export interface AdminUser extends User {
  memberships: Membership[]
}
