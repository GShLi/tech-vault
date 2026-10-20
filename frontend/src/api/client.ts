import axios, { AxiosError, AxiosHeaders } from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'

import type {
  AuditLogView,
  ChunkHistoryView,
  ChunkView,
  CredentialView,
  DocumentDetailView,
  DocumentGrantView,
  DocumentVersion,
  DocumentView,
  Envelope,
  EvaluationCase,
  EvaluationDataset,
  EvaluationReport,
  EvaluationRun,
  GenerationReindexResult,
  GenerationValidation,
  HealthView,
  IndexGeneration,
  IngestionRun,
  InvitationView,
  KnowledgeBase,
  KnowledgeBaseInput,
  KnowledgeBaseMemberView,
  KnowledgeBaseMembersUpdateInput,
  KnowledgeBaseUpdateInput,
  LoginResponse,
  Me,
  MessageView,
  ModelCall,
  ModelPolicy,
  ModelProvider,
  ProviderModelsInput,
  ProviderType,
  PageEnvelope,
  AdminUserCreateInput,
  AdminUser,
  PasswordChangeInput,
  Role,
  SourceConnection,
  Team,
  TeamCreateInput,
  TeamUpdateInput,
  AdminUserUpdateInput,
  AdminUserUpdateResult,
  FeedbackType,
  TraceView,
  User,
  VersionView,
  ChatView,
  FacetView,
  MemberUpdateInput,
  TeamMemberView,
  TransferDocumentsInput,
  TransferDocumentsResult,
} from '@/types/api'

export type {
  ChunkHistoryView,
  ChunkView,
  DocumentDetailView,
  DocumentGrantView,
  DocumentVersion,
  DocumentView,
  EvaluationCase,
  EvaluationDataset,
  EvaluationReport,
  EvaluationRun,
  GenerationReindexResult,
  IndexGeneration,
  IngestionRun,
  InvitationView,
  MessageView,
  ModelPolicy,
  ModelProvider,
  SourceConnection,
  TraceView,
  ChatView,
} from '@/types/api'

export const TOKEN_STORAGE_KEY = 'techvault.access_token'

export function getAccessToken(): string | null {
  return window.sessionStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setAccessToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearAccessToken(): void {
  window.sessionStorage.removeItem(TOKEN_STORAGE_KEY)
}

export class ApiRequestError extends Error {
  readonly code: string
  readonly requestId: string
  readonly status: number
  readonly details: Record<string, unknown>

  constructor(
    message: string,
    code = 'UNKNOWN_ERROR',
    requestId = '',
    status = 0,
    details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiRequestError'
    this.code = code
    this.requestId = requestId
    this.status = status
    this.details = details
  }
}

export function normalizeApiError(error: unknown): ApiRequestError {
  if (error instanceof ApiRequestError) return error

  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<{
      error?: { code?: string; message?: string; details?: Record<string, unknown>; request_id?: string }
    }>
    const payload = axiosError.response?.data?.error
    return new ApiRequestError(
      payload?.message ?? axiosError.message ?? '请求失败',
      payload?.code ?? 'NETWORK_ERROR',
      payload?.request_id ?? String(axiosError.response?.headers?.['x-request-id'] ?? ''),
      axiosError.response?.status ?? 0,
      payload?.details ?? {},
    )
  }

  return new ApiRequestError(error instanceof Error ? error.message : '请求失败', 'UNKNOWN_ERROR')
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
  withCredentials: true,
})

interface RetryableRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
  _skipAuthRefresh?: boolean
}

let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const response = await http.post<Envelope<LoginResponse>>(
    '/auth/refresh',
    {},
    { _skipAuthRefresh: true } as RetryableRequestConfig,
  )
  const token = response.data.data.access_token
  setAccessToken(token)
  return token
}

