<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Boxes, Download, FileClock, FileText, Pencil, RefreshCw, RotateCcw, Save, ShieldCheck, Trash2, UserPlus, Wrench, X } from 'lucide-vue-next'
import { Message, Modal } from '@arco-design/web-vue'

import { api, ApiRequestError, loadAllPages } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { ChunkView, DocumentDetailView, DocumentGrantView, DocumentVersion, IngestionRun, TeamMemberView } from '@/types/api'
import { downloadBlob, formatBytes, formatDate, parseLines, shortId } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const team = useTeamStore()
const document = ref<DocumentDetailView | null>(null)
const versions = ref<DocumentVersion[]>([])
const chunks = ref<ChunkView[]>([])
const tasks = ref<IngestionRun[]>([])
const grants = ref<DocumentGrantView[]>([])
const teamMembers = ref<TeamMemberView[]>([])
const loading = ref(false)
const rebuilding = ref(false)
const downloading = ref(false)
const deleting = ref(false)
const restoring = ref(false)
const editingMetadata = ref(false)
const savingMetadata = ref(false)
const savingGrant = ref(false)
const grantUserId = ref('')
const error = ref<ApiRequestError | null>(null)
const versionsNextCursor = ref<string | null>(null)
const chunksNextCursor = ref<string | null>(null)
const tasksNextCursor = ref<string | null>(null)
const versionsHasMore = ref(false)
const chunksHasMore = ref(false)
const tasksHasMore = ref(false)
const loadingMoreVersions = ref(false)
const loadingMoreChunks = ref(false)
const loadingMoreTasks = ref(false)
const metadataForm = ref({
  file_name: '',
  product: '',
  visibility: 'team_shared',
  data_classification: 'internal',
  version_values: '',
})

const documentId = () => String(route.params.documentId ?? '')
const canManageDocument = computed(
  () =>
    Boolean(document.value) &&
    (document.value?.owner_user_id === auth.me?.user.id ||
      team.canManage ||
      auth.me?.user.is_super_admin === true),
)
const grantCandidates = computed(() => {
  const granted = new Set(grants.value.map((item) => item.user_id))
  return teamMembers.value.filter(
    (member) =>
      member.status === 'active' &&
      member.user_id !== document.value?.owner_user_id &&
      !granted.has(member.user_id),
  )
})

function memberName(userId: string): string {
  const member = teamMembers.value.find((item) => item.user_id === userId)
  return member ? `${member.display_name} (${member.email})` : shortId(userId)
}

