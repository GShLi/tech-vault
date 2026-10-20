<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Link2, UserPlus, Users, X } from 'lucide-vue-next'

import { api, ApiRequestError, loadAllPages } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import type { Role, TeamMemberView } from '@/types/api'
import { formatDate } from '@/utils/format'

type TeamRole = Exclude<Role, 'admin'>

const team = useTeamStore()
const members = ref<TeamMemberView[]>([])
const error = ref<ApiRequestError | null>(null)
const loading = ref(false)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const inviteEmail = ref('')
const inviteRole = ref<TeamRole>('member')
const invitationUrl = ref('')
const inviting = ref(false)
const pendingUserId = ref('')
const removalCandidate = ref<TeamMemberView | null>(null)
const transferTargets = ref<TeamMemberView[]>([])
const transferTargetId = ref('')
const loadingTransferTargets = ref(false)
const transferring = ref(false)
const removing = ref(false)
const transferNotice = ref('')

const roleLabels: Record<Role, string> = {
  admin: '平台管理员',
  leader: '团队管理员',
  member: '成员',
  viewer: '只读成员',
}

const activeTransferTargets = computed(() =>
  transferTargets.value.filter(
    (member) =>
      member.status === 'active' &&
      member.user_id !== removalCandidate.value?.user_id,
  ),
)

function toApiError(caught: unknown, fallback: string): ApiRequestError {
  if (caught instanceof ApiRequestError) return caught
  return new ApiRequestError(caught instanceof Error ? caught.message : fallback)
}

function statusLabel(status: string): string {
  if (status === 'active') return '活跃'
  if (status === 'disabled') return '已停用'
  if (status === 'removed') return '已移除'
  return status
}

function statusColor(status: string): string {
  return status === 'active' ? 'green' : 'gray'
}

async function load(reset = true): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const page = await api.listMembers(
      team.selectedTeamId,
      reset ? null : nextCursor.value,
      20,
    )
    const existingIds = new Set(members.value.map((member) => member.user_id))
    const rows = reset
      ? page.data
      : page.data.filter((member) => !existingIds.has(member.user_id))
    members.value = reset ? rows : [...members.value, ...rows]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = toApiError(caught, '无法加载成员')
  } finally {
    loading.value = false
  }
}

function loadMore(): Promise<void> {
  return load(false)
}

async function changeRole(userId: string, role: TeamRole): Promise<void> {
  if (!team.selectedTeamId) return
  pendingUserId.value = userId
  error.value = null
  try {
    await api.updateMember(team.selectedTeamId, userId, { role })
    await load()
  } catch (caught) {
    error.value = toApiError(caught, '无法修改成员角色')
  } finally {
    pendingUserId.value = ''
  }
}

async function setStatus(member: TeamMemberView, status: 'active' | 'disabled'): Promise<void> {
  if (!team.selectedTeamId) return
  pendingUserId.value = member.user_id
  error.value = null
  try {
    await api.updateMember(team.selectedTeamId, member.user_id, { status })
    await load()
  } catch (caught) {
    error.value = toApiError(caught, status === 'active' ? '无法启用成员' : '无法停用成员')
  } finally {
    pendingUserId.value = ''
  }
}

async function openRemoval(member: TeamMemberView): Promise<void> {
  removalCandidate.value = member
  transferTargets.value = []
  transferTargetId.value = ''
  transferNotice.value = ''
  const teamId = team.selectedTeamId
  if (!teamId) return

  loadingTransferTargets.value = true
  error.value = null
  try {
    const allMembers = await loadAllPages((cursor) =>
      api.listMembers(teamId, cursor, 100),
    )
    if (removalCandidate.value?.user_id !== member.user_id) return
    transferTargets.value = allMembers
    transferTargetId.value = activeTransferTargets.value[0]?.user_id ?? ''
  } catch (caught) {
    error.value = toApiError(caught, '无法加载可接收私有文档的成员')
  } finally {
    loadingTransferTargets.value = false
  }
}