http.interceptors.request.use((config) => {
  const requestConfig = config as RetryableRequestConfig
  const token = getAccessToken()
  if (token && !requestConfig._skipAuthRefresh) {
    config.headers = config.headers ?? new AxiosHeaders()
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryableRequestConfig | undefined
    const isRefreshRequest = config?.url === '/auth/refresh'
    if (
      error.response?.status !== 401 ||
      config === undefined ||
      config._retry ||
      config._skipAuthRefresh ||
      isRefreshRequest
    ) {
      return Promise.reject(normalizeApiError(error))
    }

    config._retry = true
    try {
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null
      })
      await refreshPromise
      return await http(config)
    } catch (refreshError) {
      clearAccessToken()
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event('techvault:session-expired'))
      }
      return Promise.reject(normalizeApiError(refreshError))
    }
  },
)

async function getData<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await http.get<Envelope<T>>(url, { params })
  return response.data.data
}

async function getPage<T>(url: string, params?: Record<string, unknown>): Promise<PageEnvelope<T>> {
  const response = await http.get<PageEnvelope<T>>(url, { params })
  return response.data
}

export async function loadAllPages<T>(
  loadPage: (cursor: string | null) => Promise<PageEnvelope<T>>,
): Promise<T[]> {
  const rows: T[] = []
  let cursor: string | null = null
  do {
    const page = await loadPage(cursor)
    rows.push(...page.data)
    cursor = page.meta.has_more ? page.meta.next_cursor : null
  } while (cursor)
  return rows
}

async function postData<T>(url: string, body: object, headers?: Record<string, string>): Promise<T> {
  const response = await http.post<Envelope<T>>(url, body, { headers })
  return response.data.data
}

