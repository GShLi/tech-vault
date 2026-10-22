<script setup lang="ts">
import {
  ApiRequestError,
  api,
  loadAllPages,
  normalizeApiError as toApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Modal as AModal,
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { computed, onMounted, ref } from 'vue'
import { Link2, UserPlus, Users, X } from 'lucide-vue-next'

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

async function setStatus(
  member: TeamMemberView,
  status: 'active' | 'disabled',
): Promise<void> {
  if (!team.selectedTeamId) return
  pendingUserId.value = member.user_id
  error.value = null
  try {
    await api.updateMember(team.selectedTeamId, member.user_id, { status })
    await load()
  } catch (caught) {
    error.value = toApiError(
      caught,
      status === 'active' ? '无法启用成员' : '无法停用成员',
    )
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
  if (
    !team.selectedTeamId ||
    !removalCandidate.value ||
    !transferTargetId.value
  )
    return
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

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>

    <section v-if="team.canManage" class="panel invite-create-panel">
      <div class="panel-heading">
        <div>
          <h3>邀请成员</h3>
          <p>仅已由平台管理员创建的账号可以接受邀请。</p>
        </div>
      </div>
      <a-form
        class="inline-form"
        :model="{ inviteEmail, inviteRole }"
        layout="vertical"
        @submit-success="createInvitation"
      >
        <a-form-item
          field="inviteEmail"
          :rules="[
            { required: true, message: '请填写邮箱' },
            { type: 'email', message: '请输入有效的邮箱地址' },
          ]"
          :validate-trigger="['change', 'blur']"
        >
          <template #label>邮箱</template>
          <a-input
            v-model="inviteEmail"
            data-testid="invite-email"
            placeholder="member@company.com"
            type="text"
            :input-attrs="{ required: true }"
          ></a-input>
        </a-form-item>
        <a-form-item field="inviteRole">
          <template #label>角色</template>
          <a-select v-model="inviteRole" data-testid="invite-role">
            <a-option value="leader">{{ roleLabels.leader }}</a-option>
            <a-option value="member">{{ roleLabels.member }}</a-option>
            <a-option value="viewer">{{ roleLabels.viewer }}</a-option>
          </a-select>
        </a-form-item>
        <a-button
          data-testid="invite-submit"
          :disabled="inviting || !inviteEmail.trim()"
          type="primary"
          html-type="submit"
        >
          <UserPlus :size="17" />
          {{ inviting ? '创建中' : '创建邀请' }}
        </a-button>
      </a-form>
      <div v-if="invitationUrl" class="invite-link-result">
        <Link2 :size="17" />
        <a-input
          readonly
          :model-value="invitationUrl"
          :input-attrs="{ 'aria-label': '邀请链接' }"
        ></a-input>
      </div>
    </section>

    <div class="panel">
      <div v-if="loading && !members.length" class="loading-state">
        <a-spin></a-spin>
        <span>正在加载成员</span>
      </div>
      <div v-else class="table-wrap">
        <a-table
          :data="members"
          :pagination="false"
          row-key="user_id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column title="成员">
              <template #cell="{ record: member }">
                <strong>{{ member.display_name }}</strong>
                <span class="cell-subtitle">{{ member.email }}</span>
                <span class="cell-subtitle">
                  加入于 {{ formatDate(member.joined_at) }}
                </span>
              </template>
            </a-table-column>
            <a-table-column title="角色">
              <template #cell="{ record: member }">
                <a-select
                  class="member-role-select"
                  :disabled="
                    !team.canManage ||
                    pendingUserId === member.user_id ||
                    member.status === 'removed'
                  "
                  @change="changeRole(member.user_id, $event as TeamRole)"
                  :model-value="member.role"
                >
                  <a-option value="leader">{{ roleLabels.leader }}</a-option>
                  <a-option value="member">{{ roleLabels.member }}</a-option>
                  <a-option value="viewer">{{ roleLabels.viewer }}</a-option>
                </a-select>
              </template>
            </a-table-column>
            <a-table-column title="状态" :width="100">
              <template #cell="{ record: member }">
                <a-tag :color="statusColor(member.status)">
                  {{ statusLabel(member.status) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column v-if="team.canManage" title="操作" :width="180">
              <template #cell="{ record: member }">
                <div class="member-actions">
                  <a-button
                    v-if="member.status === 'active'"
                    :data-testid="`member-disable-${member.user_id}`"
                    :disabled="pendingUserId === member.user_id"
                    @click="setStatus(member, 'disabled')"
                    type="text"
                    html-type="button"
                  >
                    停用
                  </a-button>
                  <a-button
                    v-else-if="member.status === 'disabled'"
                    :data-testid="`member-enable-${member.user_id}`"
                    :disabled="pendingUserId === member.user_id"
                    @click="setStatus(member, 'active')"
                    type="text"
                    html-type="button"
                  >
                    启用
                  </a-button>
                  <a-button
                    v-if="member.status !== 'removed'"
                    :data-testid="`member-remove-${member.user_id}`"
                    :disabled="pendingUserId === member.user_id"
                    @click="openRemoval(member)"
                    type="text"
                    html-type="button"
                    status="danger"
                  >
                    移除
                  </a-button>
                </div>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <a-empty v-if="!loading && !members.length" class="page-empty">
        <template #image><Users :size="24" /></template>
        <span>暂无成员</span>
      </a-empty>
      <div v-if="hasMore" class="load-more">
        <a-button
          :disabled="loading"
          @click="loadMore"
          type="secondary"
          html-type="button"
        >
          {{ loading ? '加载中' : '加载更多成员' }}
        </a-button>
      </div>
    </div>

    <a-modal
      v-if="removalCandidate"
      :visible="true"
      :footer="false"
      unmount-on-close
      @cancel="closeRemoval"
      :closable="!(removing || transferring)"
      :mask-closable="!(removing || transferring)"
      :esc-to-close="!(removing || transferring)"
      width="520px"
    >
      <template #title>
        <h3 id="remove-member-title">
          移除 {{ removalCandidate.display_name }}
        </h3>
        <span class="cell-subtitle">{{ removalCandidate.email }}</span>
      </template>
      <a-alert type="info" class="page-alert removal-notice">
        <strong>移除前请转移该成员的私有文档</strong>
        <span>未转移的私有文档可能在账号停用后失去可管理归属。</span>
      </a-alert>
      <div class="form-stack">
        <a-form-item>
          <template #label>转移到 active 成员</template>
          <a-select
            v-model="transferTargetId"
            data-testid="transfer-target"
            :disabled="
              transferring ||
              removing ||
              loadingTransferTargets ||
              !activeTransferTargets.length
            "
          >
            <a-option v-if="loadingTransferTargets" value="">
              正在加载全部成员
            </a-option>
            <a-option v-else-if="!activeTransferTargets.length" value="">
              暂无其他可接收成员
            </a-option>
            <a-option
              v-for="target in activeTransferTargets"
              :key="target.user_id"
              :value="target.user_id"
            >
              {{ target.display_name }} · {{ target.email }}
            </a-option>
          </a-select>
        </a-form-item>
        <a-alert v-if="transferNotice" type="info" class="page-alert">
          <strong>转移完成</strong>
          <span>{{ transferNotice }}</span>
        </a-alert>
        <div class="modal-actions member-removal-actions">
          <a-button
            :disabled="removing || transferring"
            @click="closeRemoval"
            type="text"
            html-type="button"
          >
            取消
          </a-button>
          <a-button
            data-testid="transfer-submit"
            :disabled="transferring || removing || !transferTargetId"
            @click="transferPrivateDocuments"
            type="secondary"
            html-type="button"
          >
            {{ transferring ? '转移中' : '转移私有文档' }}
          </a-button>
          <a-button
            data-testid="remove-confirm"
            :disabled="removing || transferring"
            @click="confirmRemoval"
            type="primary"
            html-type="button"
          >
            {{ removing ? '移除中' : '确认移除' }}
          </a-button>
        </div>
      </div>
    </a-modal>
  </div>
</template>
