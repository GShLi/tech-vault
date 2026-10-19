<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowLeft,
  BookOpen,
  GitBranch,
  RefreshCw,
  Save,
  Settings2,
  Upload,
  Users,
} from 'lucide-vue-next'

import { api, ApiRequestError, loadAllPages } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type {
  DocumentView,
  IngestionRun,
  KnowledgeBase,
  KnowledgeBaseMemberView,
  SourceConnection,
  TeamMemberView,
} from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'

const route = useRoute()
const team = useTeamStore()
const kb = ref<KnowledgeBase | null>(null)
const documents = ref<DocumentView[]>([])
const sources = ref<SourceConnection[]>([])
const tasks = ref<IngestionRun[]>([])
const kbMembers = ref<KnowledgeBaseMemberView[]>([])
const teamMembers = ref<TeamMemberView[]>([])
const selectedMemberIds = ref<string[]>([])
const loading = ref(false)
const memberLoading = ref(false)
const memberSaving = ref(false)
const error = ref<ApiRequestError | null>(null)
const memberError = ref<ApiRequestError | null>(null)

const canEditMembers = computed(() => team.canManage)
const canEditContent = computed(
  () =>
    team.currentMembership?.role === 'leader' ||
    team.currentMembership?.role === 'member',
)

const memberRoleLabels: Record<TeamMemberView['role'], string> = {
  leader: '团队管理员',
  member: '成员',
  viewer: '只读成员',
}

const activeTeamMembers = computed(() =>
  teamMembers.value.filter((member) => member.status === 'active'),
)

function kbId(): string {
  return String(route.params.kbId ?? '')
}