function closeRemoval(): void {
  if (transferring.value || removing.value) return
  removalCandidate.value = null
  transferTargets.value = []
  transferTargetId.value = ''
  transferNotice.value = ''
}

async function transferPrivateDocuments(): Promise<void> {
  if (!team.selectedTeamId || !removalCandidate.value || !transferTargetId.value) return
  transferring.value = true
  error.value = null
  transferNotice.value = ''
  try {
    const result = await api.transferDocuments({
      team_id: team.selectedTeamId,
      from_user_id: removalCandidate.value.user_id,
      to_user_id: transferTargetId.value,
    })
    transferNotice.value = `已转移 ${result.transferred_documents} 份文档和 ${result.transferred_chunks} 个 Chunk。`
    await load()
  } catch (caught) {
    error.value = toApiError(caught, '无法转移私有文档')
  } finally {
    transferring.value = false
  }
}

async function confirmRemoval(): Promise<void> {
  if (!team.selectedTeamId || !removalCandidate.value) return
  removing.value = true
  error.value = null
  try {
    await api.removeMember(team.selectedTeamId, removalCandidate.value.user_id)
    removalCandidate.value = null
    transferTargetId.value = ''
    transferNotice.value = ''
    await load()
  } catch (caught) {
    error.value = toApiError(caught, '无法移除成员')
  } finally {
    removing.value = false
  }
}

