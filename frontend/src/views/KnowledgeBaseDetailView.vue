<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Alert as AAlert, Button as AButton, Card as ACard, Checkbox as ACheckbox,
  Empty as AEmpty, Input as AInput, InputSearch as AInputSearch, Textarea as ATextarea,
  Message, Spin as ASpin, Table as ATable, TableColumn as ATableColumn, Tag as ATag,
  Tabs as ATabs, TabPane as ATabPane, Tooltip as ATooltip } from '@arco-design/web-vue'
import { ArrowLeft, BookOpen, Pencil, RefreshCw, Save, Settings2, Upload, Users } from 'lucide-vue-next'
import { api, loadAllPages, normalizeApiError, type ApiRequestError } from '@/api/client'
import { useCursorList } from '@/composables/useCursorList'
import { confirmAction, useUnsavedChanges } from '@/composables/useUnsavedChanges'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import { statusColor } from '@/utils/status'
import { formatDate, shortId, statusLabel } from '@/utils/format'
import type { DocumentView, IngestionRun, KnowledgeBase, KnowledgeBaseMemberView, TeamMemberView } from '@/types/api'

const route = useRoute()
const router = useRouter()
const team = useTeamStore()
const auth = useAuthStore()
const kb = ref<KnowledgeBase | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const editing = ref(false)
const editName = ref('')
const editDescription = ref('')
const editVersion = ref(0)
const saving = ref(false)
const editError = ref<ApiRequestError | null>(null)
const activeTab = ref('documents')
const searchDraft = ref('')
const search = ref('')
const tasks = ref<IngestionRun[]>([])
const taskError = ref<ApiRequestError | null>(null)
const kbMembers = ref<KnowledgeBaseMemberView[]>([])
const teamMembers = ref<TeamMemberView[]>([])
const selectedMemberIds = ref<string[]>([])
const memberLoading = ref(false)
const memberSaving = ref(false)
const memberError = ref<ApiRequestError | null>(null)
let loadVersion = 0
let memberVersion = 0
let taskVersion = 0
const canEditMembers = computed(() => team.canManage)
const canEditContent = computed(() => ['leader', 'member'].includes(team.currentMembership?.role || ''))
const activeTeamMembers = computed(() => teamMembers.value.filter((member) => member.status === 'active'))
const memberRoleLabels: Record<TeamMemberView['role'], string> = { leader: '团队管理员', member: '成员', viewer: '只读成员' }
function kbId() { return String(route.params.kbId || '') }
function scope() { return `${team.selectedTeamId || ''}:${kbId()}` }
function resetMembers() { selectedMemberIds.value = kbMembers.value.filter((m) => m.status === 'active').map((m) => m.user_id) }
const membersDirty = computed(() => JSON.stringify([...selectedMemberIds.value].sort()) !== JSON.stringify(kbMembers.value.filter((m) => m.status === 'active').map((m) => m.user_id).sort()))
const titleDirty = computed(() => editing.value && (editName.value !== kb.value?.name || editDescription.value !== (kb.value?.description || '')))
useUnsavedChanges(() => titleDirty.value || membersDirty.value, () => { editing.value = false; resetMembers() })
const { items: documents, loading: documentLoading, error: documentError, hasMore: hasMoreDocuments, load: loadDocuments } = useCursorList<DocumentView>(
  () => team.selectedTeamId && kbId() ? JSON.stringify([team.selectedTeamId, kbId(), search.value]) : null,
  (key, cursor) => { const [teamId, id, query] = JSON.parse(key); return api.listDocs(teamId, id, cursor, 20, query) },
)
async function load() {
  const current = scope(), request = ++loadVersion
  if (!team.selectedTeamId || !kbId()) return
  loading.value = true; error.value = null
  try { const value = await api.getKb(team.selectedTeamId, kbId()); if (scope() === current && request === loadVersion) kb.value = value }
  catch (caught) { if (scope() === current && request === loadVersion) error.value = normalizeApiError(caught) }
  finally { if (request === loadVersion) loading.value = false }
}
async function loadTasks() {
  const current = scope(), request = ++taskVersion
  if (!team.selectedTeamId || !kbId()) return
  taskError.value = null
  try { const page = await api.listIngestions(team.selectedTeamId, null, 5, kbId()); if (scope() === current && request === taskVersion) tasks.value = page.data }
  catch (caught) { if (scope() === current && request === taskVersion) taskError.value = normalizeApiError(caught) }
}
function startEdit() {
  if (!kb.value) return
  editName.value = kb.value.name; editDescription.value = kb.value.description || ''; editVersion.value = kb.value.version
  editError.value = null; editing.value = true
}
async function saveTitle() {
  if (!kb.value || !team.selectedTeamId || saving.value) return
  if (!editName.value.trim() || editName.value.trim().length > 120 || editDescription.value.length > 2000) {
    editError.value = normalizeApiError(new Error('名称需为 1–120 字符，描述最多 2000 字符。')); return
  }
  const current = scope()
  saving.value = true; editError.value = null
  try {
    const saved = await api.updateKb({ team_id: team.selectedTeamId, kb_id: kbId(), name: editName.value.trim(), description: editDescription.value.trim() || null }, editVersion.value)
    if (scope() !== current) return
    kb.value = saved; editing.value = false; Message.success('知识库已更新')
  } catch (caught) { if (scope() === current) editError.value = normalizeApiError(caught) }
  finally { saving.value = false }
}
async function reloadTitle() {
  if (!await confirmAction('重新载入', '这会放弃当前草稿并载入最新版本。')) return
  editing.value = false; await load(); startEdit()
}
async function loadMemberScope() {
  const current = scope(), request = ++memberVersion
  if (!team.selectedTeamId || !kbId()) return
  const teamId = team.selectedTeamId, id = kbId()
  memberLoading.value = true; memberError.value = null
  try {
    const [members, allMembers] = await Promise.all([
      loadAllPages((cursor) => api.listKbMembers(teamId, id, cursor, 100)),
      canEditMembers.value ? loadAllPages((cursor) => api.listMembers(teamId, cursor, 100)) : Promise.resolve([]),
    ])
    if (scope() !== current || request !== memberVersion) return
    kbMembers.value = members; teamMembers.value = allMembers; resetMembers()
  } catch (caught) { if (scope() === current && request === memberVersion) memberError.value = normalizeApiError(caught, '无法加载知识库成员范围') }
  finally { if (request === memberVersion) memberLoading.value = false }
}
async function saveMemberScope() {
  if (!team.selectedTeamId || !canEditMembers.value || memberSaving.value) return
  const removesSelf = !selectedMemberIds.value.includes(auth.me?.user.id || '')
  if (removesSelf && !await confirmAction('移除自己的访问权限', '保存后你将无法访问这个知识库，并返回知识库列表。请确认仍有其他成员可以访问。')) return
  const current = scope()
  memberSaving.value = true; memberError.value = null
  try {
    await api.updateKbMembers({ team_id: team.selectedTeamId, kb_id: kbId(), user_ids: [...selectedMemberIds.value] })
    if (scope() !== current) return
    Message.success('成员范围已保存')
    if (removesSelf) { kbMembers.value = []; selectedMemberIds.value = []; editing.value = false; await router.push('/knowledge-bases') }
    else await loadMemberScope()
  } catch (caught) { if (scope() === current) memberError.value = normalizeApiError(caught, '无法保存知识库成员范围') }
  finally { memberSaving.value = false }
}
watch(scope, () => {
  kb.value = null; tasks.value = []; kbMembers.value = []; teamMembers.value = []; selectedMemberIds.value = []
  editing.value = false; activeTab.value = 'documents'; search.value = ''; searchDraft.value = ''
  void load(); void loadTasks(); void loadMemberScope()
}, { immediate: true })
onBeforeUnmount(() => { loadVersion++; memberVersion++; taskVersion++ })
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink to="/knowledge-bases" custom v-slot="{ href, navigate }"><a-button type="text" :href="href" @click="navigate" title="返回知识库"><ArrowLeft :size="18" /></a-button></RouterLink>
        <div class="kb-title-area">
          <template v-if="editing">
            <a-input v-model="editName" data-testid="kb-inline-name" aria-label="知识库名称" :max-length="120" :disabled="saving" @press-enter="(event: KeyboardEvent) => !event.isComposing && saveTitle()" @keydown.esc="editing = false" />
            <a-textarea v-model="editDescription" data-testid="kb-inline-description" aria-label="知识库描述" :max-length="2000" :disabled="saving" @keydown.esc="editing = false" />
            <a-alert v-if="editError" type="error">{{ editError.message }}<a-button v-if="editError.status === 409" type="text" @click="reloadTitle">重新载入最新版本</a-button></a-alert>
            <div class="row-actions"><a-button type="primary" :loading="saving" data-testid="kb-inline-save" @click="saveTitle">保存</a-button><a-button :disabled="saving" @click="editing = false">取消</a-button></div>
          </template>
          <template v-else>
            <div class="row-actions"><h2>{{ kb?.name || '知识库详情' }}</h2><a-tooltip content="编辑知识库"><a-button v-if="kb && team.canManage" type="text" aria-label="编辑知识库" data-testid="kb-inline-edit" @click="startEdit"><Pencil :size="17" /></a-button></a-tooltip></div>
            <p>{{ kb?.description || '上传文档，构建可检索的团队知识。' }}</p>
          </template>
        </div>
      </div>
      <div class="row-actions">
        <RouterLink v-if="team.canManage" :to="`/knowledge-bases/${kbId()}/settings`" custom v-slot="{ href, navigate }"><a-button :href="href" @click="navigate"><Settings2 :size="16" />策略</a-button></RouterLink>
        <RouterLink v-if="canEditContent" :to="`/knowledge-bases/${kbId()}/upload`" custom v-slot="{ href, navigate }"><a-button type="primary" :href="href" @click="navigate"><Upload :size="16" />上传文档</a-button></RouterLink>
      </div>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">{{ error.message }}<a-button type="text" @click="load">重试</a-button></a-alert>
    <div v-if="loading && !kb" class="panel loading-state"><a-spin />正在加载知识库</div>
    <template v-else-if="kb">
      <a-tabs v-model:active-key="activeTab" destroy-on-hide>
        <a-tab-pane key="documents" title="文档与任务">
      <a-card class="page-card">
        <div class="section-heading">
          <h3>文档</h3>
          <RouterLink
            v-if="canEditContent"
            :to="`/knowledge-bases/${kbId()}/upload`"
            custom
            v-slot="{ href, navigate }"
          >
            <a-button type="text" :href="href" @click="navigate">
              <Upload :size="14" />
              上传
            </a-button>
          </RouterLink>
        </div>
        <a-input-search v-model="searchDraft" placeholder="搜索文件名" allow-clear @search="search = searchDraft.trim()" @press-enter="(event: KeyboardEvent) => { if (!event.isComposing) search = searchDraft.trim() }" @clear="search = ''" class="document-search" />
        <a-alert v-if="documentError" type="error" class="page-alert">{{ documentError.message }} <a-button type="text" @click="loadDocuments()">重试</a-button></a-alert>
        <div v-if="documents.length" class="table-wrap">
          <a-table
            :data="documents"
            :loading="documentLoading"
            :pagination="false"
            row-key="id"
            :bordered="false"
            :scroll="{ x: 960 }"
          >
            <template #columns>
              <a-table-column title="文件" :width="240">
                <template #cell="{ record: document }">
                  <RouterLink :to="`/documents/${document.id}`">
                    <strong>{{ document.file_name }}</strong>
                  </RouterLink>
                  <span class="cell-subtitle">{{ statusLabel(document.source_type) }}</span>
                </template>
              </a-table-column>
              <a-table-column title="可见性">
                <template #cell="{ record: document }">
                  {{ statusLabel(document.visibility) }}
                </template>
              </a-table-column>
              <a-table-column title="分类">
                <template #cell="{ record: document }">
                  {{ statusLabel(document.data_classification) }}
                </template>
              </a-table-column>
              <a-table-column title="状态" :width="100">
                <template #cell="{ record: document }">
                  <a-tag :color="statusColor(document.doc_status)">
                    {{ statusLabel(document.doc_status) }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="版本" :width="90">
                <template #cell="{ record: document }">
                  v{{ document.version }}
                </template>
              </a-table-column>
              <a-table-column title="更新时间" :width="200">
                <template #cell="{ record: document }">
                  <span class="date-cell">{{ formatDate(document.updated_at) }}</span>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><BookOpen :size="22" /></template>
          <span>暂无文档</span>
        </a-empty>
        <div v-if="hasMoreDocuments" class="load-more"><a-button :loading="documentLoading" @click="loadDocuments(false)">加载更多文档</a-button></div>
      </a-card>

        <a-card class="page-card">
          <div class="section-heading">
            <h3>最近任务</h3>
            <RouterLink :to="{ path: '/upload-batches', query: { kbId: kbId() } }">上传批次</RouterLink>
            <RouterLink :to="{ path: '/tasks', query: { kbId: kbId() } }" custom v-slot="{ href, navigate }">
              <a-button type="text" :href="href" @click="navigate">
                <RefreshCw :size="14" />
                全部任务
              </a-button>
            </RouterLink>
          </div>
          <a-alert v-if="taskError" type="error" class="page-alert">{{ taskError.message }} <a-button type="text" @click="loadTasks">重试</a-button></a-alert>
          <div v-if="tasks.length" class="stack-list">
            <div v-for="task in tasks" :key="task.id" class="list-row">
              <div>
                <RouterLink :to="`/tasks/${task.id}`">
                  <strong>{{ task.file_name || shortId(task.id) }}</strong>
                </RouterLink>
                <span class="cell-subtitle">
                  {{ statusLabel(task.current_stage || task.status) }} ·
                  {{ task.stage_progress_pct }}%
                </span>
              </div>
              <a-tag :color="statusColor(task.status)">
                {{ statusLabel(task.status) }}
              </a-tag>
            </div>
          </div>
          <a-empty v-else class="page-empty">
            <template #image><RefreshCw :size="20" /></template>
            <span>暂无任务</span>
          </a-empty>
        </a-card>
        </a-tab-pane>
        <a-tab-pane key="members" title="成员管理">
      <a-card class="page-card member-scope-panel">
        <div class="section-heading">
          <div class="section-title-with-icon">
            <Users :size="18" />
            <h3>成员范围</h3>
          </div>
          <span class="muted-text">{{ kbMembers.length }} 人</span>
        </div>
        <a-alert
          v-if="memberError"
          type="error"
          class="page-alert member-scope-error"
        >
          <strong>{{ memberError.message }}</strong>
          <span v-if="memberError.requestId">
            请求 ID：{{ memberError.requestId }}
          </span>
          <a-button
            data-testid="kb-member-retry"
            @click="loadMemberScope"
            type="text"
            html-type="button"
          >
            重试
          </a-button>
        </a-alert>
        <div v-else-if="memberLoading" class="loading-state compact">
          <a-spin />
          <span>正在加载成员范围</span>
        </div>
        <template v-else>
          <div v-if="kbMembers.length" class="kb-member-scope-list">
            <div
              v-for="member in kbMembers"
              :key="member.user_id"
              class="kb-member-scope-row"
            >
              <div>
                <strong>{{ member.display_name }}</strong>
                <span class="cell-subtitle">{{ member.email }}</span>
              </div>
              <a-tag :color="statusColor(member.status)">
                {{ statusLabel(member.status) }}
              </a-tag>
            </div>
          </div>
          <a-empty v-else class="page-empty">
            <template #image><Users :size="20" /></template>
            <span>尚未设置知识库成员范围</span>
          </a-empty>

          <div v-if="canEditMembers" class="kb-member-editor">
            <div class="member-editor-heading">
              <div>
                <h4>编辑成员范围</h4>
                <p>选择可以访问知识库的团队成员；保存后立即生效。</p>
              </div>
              <span class="muted-text">
                已选 {{ selectedMemberIds.length }} 人
              </span>
            </div>
            <div v-if="activeTeamMembers.length" class="kb-member-option-list">
              <a-checkbox
                v-for="member in activeTeamMembers"
                :key="member.user_id"
                class="kb-member-option"
                v-model="selectedMemberIds"
                :data-testid="`kb-member-option-${member.user_id}`"
                :value="member.user_id"
                :disabled="memberSaving"
              >
                <span>
                  <strong>{{ member.display_name }}</strong>
                  <small>
                    {{ member.email }} · {{ memberRoleLabels[member.role] }}
                  </small>
                </span>
              </a-checkbox>
            </div>
            <a-empty v-else class="page-empty">
              <template #image><Users :size="20" /></template>
              <span>暂无可用团队成员</span>
            </a-empty>
            <div class="member-editor-actions">
              <a-button @click="resetMembers" :disabled="memberSaving || !membersDirty">取消修改</a-button>
              <a-button
                data-testid="kb-member-save"
                :disabled="memberSaving || !activeTeamMembers.length || !membersDirty"
                @click="saveMemberScope"
                type="primary"
                html-type="button"
              >
                <Save :size="16" />
                {{ memberSaving ? '保存中' : '保存成员范围' }}
              </a-button>
            </div>
          </div>
          <a-alert v-else type="info" class="page-alert member-readonly-note">
            <strong>只读范围</strong>
            <span>仅团队管理员或平台管理员可以修改知识库成员范围。</span>
          </a-alert>
        </template>
      </a-card>

        </a-tab-pane>
      </a-tabs>
    </template>
  </div>
</template>
<style scoped>
.date-cell { white-space: nowrap; }
.kb-title-area { min-width: 0; display: grid; gap: 8px; max-width: 640px; }
.kb-title-area h2 { overflow-wrap: anywhere; }
.document-search { max-width: 420px; margin-bottom: 16px; }

.member-scope-panel {
  margin-bottom: 16px;
}

.section-title-with-icon {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-title-with-icon h3 {
  margin: 0;
}

.member-scope-error {
  margin-bottom: 12px;
}

.kb-member-scope-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0 18px;
}

.kb-member-scope-row {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #edf0f3;
  padding: 10px 0;
}

.kb-member-scope-row > div {
  min-width: 0;
}

.kb-member-scope-row strong,
.kb-member-scope-row .cell-subtitle {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-member-editor {
  margin-top: 16px;
  border-top: 1px solid #edf0f3;
  padding-top: 16px;
}

.member-editor-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.member-editor-heading h4,
.member-editor-heading p {
  margin: 0;
}

.member-editor-heading h4 {
  font-size: 14px;
}

.member-editor-heading p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.kb-member-option-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.kb-member-option {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 9px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 9px 10px;
}

.kb-member-option span {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.kb-member-option strong,
.kb-member-option small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-member-option strong {
  color: var(--text);
  font-size: 13px;
}

.kb-member-option small {
  color: var(--muted);
  font-size: 11px;
}

.member-editor-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.member-readonly-note {
  margin-top: 14px;
}

@media (max-width: 720px) {
  .member-editor-heading {
    align-items: stretch;
    flex-direction: column;
    gap: 6px;
  }

  .kb-member-scope-list,
  .kb-member-option-list {
    grid-template-columns: 1fr;
  }
}
</style>
