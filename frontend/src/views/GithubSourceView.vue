<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, GitBranch, KeyRound, Pause, Pencil, Play, Plus, RefreshCw, Save, Trash2, X } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { CredentialView, KnowledgeBase, SourceConnection } from '@/types/api'
import { formatDate, parseLines } from '@/utils/format'

const route = useRoute()
const auth = useAuthStore()
const team = useTeamStore()
const kb = ref<KnowledgeBase | null>(null)
const sources = ref<SourceConnection[]>([])
const credentials = ref<CredentialView[]>([])
const loading = ref(false)
const loadingMoreSources = ref(false)
const loadingMoreCredentials = ref(false)
const sourcesNextCursor = ref<string | null>(null)
const credentialsNextCursor = ref<string | null>(null)
const sourcesHasMore = ref(false)
const credentialsHasMore = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)
const repoUrl = ref('')
const branch = ref('main')
const pathFilters = ref('')
const credentialId = ref('')
const credentialName = ref('')
const credentialSecret = ref('')
const editingSourceId = ref('')
const editRepoUrl = ref('')
const editBranch = ref('main')
const editPathFilters = ref('')
const editCredentialId = ref('')
const canCreateSource = computed(
  () =>
    team.currentMembership?.role === 'leader' ||
    team.currentMembership?.role === 'member' ||
    auth.me?.user.is_super_admin === true,
)

function sourceCreatedBy(source: SourceConnection): string | null {
  return (source as SourceConnection & { created_by?: string | null }).created_by ?? null
}

function canManageSource(source: SourceConnection): boolean {
  return (
    team.canManage ||
    auth.me?.user.is_super_admin === true ||
    sourceCreatedBy(source) === auth.me?.user.id
  )
}

function kbId(): string {
  return String(route.params.kbId ?? '')
}