async function load(): Promise<void> {
  if (!team.selectedTeamId || !documentId()) return
  loading.value = true
  error.value = null
  try {
    const [documentView, versionPage, chunkPage, taskPage] = await Promise.all([
      api.getDoc(team.selectedTeamId, documentId()),
      api.listDocumentVersions(team.selectedTeamId, documentId()),
      api.listDocumentChunks(team.selectedTeamId, documentId()),
      api.getDocumentTasks(team.selectedTeamId, documentId()),
    ])
    document.value = documentView
    versions.value = versionPage.data
    chunks.value = chunkPage.data
    tasks.value = taskPage.data
    versionsNextCursor.value = versionPage.meta.next_cursor
    chunksNextCursor.value = chunkPage.meta.next_cursor
    tasksNextCursor.value = taskPage.meta.next_cursor
    versionsHasMore.value = versionPage.meta.has_more
    chunksHasMore.value = chunkPage.meta.has_more
    tasksHasMore.value = taskPage.meta.has_more
    if (canManageDocument.value) await loadShareData()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadShareData(): Promise<void> {
  if (!team.selectedTeamId || !document.value || !canManageDocument.value) return
  const [grantRows, memberRows] = await Promise.all([
    loadAllPages((cursor) =>
      api.listDocumentGrants(
        team.selectedTeamId!,
        document.value!.id,
        cursor,
        100,
      ),
    ),
    loadAllPages((cursor) =>
      api.listMembers(team.selectedTeamId!, cursor, 100),
    ),
  ])
  grants.value = grantRows
  teamMembers.value = memberRows.filter((member) => member.status === 'active')
}

function beginMetadataEdit(): void {
  if (!document.value) return
  metadataForm.value = {
    file_name: document.value.file_name,
    product: document.value.product ?? '',
    visibility: document.value.visibility,
    data_classification: document.value.data_classification,
    version_values: document.value.version_values.join('\n'),
  }
  editingMetadata.value = true
}

async function saveMetadata(): Promise<void> {
  if (!team.selectedTeamId || !document.value || !canManageDocument.value) return
  if (!metadataForm.value.file_name.trim()) return
  savingMetadata.value = true
  error.value = null
  try {
    const updated = await api.updateDoc(
      {
        team_id: team.selectedTeamId,
        document_id: document.value.id,
        file_name: metadataForm.value.file_name.trim(),
        product: metadataForm.value.product.trim() || null,
        visibility: metadataForm.value.visibility,
        data_classification: metadataForm.value.data_classification,
        version_values: parseLines(metadataForm.value.version_values),
      },
      document.value.version,
    )
    document.value = { ...document.value, ...updated }
    editingMetadata.value = false
    Message.success('文档元数据已更新')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    savingMetadata.value = false
  }
}

async function addGrant(): Promise<void> {
  if (
    !team.selectedTeamId ||
    !document.value ||
    !grantUserId.value ||
    !canManageDocument.value
  ) return
  savingGrant.value = true
  error.value = null
  try {
    await api.createDocumentGrant(
      team.selectedTeamId,
      document.value.id,
      grantUserId.value,
    )
    grantUserId.value = ''
    await loadShareData()
    Message.success('文档授权已添加')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    savingGrant.value = false
  }
}

async function revokeGrant(grantId: string): Promise<void> {
  if (!team.selectedTeamId || !canManageDocument.value) return
  savingGrant.value = true
  error.value = null
  try {
    await api.revokeDocumentGrant(team.selectedTeamId, grantId)
    await loadShareData()
    Message.success('文档授权已撤销')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    savingGrant.value = false
  }
}

async function loadMoreVersions(): Promise<void> {
  if (!team.selectedTeamId || !documentId() || !versionsNextCursor.value) return
  loadingMoreVersions.value = true
  try {
    const page = await api.listDocumentVersions(
      team.selectedTeamId,
      documentId(),
      versionsNextCursor.value,
    )
    versions.value = [...versions.value, ...page.data]
    versionsNextCursor.value = page.meta.next_cursor
    versionsHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreVersions.value = false
  }
}

async function loadMoreChunks(): Promise<void> {
  if (!team.selectedTeamId || !documentId() || !chunksNextCursor.value) return
  loadingMoreChunks.value = true
  try {
    const page = await api.listDocumentChunks(
      team.selectedTeamId,
      documentId(),
      chunksNextCursor.value,
    )
    chunks.value = [...chunks.value, ...page.data]
    chunksNextCursor.value = page.meta.next_cursor
    chunksHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreChunks.value = false
  }
}

async function loadMoreTasks(): Promise<void> {
  if (!team.selectedTeamId || !documentId() || !tasksNextCursor.value) return
  loadingMoreTasks.value = true
  try {
    const page = await api.getDocumentTasks(
      team.selectedTeamId,
      documentId(),
      tasksNextCursor.value,
    )
    tasks.value = [...tasks.value, ...page.data]
    tasksNextCursor.value = page.meta.next_cursor
    tasksHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreTasks.value = false
  }
}

async function download(): Promise<void> {
  if (!team.selectedTeamId || !document.value) return
  downloading.value = true
  error.value = null
  try {
    const blob = await api.downloadDocument(team.selectedTeamId, document.value.id)
    downloadBlob(blob, document.value.file_name)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    downloading.value = false
  }
}

async function rebuild(): Promise<void> {
  if (!team.selectedTeamId || !document.value) return
  rebuilding.value = true
  error.value = null
  try {
    const result = await api.rebuildDocument(team.selectedTeamId, document.value.id)
    Message.success(`重建任务已创建：${shortId(result.ingestion_run_id)}`)
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    rebuilding.value = false
  }
}

function confirmAction(title: string, content: string): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title,
      content,
      okText: '删除',
      cancelText: '取消',
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    })
  })
}

async function remove(): Promise<void> {
  if (!team.selectedTeamId || !document.value) return
  if (!(await confirmAction('删除文档', '删除后立即停止召回，并在保留期内允许恢复。确定继续吗？'))) return
  deleting.value = true
  error.value = null
  try {
    await api.deleteDocument(team.selectedTeamId, document.value.id)
    Message.success('文档已删除，可在保留期内恢复')
    await router.push(`/knowledge-bases/${document.value.knowledge_base_id}`)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    deleting.value = false
  }
}

async function restore(): Promise<void> {
  if (!team.selectedTeamId || !document.value) return
  restoring.value = true
  error.value = null
  try {
    await api.restoreDocument(team.selectedTeamId, document.value.id)
    Message.success('文档已恢复并重新提交入库')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    restoring.value = false
  }
}

onMounted(load)
watch(() => route.params.documentId, load)
</script>

