export type Role = 'admin' | 'leader' | 'member' | 'viewer'

export interface User {
  id: string
  email: string
  display_name: string
  status: string
  is_super_admin: boolean
  is_builtin: boolean
  created_at: string
}

export interface Membership {
  team_id: string
  team_name: string
  role: Role
  status: string
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
