import axios, { AxiosError, AxiosHeaders } from 'axios'

import type {
  Envelope,
  KnowledgeBase,
  KnowledgeBaseInput,
  KnowledgeBaseUpdateInput,
  LoginResponse,
  Me,
  PageEnvelope,
  AdminUserCreateInput,
  PasswordChangeInput,
  Team,
  TeamCreateInput,
  TeamUpdateInput,
  User,
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

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers = config.headers ?? new AxiosHeaders()
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(normalizeApiError(error)),
)

async function getData<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await http.get<Envelope<T>>(url, { params })
  return response.data.data
}

async function getPage<T>(url: string, params?: Record<string, unknown>): Promise<PageEnvelope<T>> {
  const response = await http.get<PageEnvelope<T>>(url, { params })
  return response.data
}

async function postData<T>(url: string, body: object, headers?: Record<string, string>): Promise<T> {
  const response = await http.post<Envelope<T>>(url, body, { headers })
  return response.data.data
}

// --- Document / Chunk / Chat / Message types (in-client, no separate file) ---

export interface DocumentView {
  id: string; knowledge_base_id: string; file_name: string; source_type: string
  product: string | null; version_values: string[]; visibility: string
  data_classification: string; doc_status: string; version: number
  created_at: string; updated_at: string
}

export interface ChunkView {
  id: string; document_id: string; content: string; heading_path: string[]
  source_locator: Record<string, unknown>; status: string; version: number
  created_at: string; updated_at: string
}

export interface ChatView {
  id: string; team_id: string; user_id: string; title: string
  knowledge_base_ids: string[]; version: number; created_at: string; updated_at: string
}

export interface MessageView {
  id: string; chat_id: string; role: string; content: string; status: string
  trace_id: string | null; citation_ids: string[]; refusal_reason: string | null; created_at: string
}

export const api = {
  login(body: { email: string; password: string }): Promise<LoginResponse> { return postData<LoginResponse>('/auth/login', body) },
  changePassword(body: PasswordChangeInput) { return postData<Record<string, never>>('/auth/password/change', body) },
  me(): Promise<Me> { return getData<Me>('/auth/me') },
  listTeams(cursor?: string | null, limit = 100): Promise<PageEnvelope<Team>> { return getPage<Team>('/teams', { limit, ...(cursor ? { cursor } : {}) }) },
  createUser(body: AdminUserCreateInput) { return postData<Record<string, unknown>>('/admin/users/create', body) },
  createTeam(body: TeamCreateInput): Promise<Team> { return postData<Team>('/teams/create', body) },
  updateTeam(body: TeamUpdateInput, version: number): Promise<Team> { return postData<Team>('/teams/update', body, { 'If-Match': String(version) }) },
  listKbs(teamId: string, cursor?: string | null, limit = 20): Promise<PageEnvelope<KnowledgeBase>> { return getPage<KnowledgeBase>('/kbs', { team_id: teamId, limit, ...(cursor ? { cursor } : {}) }) },
  createKb(body: KnowledgeBaseInput): Promise<KnowledgeBase> { return postData<KnowledgeBase>('/kbs/create', body) },
  updateKb(body: KnowledgeBaseUpdateInput, version: number): Promise<KnowledgeBase> { return postData<KnowledgeBase>('/kbs/update', body, { 'If-Match': String(version) }) },
  archiveKb(body: { team_id: string; kb_id: string }, version: number): Promise<KnowledgeBase> { return postData<KnowledgeBase>('/kbs/archive', body, { 'If-Match': String(version) }) },

  // Document
  listDocs(teamId: string, kbId: string, cursor?: string | null, limit = 20): Promise<PageEnvelope<DocumentView>> { return getPage<DocumentView>('/docs', { team_id: teamId, kb_id: kbId, limit, ...(cursor ? { cursor } : {}) }) },
  getDoc(teamId: string, documentId: string): Promise<DocumentView> { return getData<DocumentView>('/docs/detail', { team_id: teamId, document_id: documentId }) },

  // Chunk
  listChunks(teamId: string, documentId: string, cursor?: string | null, limit = 20): Promise<PageEnvelope<ChunkView>> { return getPage<ChunkView>('/chunks', { team_id: teamId, document_id: documentId, limit, ...(cursor ? { cursor } : {}) }) },
  disableChunks(teamId: string, chunkIds: string[]) { return postData<{ disabled: number }>('/chunks/disable', { team_id: teamId, chunk_ids: chunkIds }) },
  enableChunks(teamId: string, chunkIds: string[]) { return postData<{ enabled: number }>('/chunks/enable', { team_id: teamId, chunk_ids: chunkIds }) },

  // Chat
  listChats(teamId: string, cursor?: string | null, limit = 20): Promise<PageEnvelope<ChatView>> { return getPage<ChatView>('/chats', { team_id: teamId, limit, ...(cursor ? { cursor } : {}) }) },
  createChat(teamId: string, title?: string, knowledgeBaseIds?: string[]): Promise<ChatView> { return postData<ChatView>('/chats/create', { team_id: teamId, title, knowledge_base_ids: knowledgeBaseIds }) },
  getPolicy(teamId: string): Promise<Record<string, unknown>> { return getData<Record<string, unknown>>("/model-policy", { team_id: teamId }) },

  updatePolicy(teamId: string, mode: string) { return postData<Record<string, unknown>>("/model-policy/update", { team_id: teamId, mode }) },

  deleteChat(teamId: string, chatId: string) { return postData<{ deleted: string }>('/chats/delete', { team_id: teamId, chat_id: chatId }) },
  listMessages(teamId: string, chatId: string): Promise<MessageView[]> { return getData<MessageView[]>('/chats/messages', { team_id: teamId, chat_id: chatId }) },

  listMembers(teamId: string, cursor?: string | null, limit = 20): Promise<PageEnvelope<Record<string, string>>> { return getPage<Record<string, string>>('/members', { team_id: teamId, limit, ...(cursor ? { cursor } : {}) }) },

  updateMember(teamId: string, userId: string, body: { role?: string; status?: string }) { return postData<Record<string, string>>('/members/update', { team_id: teamId, user_id: userId, ...body }) },

  removeMember(teamId: string, userId: string) { return postData<{ removed: string }>('/members/remove', { team_id: teamId, user_id: userId }) },
}