async function load(): Promise<void> {
  if (!team.selectedTeamId || !kbId()) return
  loading.value = true
  error.value = null
  try {
    const [kbView, sourcePage, credentialPage] = await Promise.all([
      api.getKb(team.selectedTeamId, kbId()),
      api.listSources(team.selectedTeamId, kbId()),
      api.listCredentials(team.selectedTeamId),
    ])
    kb.value = kbView
    sources.value = sourcePage.data
    credentials.value = credentialPage.data
    sourcesNextCursor.value = sourcePage.meta.next_cursor
    credentialsNextCursor.value = credentialPage.meta.next_cursor
    sourcesHasMore.value = sourcePage.meta.has_more
    credentialsHasMore.value = credentialPage.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadMoreSources(): Promise<void> {
  if (!team.selectedTeamId || !sourcesNextCursor.value) return
  loadingMoreSources.value = true
  try {
    const page = await api.listSources(
      team.selectedTeamId,
      kbId(),
      sourcesNextCursor.value,
    )
    sources.value = [...sources.value, ...page.data]
    sourcesNextCursor.value = page.meta.next_cursor
    sourcesHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreSources.value = false
  }
}

async function loadMoreCredentials(): Promise<void> {
  if (!team.selectedTeamId || !credentialsNextCursor.value) return
  loadingMoreCredentials.value = true
  try {
    const page = await api.listCredentials(
      team.selectedTeamId,
      credentialsNextCursor.value,
    )
    credentials.value = [...credentials.value, ...page.data]
    credentialsNextCursor.value = page.meta.next_cursor
    credentialsHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreCredentials.value = false
  }
}

async function createSource(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    await api.createGithubSource({
      team_id: team.selectedTeamId,
      kb_id: kbId(),
      repo_url: repoUrl.value.trim(),
      branch: branch.value.trim() || 'main',
      path_filters: parseLines(pathFilters.value),
      credentials_id: credentialId.value || null,
    })
    Message.success('GitHub 来源已添加')
    repoUrl.value = ''
    pathFilters.value = ''
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

async function createCredential(): Promise<void> {
  if (!team.selectedTeamId) return
  saving.value = true
  error.value = null
  try {
    await api.createCredential(team.selectedTeamId, credentialName.value.trim(), credentialSecret.value)
    Message.success('凭据已创建')
    credentialName.value = ''
    credentialSecret.value = ''
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

function startEditSource(source: SourceConnection): void {
  editingSourceId.value = source.id
  editRepoUrl.value = source.repo_url
  editBranch.value = source.branch
  editPathFilters.value = source.path_filters.join('\n')
  editCredentialId.value = source.credentials_id ?? ''
}

function cancelEditSource(): void {
  editingSourceId.value = ''
}

async function saveSource(source: SourceConnection): Promise<void> {
  if (!team.selectedTeamId || !canManageSource(source)) return
  saving.value = true
  error.value = null
  try {
    await api.updateSource({
      team_id: team.selectedTeamId,
      source_id: source.id,
      repo_url: editRepoUrl.value.trim(),
      branch: editBranch.value.trim() || 'main',
      path_filters: parseLines(editPathFilters.value),
      credentials_id: editCredentialId.value || null,
    })
    Message.success('GitHub 来源已更新')
    editingSourceId.value = ''
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

async function runAction(action: 'sync' | 'pause' | 'resume' | 'delete', source: SourceConnection): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    if (action === 'sync') await api.syncSource(team.selectedTeamId, source.id)
    if (action === 'pause') await api.pauseSource(team.selectedTeamId, source.id)
    if (action === 'resume') await api.resumeSource(team.selectedTeamId, source.id)
    if (action === 'delete') await api.deleteSource(team.selectedTeamId, source.id)
    Message.success('来源状态已更新')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function deleteCredential(item: CredentialView): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    await api.deleteCredential(team.selectedTeamId, item.id)
    Message.success('凭据已删除')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(load)
watch(() => route.params.kbId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink class="icon-button" :to="`/knowledge-bases/${kbId()}`" title="返回知识库"><ArrowLeft :size="18" /></RouterLink>
        <div><h2>GitHub 来源</h2><p>{{ kb?.name || '知识库' }} · 仓库同步、路径白名单与凭据。</p></div>
      </div>
      <button class="secondary-button" type="button" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button>
    </div>

    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>

    <div class="split-grid source-grid">
      <section class="panel detail-panel">
        <div class="section-heading"><h3>已连接来源</h3><span class="muted-text">{{ sources.length }} 个</span></div>
        <div v-if="loading && !sources.length" class="loading-state compact"><a-spin /><span>正在加载来源</span></div>
        <div v-else-if="!sources.length" class="empty-state compact"><GitBranch :size="22" /><span>当前知识库还没有 GitHub 来源</span></div>
        <div v-else class="stack-list">
          <article v-for="source in sources" :key="source.id" class="list-card">
            <div class="list-card-heading">
              <div><strong>{{ source.repo_url }}</strong><span class="cell-subtitle">{{ source.branch }} · {{ source.path_filters.join(', ') || '全仓库' }}</span></div>
              <StatusPill :status="source.status" />
            </div>
            <div class="list-card-meta"><span>最近游标：{{ source.sync_cursor || '—' }}</span><span>{{ formatDate(source.updated_at) }}</span></div>
            <form v-if="editingSourceId === source.id" class="form-grid source-editor" @submit.prevent="saveSource(source)">
              <label class="field"><span>仓库 URL</span><input v-model="editRepoUrl" type="url" required /></label>
              <label class="field"><span>分支</span><input v-model="editBranch" type="text" /></label>
              <label class="field source-editor-wide"><span>路径白名单（逗号或换行）</span><textarea v-model="editPathFilters" rows="3" /></label>
              <label class="field source-editor-wide"><span>访问凭据</span><select v-model="editCredentialId"><option value="">不使用凭据</option><option v-for="item in credentials" :key="item.id" :value="item.id">{{ item.name }} ({{ item.secret_masked }})</option></select></label>
              <div class="row-actions source-editor-wide">
                <button class="ghost-button" type="button" :disabled="saving" @click="cancelEditSource"><X :size="14" />取消</button>
                <button class="primary-button" type="submit" :disabled="saving"><Save :size="14" />保存</button>
              </div>
            </form>
            <div class="row-actions" v-if="canManageSource(source)">
              <button v-if="editingSourceId !== source.id" class="ghost-button" type="button" @click="startEditSource(source)"><Pencil :size="14" />编辑</button>
              <button class="ghost-button" type="button" @click="runAction('sync', source)"><RefreshCw :size="14" />同步</button>
              <button v-if="source.status !== 'paused'" class="ghost-button" type="button" @click="runAction('pause', source)"><Pause :size="14" />暂停</button>
              <button v-else class="ghost-button" type="button" @click="runAction('resume', source)"><Play :size="14" />恢复</button>
              <button class="ghost-button danger-text" type="button" @click="runAction('delete', source)"><Trash2 :size="14" />删除</button>
            </div>
          </article>
        </div>
        <div v-if="sourcesHasMore" class="load-more">
          <button class="secondary-button" type="button" :disabled="loadingMoreSources" @click="loadMoreSources">
            {{ loadingMoreSources ? '加载中' : '加载更多来源' }}
          </button>
        </div>
      </section>

      <section class="panel detail-panel">
        <div class="section-heading"><h3>添加仓库</h3><GitBranch :size="16" /></div>
        <form v-if="canCreateSource" class="form-stack" @submit.prevent="createSource">
          <label class="field"><span>仓库 URL</span><input v-model="repoUrl" type="url" required placeholder="https://github.com/org/repo" /></label>
          <label class="field"><span>分支</span><input v-model="branch" type="text" /></label>
          <label class="field"><span>路径白名单（逗号或换行）</span><textarea v-model="pathFilters" rows="3" placeholder="docs/**\n*.md" /></label>
          <label class="field"><span>访问凭据</span><select v-model="credentialId"><option value="">不使用凭据</option><option v-for="item in credentials" :key="item.id" :value="item.id">{{ item.name }} ({{ item.secret_masked }})</option></select></label>
          <button class="primary-button" type="submit" :disabled="saving"><Plus :size="16" />添加来源</button>
        </form>
        <div v-else class="notice-box"><strong>只读访问</strong><span>只读成员不能创建 GitHub 来源。</span></div>
      </section>
    </div>

    <section class="panel detail-panel">
      <div class="section-heading"><h3>团队凭据</h3><KeyRound :size="16" /></div>
      <div class="split-grid compact-split">
        <div>
          <div v-if="credentials.length" class="stack-list">
            <div v-for="item in credentials" :key="item.id" class="list-row">
              <div><strong>{{ item.name }}</strong><span class="cell-subtitle">{{ item.secret_masked }} · {{ formatDate(item.created_at) }}</span></div>
              <button v-if="team.canManage" class="ghost-button danger-text" type="button" @click="deleteCredential(item)">删除</button>
            </div>
          </div>
          <div v-else class="empty-state compact"><KeyRound :size="20" /><span>暂无凭据</span></div>
          <div v-if="credentialsHasMore" class="load-more">
            <button class="secondary-button" type="button" :disabled="loadingMoreCredentials" @click="loadMoreCredentials">
              {{ loadingMoreCredentials ? '加载中' : '加载更多凭据' }}
            </button>
          </div>
        </div>
        <form class="form-stack" @submit.prevent="createCredential">
          <label class="field"><span>凭据名称</span><input v-model="credentialName" type="text" required /></label>
          <label class="field"><span>Token / Secret</span><input v-model="credentialSecret" type="password" required autocomplete="new-password" /></label>
          <button class="secondary-button" type="submit" :disabled="saving || !team.canManage">保存凭据</button>
        </form>
      </div>
    </section>
  </div>
</template>

<style scoped>
.source-editor {
  margin-top: 12px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

.source-editor-wide {
  grid-column: 1 / -1;
}

@media (max-width: 720px) {
  .source-editor-wide {
    grid-column: auto;
  }
}
</style>