async function load(): Promise<void> {
  if (!team.selectedTeamId || !kbId()) return
  loading.value = true
  error.value = null
  try {
    const [kbView, documentRows, sourceRows, taskRows] = await Promise.all([
      api.getKb(team.selectedTeamId, kbId()),
      loadAllPages((cursor) =>
        api.listDocs(team.selectedTeamId!, kbId(), cursor, 100),
      ),
      loadAllPages((cursor) =>
        api.listSources(team.selectedTeamId!, kbId(), cursor, 100),
      ),
      loadAllPages((cursor) =>
        api.listIngestions(team.selectedTeamId!, cursor, 100),
      ),
    ])
    kb.value = kbView
    documents.value = documentRows
    sources.value = sourceRows
    tasks.value = taskRows.slice(0, 5)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
  if (kb.value) await loadMemberScope()
}

onMounted(load)
watch(() => route.params.kbId, load)
watch(() => team.selectedTeamId, load)

function toMemberError(caught: unknown, fallback: string): ApiRequestError {
  if (caught instanceof ApiRequestError) return caught
  return new ApiRequestError(caught instanceof Error ? caught.message : fallback)
}

async function loadMemberScope(): Promise<void> {
  if (!team.selectedTeamId || !kbId()) return
  memberLoading.value = true
  memberError.value = null
  try {
    kbMembers.value = await loadAllPages((cursor) =>
      api.listKbMembers(team.selectedTeamId!, kbId(), cursor, 100),
    )
    selectedMemberIds.value = kbMembers.value
      .filter((member) => member.status === 'active')
      .map((member) => member.user_id)

    if (canEditMembers.value) {
      teamMembers.value = await loadAllPages((cursor) =>
        api.listMembers(team.selectedTeamId!, cursor, 100),
      )
    } else {
      teamMembers.value = []
    }
  } catch (caught) {
    memberError.value = toMemberError(caught, '无法加载知识库成员范围')
  } finally {
    memberLoading.value = false
  }
}

async function saveMemberScope(): Promise<void> {
  if (!team.selectedTeamId || !kbId() || !canEditMembers.value) return
  memberSaving.value = true
  memberError.value = null
  try {
    await api.updateKbMembers({
      team_id: team.selectedTeamId,
      kb_id: kbId(),
      user_ids: [...selectedMemberIds.value],
    })
    await loadMemberScope()
  } catch (caught) {
    memberError.value = toMemberError(caught, '无法保存知识库成员范围')
  } finally {
    memberSaving.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink class="icon-button" to="/knowledge-bases" title="返回知识库"><ArrowLeft :size="18" /></RouterLink>
        <div><h2>{{ kb?.name || '知识库详情' }}</h2><p>{{ kb?.description || '文档、来源与索引状态。' }}</p></div>
      </div>
      <div v-if="team.canManage || canEditContent" class="row-actions">
        <RouterLink v-if="team.canManage" class="secondary-button" :to="`/knowledge-bases/${kbId()}/settings`"><Settings2 :size="16" />策略</RouterLink>
        <RouterLink v-if="canEditContent" class="secondary-button" :to="`/knowledge-bases/${kbId()}/sources/github`"><GitBranch :size="16" />来源</RouterLink>
        <RouterLink v-if="canEditContent" class="primary-button" :to="`/knowledge-bases/${kbId()}/upload`"><Upload :size="16" />上传文档</RouterLink>
      </div>
    </div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span><button class="inline-link" type="button" @click="load">重试</button></div>
    <div v-if="loading && !kb" class="panel loading-state"><a-spin /><span>正在加载知识库</span></div>
    <template v-else-if="kb">
      <div class="metric-grid">
        <article class="metric-card"><span>文档数量</span><strong>{{ documents.length }}</strong></article>
        <article class="metric-card"><span>来源数量</span><strong>{{ sources.length }}</strong></article>
        <article class="metric-card"><span>默认策略</span><strong class="metric-text">{{ statusLabel(kb.default_model_policy_mode) }}</strong></article>
      </div>

      <section class="panel detail-panel member-scope-panel">
        <div class="section-heading">
          <div class="section-title-with-icon">
            <Users :size="18" />
            <h3>成员范围</h3>
          </div>
          <span class="muted-text">{{ kbMembers.length }} 人</span>
        </div>

        <div v-if="memberError" class="error-banner member-scope-error" role="alert">
          <strong>{{ memberError.message }}</strong>
          <span v-if="memberError.requestId">请求 ID：{{ memberError.requestId }}</span>
          <button class="inline-link" data-testid="kb-member-retry" type="button" @click="loadMemberScope">重试</button>
        </div>

        <div v-else-if="memberLoading" class="loading-state compact">
          <a-spin />
          <span>正在加载成员范围</span>
        </div>

        <template v-else>
          <div v-if="kbMembers.length" class="kb-member-scope-list">
            <div v-for="member in kbMembers" :key="member.user_id" class="kb-member-scope-row">
              <div>
                <strong>{{ member.display_name }}</strong>
                <span class="cell-subtitle">{{ member.email }}</span>
              </div>
              <StatusPill :status="member.status" />
            </div>
          </div>
          <div v-else class="empty-state compact">
            <Users :size="20" />
            <span>尚未设置知识库成员范围</span>
          </div>

          <div v-if="canEditMembers" class="kb-member-editor">
            <div class="member-editor-heading">
              <div>
                <h4>编辑成员范围</h4>
                <p>可选择所有 active 团队成员，保存后将立即刷新范围。</p>
              </div>
              <span class="muted-text">已选 {{ selectedMemberIds.length }} 人</span>
            </div>
            <div v-if="activeTeamMembers.length" class="kb-member-option-list">
              <label v-for="member in activeTeamMembers" :key="member.user_id" class="kb-member-option">
                <input
                  v-model="selectedMemberIds"
                  :data-testid="`kb-member-option-${member.user_id}`"
                  type="checkbox"
                  :value="member.user_id"
                  :disabled="memberSaving"
                />
                <span>
                  <strong>{{ member.display_name }}</strong>
                  <small>{{ member.email }} · {{ memberRoleLabels[member.role] }}</small>
                </span>
              </label>
            </div>
            <div v-else class="empty-state compact">
              <Users :size="20" />
              <span>暂无 active 团队成员</span>
            </div>
            <div class="member-editor-actions">
              <button
                class="primary-button"
                data-testid="kb-member-save"
                type="button"
                :disabled="memberSaving || !activeTeamMembers.length"
                @click="saveMemberScope"
              >
                <Save :size="16" />
                {{ memberSaving ? '保存中' : '保存成员范围' }}
              </button>
            </div>
          </div>
          <div v-else class="notice-box member-readonly-note">
            <strong>只读范围</strong>
            <span>仅团队管理员或平台管理员可以修改知识库成员范围。</span>
          </div>
        </template>
      </section>

      <section class="panel detail-panel">
        <div class="section-heading"><h3>文档</h3><RouterLink v-if="canEditContent" class="ghost-button" :to="`/knowledge-bases/${kbId()}/upload`"><Upload :size="14" />上传</RouterLink></div>
        <div v-if="documents.length" class="table-wrap">
          <table><thead><tr><th>文件</th><th>可见性</th><th>分类</th><th>状态</th><th>版本</th><th>更新时间</th></tr></thead><tbody><tr v-for="document in documents" :key="document.id"><td data-label="文件"><RouterLink :to="`/documents/${document.id}`"><strong>{{ document.file_name }}</strong></RouterLink><span class="cell-subtitle">{{ document.source_type }}</span></td><td data-label="可见性">{{ document.visibility }}</td><td data-label="分类">{{ document.data_classification }}</td><td data-label="状态"><StatusPill :status="document.doc_status" /></td><td data-label="版本">v{{ document.version }}</td><td data-label="更新时间">{{ formatDate(document.updated_at) }}</td></tr></tbody></table>
        </div>
        <div v-else class="empty-state compact"><BookOpen :size="22" /><span>暂无文档</span></div>
      </section>

      <div class="split-grid">
        <section class="panel detail-panel">
          <div class="section-heading"><h3>来源</h3><RouterLink class="ghost-button" :to="`/knowledge-bases/${kbId()}/sources/github`"><GitBranch :size="14" />管理</RouterLink></div>
          <div v-if="sources.length" class="stack-list"><div v-for="source in sources" :key="source.id" class="list-row"><div><strong>{{ source.repo_url }}</strong><span class="cell-subtitle">{{ source.branch }} · {{ formatDate(source.updated_at) }}</span></div><StatusPill :status="source.status" /></div></div>
          <div v-else class="empty-state compact"><GitBranch :size="20" /><span>暂无外部来源</span></div>
        </section>
        <section class="panel detail-panel">
          <div class="section-heading"><h3>最近任务</h3><RouterLink class="ghost-button" to="/tasks"><RefreshCw :size="14" />全部任务</RouterLink></div>
          <div v-if="tasks.length" class="stack-list"><div v-for="task in tasks" :key="task.id" class="list-row"><div><RouterLink :to="`/tasks/${task.id}`"><strong>{{ shortId(task.id) }}</strong></RouterLink><span class="cell-subtitle">{{ task.current_stage || task.status }} · {{ task.stage_progress_pct }}%</span></div><StatusPill :status="task.status" /></div></div>
          <div v-else class="empty-state compact"><RefreshCw :size="20" /><span>暂无任务</span></div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
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

.kb-member-option input {
  margin-top: 3px;
  accent-color: var(--accent);
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

  .member-editor-actions .primary-button {
    width: 100%;
  }
}
</style>