<template>
  <div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !document" class="panel loading-state"><a-spin /><span>正在加载文档</span></div>
    <template v-else-if="document">
      <div class="page-header">
        <div class="heading-with-back">
          <RouterLink class="icon-button" :to="`/knowledge-bases/${document.knowledge_base_id}`" title="返回知识库"><FileText :size="18" /></RouterLink>
          <div><h2>{{ document.file_name }}</h2><p>{{ document.source_type }} · 知识库 {{ shortId(document.knowledge_base_id) }}</p></div>
        </div>
        <div class="row-actions">
          <button v-if="document.doc_status !== 'deleted'" class="secondary-button" type="button" :disabled="downloading" @click="download"><Download :size="16" />{{ downloading ? '下载中' : '下载原文' }}</button>
          <button v-if="canManageDocument && document.doc_status !== 'deleted'" class="secondary-button" type="button" @click="beginMetadataEdit"><Pencil :size="16" />编辑元数据</button>
          <button v-if="canManageDocument && document.doc_status !== 'deleted'" class="primary-button" type="button" :disabled="rebuilding" @click="rebuild"><Wrench :size="16" />{{ rebuilding ? '提交中' : '重建索引' }}</button>
          <button v-if="canManageDocument && document.doc_status === 'deleted'" class="secondary-button" type="button" :disabled="restoring" @click="restore"><RotateCcw :size="16" />{{ restoring ? '恢复中' : '恢复文档' }}</button>
          <button v-else-if="canManageDocument" class="secondary-button danger-text" type="button" :disabled="deleting" @click="remove"><Trash2 :size="16" />{{ deleting ? '删除中' : '删除文档' }}</button>
        </div>
      </div>

      <div v-if="document.doc_status === 'deleted'" class="notice-box" data-testid="document-deleted-notice">
        <strong>文档已停止召回</strong>
        <span>可在保留期内恢复；超过保留期后将清理原始文件、索引和缓存。</span>
      </div>

      <section class="panel detail-panel">
        <div class="detail-heading">
          <div class="detail-icon"><FileText :size="20" /></div>
          <div><h3>元数据</h3><p>文档 v{{ document.version }} · {{ formatDate(document.updated_at) }}</p></div>
          <StatusPill :status="document.doc_status" />
        </div>
        <form v-if="editingMetadata" class="form-grid metadata-editor" @submit.prevent="saveMetadata">
          <label class="field"><span>文件名</span><input v-model="metadataForm.file_name" data-testid="document-metadata-file-name" type="text" required /></label>
          <label class="field"><span>产品</span><input v-model="metadataForm.product" data-testid="document-metadata-product" type="text" /></label>
          <label class="field"><span>可见性</span><select v-model="metadataForm.visibility"><option value="team_shared">团队共享</option><option value="private">私有</option></select></label>
          <label class="field"><span>数据分类</span><select v-model="metadataForm.data_classification"><option value="public">公开</option><option value="internal">内部</option><option value="private">私有</option><option value="restricted">受限</option></select></label>
          <label class="field metadata-editor-wide"><span>版本标签（逗号或换行）</span><textarea v-model="metadataForm.version_values" rows="3" /></label>
          <div class="row-actions metadata-editor-wide">
            <button class="ghost-button" type="button" :disabled="savingMetadata" @click="editingMetadata = false"><X :size="16" />取消</button>
            <button class="primary-button" data-testid="document-metadata-save" type="submit" :disabled="savingMetadata || !metadataForm.file_name.trim()"><Save :size="16" />{{ savingMetadata ? '保存中' : '保存元数据' }}</button>
          </div>
        </form>
        <dl v-else class="detail-grid">
          <div><dt>可见性</dt><dd>{{ document.visibility }}</dd></div>
          <div><dt>数据分类</dt><dd>{{ document.data_classification }}</dd></div>
          <div><dt>产品</dt><dd>{{ document.product || '—' }}</dd></div>
          <div><dt>版本标签</dt><dd>{{ document.version_values.join(', ') || '—' }}</dd></div>
          <div><dt>所有者</dt><dd>{{ shortId(document.owner_user_id) }}</dd></div>
          <div><dt>当前版本</dt><dd>{{ shortId(document.current_version_id) }}</dd></div>
        </dl>
      </section>

      <section v-if="canManageDocument" class="panel detail-panel" data-testid="document-grants">
        <div class="detail-heading">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <div><h3>文档授权</h3><p>私有文档可额外授权给当前团队成员访问。</p></div>
          <span class="muted-text">{{ grants.length }} 人</span>
        </div>
        <form class="inline-form" @submit.prevent="addGrant">
          <label class="inline-field">
            <span>团队成员</span>
            <select v-model="grantUserId" data-testid="document-grant-user">
              <option value="" disabled>选择成员</option>
              <option v-for="member in grantCandidates" :key="member.user_id" :value="member.user_id">{{ member.display_name }} ({{ member.email }})</option>
            </select>
          </label>
          <button class="primary-button" data-testid="document-grant-add" type="submit" :disabled="savingGrant || !grantUserId"><UserPlus :size="16" />添加授权</button>
        </form>
        <div v-if="grants.length" class="stack-list grant-list">
          <div v-for="grant in grants" :key="grant.id" class="list-row">
            <div><strong>{{ memberName(grant.user_id) }}</strong><span class="cell-subtitle">由 {{ shortId(grant.granted_by) }} 授权 · {{ formatDate(grant.created_at) }}</span></div>
            <button class="ghost-button danger-text" :data-testid="`document-grant-revoke-${grant.id}`" type="button" :disabled="savingGrant" @click="revokeGrant(grant.id)">撤销</button>
          </div>
        </div>
        <div v-else class="empty-state compact"><ShieldCheck :size="20" /><span>暂无额外授权</span></div>
      </section>

      <section class="panel detail-panel">
        <div class="section-heading"><h3>版本时间线</h3><span class="muted-text">{{ versions.length }} 个版本</span></div>
        <div v-if="versions.length" class="table-wrap">
          <table>
            <thead><tr><th>版本</th><th>状态</th><th>大小</th><th>Chunk</th><th>索引 Generation</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="version in versions" :key="version.id">
                <td data-label="版本"><strong>{{ shortId(version.id) }}</strong><span class="cell-subtitle">{{ version.content_fingerprint.slice(0, 18) }}…</span></td>
                <td data-label="状态"><StatusPill :status="version.status" /></td>
                <td data-label="大小">{{ formatBytes(version.file_size_bytes) }}</td>
                <td data-label="Chunk">{{ version.chunk_count }}</td>
                <td data-label="索引 Generation">{{ shortId(version.index_generation) }}</td>
                <td data-label="创建时间">{{ formatDate(version.created_at) }}</td>
                <td data-label="操作"><RouterLink class="ghost-button" :to="`/documents/${document.id}/versions/${version.id}`"><FileClock :size="14" />查看</RouterLink></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state compact"><FileClock :size="22" /><span>暂无版本记录</span></div>
        <div v-if="versionsHasMore" class="load-more" data-testid="document-versions-load-more">
          <button class="secondary-button" type="button" :disabled="loadingMoreVersions" @click="loadMoreVersions">
            {{ loadingMoreVersions ? '加载中' : '加载更多版本' }}
          </button>
        </div>
      </section>

      <div class="split-grid">
        <section class="panel detail-panel">
          <div class="section-heading"><h3>Chunk 概览</h3><RouterLink class="ghost-button" :to="`/chunks?document_id=${document.id}`"><Boxes :size="14" />管理 Chunk</RouterLink></div>
          <div class="metric-grid compact-metrics">
            <article class="metric-card"><span>总数</span><strong>{{ chunks.length }}</strong></article>
            <article class="metric-card"><span>启用</span><strong>{{ chunks.filter((item) => item.status === 'enabled').length }}</strong></article>
            <article class="metric-card"><span>禁用</span><strong>{{ chunks.filter((item) => item.status === 'disabled').length }}</strong></article>
          </div>
          <div v-if="chunksHasMore" class="load-more" data-testid="document-chunks-load-more">
            <button class="secondary-button" type="button" :disabled="loadingMoreChunks" @click="loadMoreChunks">
              {{ loadingMoreChunks ? '加载中' : '加载更多 Chunk' }}
            </button>
          </div>
        </section>
        <section class="panel detail-panel">
          <div class="section-heading"><h3>最近任务</h3><RouterLink class="ghost-button" to="/tasks"><RefreshCw :size="14" />任务中心</RouterLink></div>
          <div v-if="tasks.length" class="stack-list">
            <div v-for="task in tasks" :key="task.id" class="list-row"><div><strong>{{ task.current_stage || task.status }}</strong><span class="cell-subtitle">{{ task.stage_progress_pct }}% · {{ formatDate(task.created_at) }}</span></div><StatusPill :status="task.status" /></div>
          </div>
          <div v-else class="empty-state compact"><RefreshCw :size="20" /><span>暂无入库任务</span></div>
          <div v-if="tasksHasMore" class="load-more" data-testid="document-tasks-load-more">
            <button class="secondary-button" type="button" :disabled="loadingMoreTasks" @click="loadMoreTasks">
              {{ loadingMoreTasks ? '加载中' : '加载更多任务' }}
            </button>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.metadata-editor-wide {
  grid-column: 1 / -1;
}

.grant-list {
  margin-top: 16px;
}

@media (max-width: 720px) {
  .metadata-editor-wide {
    grid-column: auto;
  }
}
</style>
