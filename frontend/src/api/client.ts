import axios, { AxiosError, AxiosHeaders } from 'axios'

import type {
  Envelope,
  KnowledgeBase,
  KnowledgeBaseInput,
  KnowledgeBaseUpdateInput,
  LoginResponse,
  Me,
  PageEnvelope,
  RegisterInput,
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
  if (error instanceof ApiRequestError) {
    return error
  }

  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<{
      error?: {
        code?: string
        message?: string
        details?: Record<string, unknown>
        request_id?: string
      }
    }>
    const payload = axiosError.response?.data?.error
    return new ApiRequestError(
      payload?.message ?? axiosError.message ?? '请求失败',
      payload?.code ?? 'NETWORK_ERROR',
      payload?.request_id ??
        String(axiosError.response?.headers?.['x-request-id'] ?? ''),
      axiosError.response?.status ?? 0,
      payload?.details ?? {},
    )
  }

  return new ApiRequestError(
    error instanceof Error ? error.message : '请求失败',
    'UNKNOWN_ERROR',
  )
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

async function getPage<T>(
  url: string,
  params?: Record<string, unknown>,
): Promise<PageEnvelope<T>> {
  const response = await http.get<PageEnvelope<T>>(url, { params })
  return response.data
}

async function postData<T>(
  url: string,
  body: object,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await http.post<Envelope<T>>(url, body, { headers })
  return response.data.data
}

export const api = {
  register(body: RegisterInput): Promise<User> {
    return postData<User>('/auth/register', body)
  },

  login(body: { email: string; password: string }): Promise<LoginResponse> {
    return postData<LoginResponse>('/auth/login', body)
  },

  me(): Promise<Me> {
    return getData<Me>('/auth/me')
  },

  createTeam(body: TeamCreateInput): Promise<Team> {
    return postData<Team>('/teams/create', body)
  },

  updateTeam(body: TeamUpdateInput, version: number): Promise<Team> {
    return postData<Team>('/teams/update', body, {
      'If-Match': String(version),
    })
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

  createKb(body: KnowledgeBaseInput): Promise<KnowledgeBase> {
    return postData<KnowledgeBase>('/kbs/create', body)
  },

  updateKb(
    body: KnowledgeBaseUpdateInput,
    version: number,
  ): Promise<KnowledgeBase> {
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
}