async function createInvitation(): Promise<void> {
  if (!team.selectedTeamId || !inviteEmail.value.trim()) return
  inviting.value = true
  error.value = null
  try {
    const invitation = await api.createInvitation({
      team_id: team.selectedTeamId,
      email: inviteEmail.value.trim(),
      role: inviteRole.value,
    })
    invitationUrl.value = new URL(
      invitation.invitation_url ?? `/invite/${invitation.token}`,
      window.location.origin,
    ).toString()
    inviteEmail.value = ''
  } catch (caught) {
    error.value = toApiError(caught, '无法创建邀请')
  } finally {
    inviting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>成员管理</h2>
        <p>管理团队角色、成员状态和私有文档归属。</p>
      </div>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </div>

    <section v-if="team.canManage" class="panel invite-create-panel">
      <div class="panel-heading">
        <div>
          <h3>邀请成员</h3>
          <p>仅已由平台管理员创建的账号可以接受邀请。</p>
        </div>
      </div>
      <form class="inline-form" @submit.prevent="createInvitation">
        <label class="field">
          <span>邮箱</span>
          <input v-model="inviteEmail" data-testid="invite-email" type="email" required placeholder="member@company.com" />
        </label>
        <label class="field">
          <span>角色</span>
          <select v-model="inviteRole" data-testid="invite-role">
            <option value="leader">{{ roleLabels.leader }}</option>
            <option value="member">{{ roleLabels.member }}</option>
            <option value="viewer">{{ roleLabels.viewer }}</option>
          </select>
        </label>
        <button class="primary-button" data-testid="invite-submit" type="submit" :disabled="inviting || !inviteEmail.trim()">
          <UserPlus :size="17" />
          {{ inviting ? '创建中' : '创建邀请' }}
        </button>
      </form>
      <div v-if="invitationUrl" class="invite-link-result">
        <Link2 :size="17" />
        <input :value="invitationUrl" readonly aria-label="邀请链接" />
      </div>
    </section>

    <div class="panel">
      <div v-if="loading && !members.length" class="loading-state">
        <span class="spinner" />
        <span>正在加载成员</span>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>成员</th>
              <th>角色</th>
              <th>状态</th>
              <th v-if="team.canManage" class="actions-column">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in members" :key="member.user_id">
              <td data-label="成员">
                <strong>{{ member.display_name }}</strong>
                <span class="cell-subtitle">{{ member.email }}</span>
                <span class="cell-subtitle">加入于 {{ formatDate(member.joined_at) }}</span>
              </td>
              <td data-label="角色">
                <select
                  class="member-role-select"
                  :value="member.role"
                  :disabled="!team.canManage || pendingUserId === member.user_id || member.status === 'removed'"
                  @change="changeRole(member.user_id, ($event.target as HTMLSelectElement).value as TeamRole)"
                >
                  <option value="leader">{{ roleLabels.leader }}</option>
                  <option value="member">{{ roleLabels.member }}</option>
                  <option value="viewer">{{ roleLabels.viewer }}</option>
                </select>
              </td>
              <td data-label="状态">
                <a-tag :color="statusColor(member.status)">{{ statusLabel(member.status) }}</a-tag>
              </td>
              <td v-if="team.canManage" data-label="操作" class="actions-column">
                <div class="member-actions">
                  <button
                    v-if="member.status === 'active'"
                    class="ghost-button"
                    :data-testid="`member-disable-${member.user_id}`"
                    type="button"
                    :disabled="pendingUserId === member.user_id"
                    @click="setStatus(member, 'disabled')"
                  >
                    停用
                  </button>
                  <button
                    v-else-if="member.status === 'disabled'"
                    class="ghost-button"
                    :data-testid="`member-enable-${member.user_id}`"
                    type="button"
                    :disabled="pendingUserId === member.user_id"
                    @click="setStatus(member, 'active')"
                  >
                    启用
                  </button>
                  <button
                    v-if="member.status !== 'removed'"
                    class="ghost-button danger-text"
                    :data-testid="`member-remove-${member.user_id}`"
                    type="button"
                    :disabled="pendingUserId === member.user_id"
                    @click="openRemoval(member)"
                  >
                    移除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!loading && !members.length" class="empty-state">
        <Users :size="24" />
        <span>暂无成员</span>
      </div>
      <div v-if="hasMore" class="load-more">
        <button class="secondary-button" type="button" :disabled="loading" @click="loadMore">
          {{ loading ? '加载中' : '加载更多成员' }}
        </button>
      </div>
    </div>

    <div v-if="removalCandidate" class="modal-backdrop" @click.self="closeRemoval">
      <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="remove-member-title">
        <div class="modal-heading">
          <div>
            <h3 id="remove-member-title">移除 {{ removalCandidate.display_name }}</h3>
            <span class="cell-subtitle">{{ removalCandidate.email }}</span>
          </div>
          <button class="icon-button" type="button" title="关闭" :disabled="removing || transferring" @click="closeRemoval">
            <X :size="17" />
          </button>
        </div>
        <div class="notice-box removal-notice">
          <strong>移除前请转移该成员的私有文档</strong>
          <span>未转移的私有文档可能在账号停用后失去可管理归属。</span>
        </div>
        <div class="form-stack">
          <label class="field">
            <span>转移到 active 成员</span>
            <select v-model="transferTargetId" data-testid="transfer-target" :disabled="transferring || removing || loadingTransferTargets || !activeTransferTargets.length">
              <option v-if="loadingTransferTargets" value="">正在加载全部成员</option>
              <option v-else-if="!activeTransferTargets.length" value="">暂无其他可接收成员</option>
              <option v-for="target in activeTransferTargets" :key="target.user_id" :value="target.user_id">
                {{ target.display_name }} · {{ target.email }}
              </option>
            </select>
          </label>
          <div v-if="transferNotice" class="notice-box">
            <strong>转移完成</strong>
            <span>{{ transferNotice }}</span>
          </div>
          <div class="modal-actions member-removal-actions">
            <button class="ghost-button" type="button" :disabled="removing || transferring" @click="closeRemoval">取消</button>
            <button
              class="secondary-button"
              data-testid="transfer-submit"
              type="button"
              :disabled="transferring || removing || !transferTargetId"
              @click="transferPrivateDocuments"
            >
              {{ transferring ? '转移中' : '转移私有文档' }}
            </button>
            <button
              class="primary-button"
              data-testid="remove-confirm"
              type="button"
              :disabled="removing || transferring"
              @click="confirmRemoval"
            >
              {{ removing ? '移除中' : '确认移除' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