export const api = {
  login(body: { email: string; password: string }): Promise<LoginResponse> {
    return postData<LoginResponse>('/auth/login', body)
  },
  changePassword(body: PasswordChangeInput) {
    return postData<Record<string, never>>('/auth/password/change', body)
  },
  updateProfile(displayName: string): Promise<User> {
    return postData<User>('/users/update', { display_name: displayName })
  },
  async logout(): Promise<void> {
    await http.post('/auth/logout')
  },
  me(): Promise<Me> {
    return getData<Me>('/auth/me')
  },
  listTeams(cursor?: string | null, limit = 100): Promise<PageEnvelope<Team>> {
    return getPage<Team>('/teams', { limit, ...(cursor ? { cursor } : {}) })
  },
  getTeam(teamId: string): Promise<Team> {
    return getData<Team>('/teams/detail', { team_id: teamId })
  },
  createTeam(body: TeamCreateInput): Promise<Team> {
    return postData<Team>('/teams/create', body)
  },
  updateTeam(body: TeamUpdateInput, version: number): Promise<Team> {
    return postData<Team>('/teams/update', body, { 'If-Match': String(version) })
  },
  createUser(body: AdminUserCreateInput) {
    return postData<Record<string, unknown>>('/admin/users/create', body)
  },
  listUsers(cursor?: string | null, limit = 20): Promise<PageEnvelope<AdminUser>> {
    return getPage<AdminUser>('/admin/users', {
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  updateUser(body: AdminUserUpdateInput): Promise<AdminUserUpdateResult> {
    return postData<AdminUserUpdateResult>('/admin/users/update', body)
  },

  listKbs(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<KnowledgeBase>> {
    return getPage<KnowledgeBase>('/kbs', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getKb(teamId: string, kbId: string): Promise<KnowledgeBase> {
    return getData<KnowledgeBase>('/kbs/detail', { team_id: teamId, kb_id: kbId })
  },
  listKbMembers(
    teamId: string,
    kbId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<KnowledgeBaseMemberView>> {
    return getPage<KnowledgeBaseMemberView>('/kbs/members', {
      team_id: teamId,
      kb_id: kbId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  updateKbMembers(
    body: KnowledgeBaseMembersUpdateInput,
  ): Promise<KnowledgeBaseMemberView[]> {
    return postData<KnowledgeBaseMemberView[]>('/kbs/members/update', body)
  },
  createKb(body: KnowledgeBaseInput): Promise<KnowledgeBase> {
    return postData<KnowledgeBase>('/kbs/create', body)
  },
  updateKb(body: KnowledgeBaseUpdateInput, version: number): Promise<KnowledgeBase> {
    return postData<KnowledgeBase>('/kbs/update', body, {
      'If-Match': String(version),
    })
  },
  archiveKb(
    body: { team_id: string; kb_id: string },
    version: number,
  ): Promise<KnowledgeBase> {
    return postData<KnowledgeBase>('/kbs/archive', body, {
      'If-Match': String(version),
    })
  },
  getKbPolicy(teamId: string, kbId: string) {
    return getData<{ kb_id: string; mode: string; version: number }>('/kbs/policy', {
      team_id: teamId,
      kb_id: kbId,
    })
  },
  updateKbPolicy(
    body: { team_id: string; kb_id: string; mode: string },
    version: number,
  ) {
    return postData<{ kb_id: string; mode: string; version: number }>(
      '/kbs/policy/update',
      body,
      { 'If-Match': String(version) },
    )
  },

  listDocs(
    teamId: string,
    kbId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<DocumentView>> {
    return getPage<DocumentView>('/docs', {
      team_id: teamId,
      kb_id: kbId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getDoc(teamId: string, documentId: string): Promise<DocumentDetailView> {
    return getData<DocumentDetailView>('/docs/detail', {
      team_id: teamId,
      document_id: documentId,
    })
  },
  updateDoc(
    body: {
      team_id: string
      document_id: string
      file_name?: string
      product?: string | null
      visibility?: string
      data_classification?: string
      version_values?: string[]
    },
    version: number,
  ): Promise<DocumentView> {
    return postData<DocumentView>('/docs/update', body, {
      'If-Match': String(version),
    })
  },
  listDocumentVersions(
    teamId: string,
    documentId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<DocumentVersion>> {
    return getPage<DocumentVersion>('/docs/versions', {
      team_id: teamId,
      document_id: documentId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getDocumentVersion(
    teamId: string,
    documentId: string,
    versionId: string,
  ): Promise<DocumentVersion> {
    return getData<DocumentVersion>('/docs/version', {
      team_id: teamId,
      document_id: documentId,
      version_id: versionId,
    })
  },
  listDocumentChunks(
    teamId: string,
    documentId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<ChunkView>> {
    return getPage<ChunkView>('/docs/chunks', {
      team_id: teamId,
      document_id: documentId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getDocumentTasks(
    teamId: string,
    documentId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<IngestionRun>> {
    return getPage<IngestionRun>('/docs/tasks', {
      team_id: teamId,
      document_id: documentId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  listDocumentGrants(
    teamId: string,
    documentId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<DocumentGrantView>> {
    return getPage<DocumentGrantView>('/docs/grants', {
      team_id: teamId,
      document_id: documentId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  createDocumentGrant(teamId: string, documentId: string, userId: string) {
    return postData<{ id: string; user_id: string }>('/docs/grants/create', {
      team_id: teamId,
      document_id: documentId,
      user_id: userId,
    })
  },
  revokeDocumentGrant(teamId: string, grantId: string) {
    return postData<{ revoked: string }>('/docs/grants/revoke', {
      team_id: teamId,
      grant_id: grantId,
    })
  },
  getDocumentDownloadUrl(teamId: string, documentId: string) {
    return getData<{ url: string; expires_in: number }>('/docs/download-url', {
      team_id: teamId,
      document_id: documentId,
    })
  },
  async downloadDocument(teamId: string, documentId: string): Promise<Blob> {
    const response = await http.get<Blob>('/docs/download', {
      params: { team_id: teamId, document_id: documentId },
      responseType: 'blob',
    })
    return response.data
  },
  rebuildDocument(teamId: string, documentId: string) {
    return postData<{ document_id: string; ingestion_run_id: string; status: string }>(
      '/docs/rebuild',
      { team_id: teamId, document_id: documentId },
    )
  },
  deleteDocument(teamId: string, documentId: string): Promise<DocumentView> {
    return postData<DocumentView>('/docs/delete', {
      team_id: teamId,
      document_id: documentId,
    })
  },
  restoreDocument(teamId: string, documentId: string): Promise<DocumentView> {
    return postData<DocumentView>('/docs/restore', {
      team_id: teamId,
      document_id: documentId,
    })
  },

  listIngestions(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<IngestionRun>> {
    return getPage<IngestionRun>('/ingestions', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getIngestionRun(teamId: string, runId: string): Promise<IngestionRun> {
    return getData<IngestionRun>('/ingestions/detail', {
      team_id: teamId,
      run_id: runId,
    })
  },
  retryIngestion(teamId: string, runId: string) {
    return postData<{ run_id: string; status: string; stage: string }>(
      '/ingestions/retry',
      { team_id: teamId, run_id: runId },
    )
  },
  cancelIngestion(teamId: string, runId: string) {
    return postData<{ run_id: string; status: string }>('/ingestions/cancel', {
      team_id: teamId,
      run_id: runId,
    })
  },

  listChunks(
    teamId: string,
    documentId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<ChunkView>> {
    return getPage<ChunkView>('/chunks', {
      team_id: teamId,
      document_id: documentId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getChunk(teamId: string, chunkId: string): Promise<ChunkView> {
    return getData<ChunkView>('/chunks/detail', {
      team_id: teamId,
      chunk_id: chunkId,
    })
  },
  disableChunks(teamId: string, chunkIds: string[]) {
    return postData<{ disabled: number }>('/chunks/disable', {
      team_id: teamId,
      chunk_ids: chunkIds,
    })
  },
  enableChunks(teamId: string, chunkIds: string[]) {
    return postData<{ enabled: number }>('/chunks/enable', {
      team_id: teamId,
      chunk_ids: chunkIds,
    })
  },
  updateChunk(
    teamId: string,
    chunkId: string,
    content: string,
    version: number,
  ): Promise<ChunkView> {
    return postData<ChunkView>(
      '/chunks/update',
      { team_id: teamId, chunk_id: chunkId, content },
      { 'If-Match': String(version) },
    )
  },
  regenerateChunks(teamId: string, documentId: string) {
    return postData<{ document_id: string; run_id: string; status: string }>(
      '/chunks/regenerate',
      { team_id: teamId, document_id: documentId },
    )
  },
  getChunkHistory(
    teamId: string,
    chunkId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<ChunkHistoryView>> {
    return getPage<ChunkHistoryView>('/chunks/history', {
      team_id: teamId,
      chunk_id: chunkId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },

  listChats(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<ChatView>> {
    return getPage<ChatView>('/chats', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  createChat(
    teamId: string,
    title?: string,
    knowledgeBaseIds?: string[],
  ): Promise<ChatView> {
    return postData<ChatView>('/chats/create', {
      team_id: teamId,
      title,
      knowledge_base_ids: knowledgeBaseIds,
    })
  },
  updateChat(teamId: string, chatId: string, title: string, version: number) {
    return postData<ChatView>(
      '/chats/update',
      { team_id: teamId, chat_id: chatId, title },
      { 'If-Match': String(version) },
    )
  },
  deleteChat(teamId: string, chatId: string) {
    return postData<{ deleted: string }>('/chats/delete', {
      team_id: teamId,
      chat_id: chatId,
    })
  },
  listMessages(
    teamId: string,
    chatId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<MessageView>> {
    return getPage<MessageView>('/chats/messages', {
      team_id: teamId,
      chat_id: chatId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  cancelMessage(teamId: string, messageId: string) {
    return postData<{ message_id: string; status: string }>('/messages/cancel', {
      team_id: teamId,
      message_id: messageId,
    })
  },
  submitFeedback(
    teamId: string,
    messageId: string,
    feedbackType: FeedbackType,
    comment?: string,
  ) {
    return postData<{ id: string; message_id: string; feedback_type: string }>(
      '/messages/feedback',
      {
        team_id: teamId,
        message_id: messageId,
        feedback_type: feedbackType,
        ...(comment ? { comment } : {}),
      },
    )
  },

  listMembers(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<TeamMemberView>> {
    return getPage<TeamMemberView>('/members', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  createInvitation(body: {
    team_id: string
    email: string
    role: Exclude<Role, 'admin'>
  }): Promise<InvitationView> {
    return postData<InvitationView>('/invitations/create', body)
  },
  getInvitation(token: string): Promise<InvitationView> {
    return getData<InvitationView>('/invitations/detail', { token })
  },
  acceptInvitation(token: string) {
    return postData<{
      team_id: string
      user_id: string
      role: Role
      status: string
    }>('/invitations/accept', { token })
  },
  updateMember(
    teamId: string,
    userId: string,
    body: MemberUpdateInput,
  ): Promise<Pick<TeamMemberView, 'team_id' | 'user_id' | 'role' | 'status'>> {
    return postData<Pick<TeamMemberView, 'team_id' | 'user_id' | 'role' | 'status'>>('/members/update', {
      team_id: teamId,
      user_id: userId,
      ...body,
    })
  },
  removeMember(teamId: string, userId: string) {
    return postData<{ removed: string }>('/members/remove', {
      team_id: teamId,
      user_id: userId,
    })
  },
  transferDocuments(
    body: TransferDocumentsInput,
  ): Promise<TransferDocumentsResult> {
    return postData<TransferDocumentsResult>('/members/transfer-documents', body)
  },

  listFacets(teamId: string): Promise<FacetView> {
    return getData<FacetView>('/facets', { team_id: teamId })
  },

  listSources(
    teamId: string,
    kbId?: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<SourceConnection>> {
    return getPage<SourceConnection>('/sources', {
      team_id: teamId,
      ...(kbId ? { kb_id: kbId } : {}),
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getSource(teamId: string, sourceId: string): Promise<SourceConnection> {
    return getData<SourceConnection>('/sources/detail', {
      team_id: teamId,
      source_id: sourceId,
    })
  },
  createGithubSource(body: {
    team_id: string
    kb_id: string
    repo_url: string
    branch: string
    path_filters: string[]
    credentials_id?: string | null
  }): Promise<SourceConnection> {
    return postData<SourceConnection>('/sources/github/create', body)
  },
  updateSource(body: {
    team_id: string
    source_id: string
    repo_url?: string
    branch?: string
    path_filters?: string[]
    credentials_id?: string | null
  }): Promise<SourceConnection> {
    return postData<SourceConnection>('/sources/update', body)
  },
  deleteSource(teamId: string, sourceId: string) {
    return postData<{ deleted: string }>('/sources/delete', {
      team_id: teamId,
      source_id: sourceId,
    })
  },
  syncSource(teamId: string, sourceId: string) {
    return postData<{ source_id: string; status: string }>('/sources/sync', {
      team_id: teamId,
      source_id: sourceId,
    })
  },
  pauseSource(teamId: string, sourceId: string) {
    return postData<{ source_id: string; status: string }>('/sources/pause', {
      team_id: teamId,
      source_id: sourceId,
    })
  },
  resumeSource(teamId: string, sourceId: string) {
    return postData<{ source_id: string; status: string }>('/sources/resume', {
      team_id: teamId,
      source_id: sourceId,
    })
  },
  listCredentials(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<CredentialView>> {
    return getPage<CredentialView>('/credentials', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  createCredential(teamId: string, name: string, secret: string) {
    return postData<{ id: string; name: string; secret_masked: string }>(
      '/credentials/create',
      { team_id: teamId, name, secret },
    )
  },
  deleteCredential(teamId: string, credentialId: string) {
    return postData<{ deleted: string }>('/credentials/delete', {
      team_id: teamId,
      credential_id: credentialId,
    })
  },

  listTraces(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<TraceView>> {
    return getPage<TraceView>('/traces', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getTrace(teamId: string, traceId: string): Promise<TraceView> {
    return getData<TraceView>('/traces/detail', {
      team_id: teamId,
      trace_id: traceId,
    })
  },
  exportTrace(teamId: string, traceId: string): Promise<TraceView> {
    return getData<TraceView>('/traces/export', {
      team_id: teamId,
      trace_id: traceId,
    })
  },

  listEvalDatasets(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<EvaluationDataset>> {
    return getPage<EvaluationDataset>('/evals/datasets', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getEvalDataset(
    teamId: string,
    datasetId: string,
  ): Promise<EvaluationDataset> {
    return getData<EvaluationDataset>('/evals/datasets/detail', {
      team_id: teamId,
      dataset_id: datasetId,
    })
  },
  createEvalDataset(body: {
    team_id: string
    name: string
    description?: string | null
  }): Promise<EvaluationDataset> {
    return postData<EvaluationDataset>('/evals/datasets/create', body)
  },
  updateEvalDataset(body: {
    team_id: string
    dataset_id: string
    name?: string
    description?: string | null
  }): Promise<EvaluationDataset> {
    return postData<EvaluationDataset>('/evals/datasets/update', body)
  },
  archiveEvalDataset(teamId: string, datasetId: string) {
    return postData<{ id: string; status: string }>('/evals/datasets/archive', {
      team_id: teamId,
      dataset_id: datasetId,
    })
  },
  listEvalCases(
    teamId: string,
    datasetId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<EvaluationCase>> {
    return getPage<EvaluationCase>('/evals/datasets/cases', {
      team_id: teamId,
      dataset_id: datasetId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  createEvalCase(body: {
    team_id: string
    dataset_id: string
    query_id: string
    query_type: string
    query: string
    relevant_chunk_ids: string[]
    filters: Record<string, unknown>
    relevance: Record<string, unknown>
  }): Promise<EvaluationCase> {
    return postData<EvaluationCase>('/evals/datasets/cases/create', body)
  },
  updateEvalCase(body: {
    team_id: string
    case_id: string
    query_id?: string
    query_type?: string
    query?: string
    relevant_chunk_ids?: string[]
    filters?: Record<string, unknown>
    relevance?: Record<string, unknown>
  }): Promise<EvaluationCase> {
    return postData<EvaluationCase>('/evals/datasets/cases/update', body)
  },
  deleteEvalCase(teamId: string, caseId: string) {
    return postData<{ deleted: string }>('/evals/datasets/cases/delete', {
      team_id: teamId,
      case_id: caseId,
    })
  },
  importEvalCases(
    teamId: string,
    datasetId: string,
    content: string,
  ) {
    return postData<{ imported: number }>('/evals/datasets/import', {
      team_id: teamId,
      dataset_id: datasetId,
      content,
    })
  },
  listEvalRuns(
    teamId: string,
    datasetId?: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<EvaluationRun>> {
    return getPage<EvaluationRun>('/evals/runs', {
      team_id: teamId,
      ...(datasetId ? { dataset_id: datasetId } : {}),
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  startEvalRun(body: {
    team_id: string
    dataset_id: string
    provider_id: string
    model_id: string
    engine_mode: string
    baseline_run_id?: string | null
  }) {
    return postData<{ id: string; status: string }>('/evals/runs/start', body)
  },
  getEvalRun(teamId: string, runId: string): Promise<EvaluationRun> {
    return getData<EvaluationRun>('/evals/runs/detail', {
      team_id: teamId,
      run_id: runId,
    })
  },
  cancelEvalRun(teamId: string, runId: string) {
    return postData<{ id: string; status: string }>('/evals/runs/cancel', {
      team_id: teamId,
      run_id: runId,
    })
  },
  getEvalReport(teamId: string, runId: string): Promise<EvaluationReport> {
    return getData<EvaluationReport>('/evals/runs/report', {
      team_id: teamId,
      run_id: runId,
    })
  },

  getPolicy(teamId: string): Promise<ModelPolicy> {
    return getData<ModelPolicy>('/model-policy', { team_id: teamId })
  },
  updatePolicy(body: {
    team_id: string
    mode: string
    allowed_provider_ids?: string[]
    max_data_classification?: string
    allow_chat_history?: boolean
    allow_document_metadata?: boolean
  }): Promise<ModelPolicy> {
    return postData<ModelPolicy>('/model-policy/update', body)
  },
  listProviders(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<ModelProvider>> {
    return getPage<ModelProvider>('/providers', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  createProvider(body: {
    team_id: string
    name: string
    provider_type: ProviderType
    base_url: string
    api_key: string
    model_ids: string[]
  }) {
    return postData<ModelProvider>('/providers/create', body)
  },
  discoverProviderModels(
    teamId: string,
    body: ProviderModelsInput,
  ): Promise<{ provider_type: ProviderType; models: string[] }> {
    return postData('/providers/models', { team_id: teamId, ...body })
  },
  testProvider(teamId: string, providerId: string) {
    return postData<{ provider_id: string; status: string }>('/providers/test', {
      team_id: teamId,
      provider_id: providerId,
    })
  },
  listModelCalls(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<ModelCall>> {
    return getPage<ModelCall>('/model-calls', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getAdminPolicy(): Promise<ModelPolicy> {
    return getData<ModelPolicy>('/admin/model-policy')
  },
  updateAdminPolicy(body: {
    mode: string
    max_data_classification?: string
    allowed_provider_ids?: string[]
    allow_chat_history?: boolean
    allow_document_metadata?: boolean
  }): Promise<ModelPolicy> {
    return postData<ModelPolicy>('/admin/model-policy/update', body)
  },
  listAdminProviders(
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<ModelProvider>> {
    return getPage<ModelProvider>('/admin/providers', {
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  createAdminProvider(body: {
    name: string
    provider_type: ProviderType
    base_url: string
    api_key: string
    model_ids: string[]
  }) {
    return postData<ModelProvider>('/admin/providers/create', body)
  },
  discoverAdminProviderModels(
    body: ProviderModelsInput,
  ): Promise<{ provider_type: ProviderType; models: string[] }> {
    return postData('/admin/providers/models', body)
  },
  updateAdminProvider(body: {
    provider_id: string
    status?: string
    provider_type?: ProviderType
    base_url?: string
    api_key?: string
    model_ids?: string[]
  }) {
    return postData<ModelProvider>('/admin/providers/update', body)
  },
  listAdminModels(
    cursor?: string | null,
    limit = 20,
  ): Promise<
    PageEnvelope<{ provider_id: string; model_id: string; status: string }>
  > {
    return getPage('/admin/models', {
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  updateAdminModels(providerId: string, modelIds: string[]) {
    return postData<{ provider_id: string; model_ids: string[] }>(
      '/admin/models/update',
      { provider_id: providerId, model_ids: modelIds },
    )
  },

  listAudit(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<AuditLogView>> {
    return getPage<AuditLogView>('/audit', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  listAdminAudit(
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<AuditLogView>> {
    return getPage<AuditLogView>('/admin/audit', {
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getAdminAudit(auditId: string): Promise<AuditLogView> {
    return getData<AuditLogView>('/admin/audit/detail', { audit_id: auditId })
  },
  getAudit(teamId: string, auditId: string): Promise<AuditLogView> {
    return getData<AuditLogView>('/audit/detail', {
      team_id: teamId,
      audit_id: auditId,
    })
  },
  listGenerations(
    teamId: string,
    cursor?: string | null,
    limit = 20,
  ): Promise<PageEnvelope<IndexGeneration>> {
    return getPage<IndexGeneration>('/generations', {
      team_id: teamId,
      limit,
      ...(cursor ? { cursor } : {}),
    })
  },
  getGeneration(teamId: string, generationId: string): Promise<IndexGeneration> {
    return getData<IndexGeneration>('/generations/detail', {
      team_id: teamId,
      generation_id: generationId,
    })
  },
  getGenerationValidation(
    teamId: string,
    generationId: string,
  ): Promise<GenerationValidation> {
    return getData<GenerationValidation>('/generations/validation', {
      team_id: teamId,
      generation_id: generationId,
    })
  },
  reindexGeneration(teamId: string): Promise<GenerationReindexResult> {
    return postData<GenerationReindexResult>('/generations/reindex', {
      team_id: teamId,
    })
  },
  validateGeneration(teamId: string, generationId: string) {
    return postData<GenerationValidation & { status: string }>(
      '/generations/validate',
      { team_id: teamId, generation_id: generationId },
    )
  },
  activateGeneration(teamId: string, generationId: string) {
    return postData<IndexGeneration>('/generations/activate', {
      team_id: teamId,
      generation_id: generationId,
    })
  },
  rollbackGeneration(teamId: string) {
    return postData<IndexGeneration>('/generations/rollback', { team_id: teamId })
  },

  getHealth(): Promise<HealthView> {
    return getData<HealthView>('/health')
  },
  getReady(): Promise<HealthView> {
    return getData<HealthView>('/ready')
  },
  getVersion(): Promise<VersionView> {
    return getData<VersionView>('/version')
  },
}
