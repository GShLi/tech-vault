<script setup lang="ts">
import {
  ApiRequestError,
  api,
  loadAllPages,
  normalizeApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  Message,
  Modal,
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
  Textarea as ATextarea,
} from '@arco-design/web-vue'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Boxes,
  Download,
  FileClock,
  FileText,
  Pencil,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  UserPlus,
  Wrench,
  X,
} from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type {
  ChunkView,
  DocumentDetailView,
  DocumentGrantView,
  DocumentVersion,
  IngestionRun,
  TeamMemberView,
} from '@/types/api'
import {
  downloadBlob,
  formatBytes,
  formatDate,
  parseLines,
  shortId,
  statusLabel,
} from '@/utils/format'

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
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function loadShareData(): Promise<void> {
  if (!team.selectedTeamId || !document.value || !canManageDocument.value)
    return
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
  if (!team.selectedTeamId || !document.value || !canManageDocument.value)
    return
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
    error.value = normalizeApiError(caught)
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
  )
    return
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
  } finally {
    loadingMoreTasks.value = false
  }
}

async function download(): Promise<void> {
  if (!team.selectedTeamId || !document.value) return
  downloading.value = true
  error.value = null
  try {
    const blob = await api.downloadDocument(
      team.selectedTeamId,
      document.value.id,
    )
    downloadBlob(blob, document.value.file_name)
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    downloading.value = false
  }
}

async function rebuild(): Promise<void> {
  if (!team.selectedTeamId || !document.value) return
  rebuilding.value = true
  error.value = null
  try {
    const result = await api.rebuildDocument(
      team.selectedTeamId,
      document.value.id,
    )
    Message.success(`重建任务已创建：${shortId(result.ingestion_run_id)}`)
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
  if (
    !(await confirmAction(
      '删除文档',
      '删除后立即停止召回，并在保留期内允许恢复。确定继续吗？',
    ))
  )
    return
  deleting.value = true
  error.value = null
  try {
    await api.deleteDocument(team.selectedTeamId, document.value.id)
    Message.success('文档已删除，可在保留期内恢复')
    await router.push(`/knowledge-bases/${document.value.knowledge_base_id}`)
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
  } finally {
    restoring.value = false
  }
}

onMounted(load)
watch(() => route.params.documentId, load)
</script>

<template>
  <div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div v-if="loading && !document" class="panel loading-state">
      <a-spin />
      <span>正在加载文档</span>
    </div>
    <template v-else-if="document">
      <section
        v-if="
          document.parse_metadata?.parser_name || document.failure_details?.code
        "
        class="panel"
        data-testid="parsing-diagnostics"
      >
        <h3>解析与分块质量</h3>
        <p v-if="document.parse_metadata?.parser_name">
          解析器：{{ document.parse_metadata.parser_name }} · 版本
          {{ document.parse_metadata.parser_version }}
          <span v-if="document.parse_metadata.pdf_kind">
            · PDF 类型 {{ document.parse_metadata.pdf_kind }}
          </span>
        </p>
        <p v-if="document.chunking_metadata?.child_count">
          父块 {{ document.chunking_metadata.parent_count }} · 子块
          {{ document.chunking_metadata.child_count }} · 最大
          {{ document.chunking_metadata.max_tokens }} tokens · 非安全切分
          {{ document.chunking_metadata.unsafe_split_count }}
        </p>
        <p v-if="document.failure_details?.code" role="alert">
          处理失败：{{ document.failure_details.code }}
        </p>
      </section>
      <div class="page-header">
        <div class="heading-with-back">
          <RouterLink
            :to="`/knowledge-bases/${document.knowledge_base_id}`"
            custom
            v-slot="{ href, navigate }"
          >
            <a-button
              type="text"
              :href="href"
              @click="navigate"
              title="返回知识库"
            >
              <FileText :size="18" />
            </a-button>
          </RouterLink>
          <div>
            <h2>{{ document.file_name }}</h2>
            <p>
              {{ document.source_type }} · 知识库
              {{ shortId(document.knowledge_base_id) }}
            </p>
          </div>
        </div>
        <div class="row-actions">
          <a-button
            v-if="document.doc_status !== 'deleted'"
            :disabled="downloading"
            @click="download"
            type="secondary"
            html-type="button"
          >
            <Download :size="16" />
            {{ downloading ? '下载中' : '下载原文' }}
          </a-button>
          <a-button
            v-if="canManageDocument && document.doc_status !== 'deleted'"
            @click="beginMetadataEdit"
            type="secondary"
            html-type="button"
          >
            <Pencil :size="16" />
            编辑元数据
          </a-button>
          <a-button
            v-if="canManageDocument && document.doc_status !== 'deleted'"
            :disabled="rebuilding"
            @click="rebuild"
            type="primary"
            html-type="button"
          >
            <Wrench :size="16" />
            {{ rebuilding ? '提交中' : '重建索引' }}
          </a-button>
          <a-button
            v-if="canManageDocument && document.doc_status === 'deleted'"
            :disabled="restoring"
            @click="restore"
            type="secondary"
            html-type="button"
          >
            <RotateCcw :size="16" />
            {{ restoring ? '恢复中' : '恢复文档' }}
          </a-button>
          <a-button
            v-else-if="canManageDocument"
            :disabled="deleting"
            @click="remove"
            type="secondary"
            html-type="button"
            status="danger"
          >
            <Trash2 :size="16" />
            {{ deleting ? '删除中' : '删除文档' }}
          </a-button>
        </div>
      </div>

      <a-alert
        v-if="document.doc_status === 'deleted'"
        data-testid="document-deleted-notice"
        type="info"
        class="page-alert"
      >
        <strong>文档已停止召回</strong>
        <span>可在保留期内恢复；超过保留期后将清理原始文件、索引和缓存。</span>
      </a-alert>

      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><FileText :size="20" /></div>
          <div>
            <h3>元数据</h3>
            <p>
              文档 v{{ document.version }} ·
              {{ formatDate(document.updated_at) }}
            </p>
          </div>
          <a-tag :color="statusColor(document.doc_status)">
            {{ statusLabel(document.doc_status) }}
          </a-tag>
        </div>
        <a-form
          v-if="editingMetadata"
          class="form-grid metadata-editor"
          :model="{ metadataForm }"
          layout="vertical"
          @submit-success="saveMetadata"
        >
          <a-form-item
            field="metadataForm.file_name"
            :rules="[{ required: true, message: '请填写文件名' }]"
            :validate-trigger="['change', 'blur']"
          >
            <template #label>文件名</template>
            <a-input
              v-model="metadataForm.file_name"
              data-testid="document-metadata-file-name"
              type="text"
              :input-attrs="{ required: true }"
            ></a-input>
          </a-form-item>
          <a-form-item field="metadataForm.product">
            <template #label>产品</template>
            <a-input
              v-model="metadataForm.product"
              data-testid="document-metadata-product"
              type="text"
            ></a-input>
          </a-form-item>
          <a-form-item field="metadataForm.visibility">
            <template #label>可见性</template>
            <a-select v-model="metadataForm.visibility">
              <a-option value="team_shared">团队共享</a-option>
              <a-option value="private">私有</a-option>
            </a-select>
          </a-form-item>
          <a-form-item field="metadataForm.data_classification">
            <template #label>数据分类</template>
            <a-select v-model="metadataForm.data_classification">
              <a-option value="public">公开</a-option>
              <a-option value="internal">内部</a-option>
              <a-option value="private">私有</a-option>
              <a-option value="restricted">受限</a-option>
            </a-select>
          </a-form-item>
          <a-form-item
            class="metadata-editor-wide"
            field="metadataForm.version_values"
          >
            <template #label>版本标签（逗号或换行）</template>
            <a-textarea
              v-model="metadataForm.version_values"
              :textarea-attrs="{ rows: '3' }"
            ></a-textarea>
          </a-form-item>
          <div class="row-actions metadata-editor-wide">
            <a-button
              :disabled="savingMetadata"
              @click="editingMetadata = false"
              type="text"
              html-type="button"
            >
              <X :size="16" />
              取消
            </a-button>
            <a-button
              data-testid="document-metadata-save"
              :disabled="savingMetadata || !metadataForm.file_name.trim()"
              type="primary"
              html-type="submit"
            >
              <Save :size="16" />
              {{ savingMetadata ? '保存中' : '保存元数据' }}
            </a-button>
          </div>
        </a-form>
        <a-descriptions
          v-else
          :column="{ xs: 1, sm: 2, lg: 3 }"
          bordered
          class="detail-descriptions"
        >
          <a-descriptions-item label="可见性">
            {{ document.visibility }}
          </a-descriptions-item>
          <a-descriptions-item label="数据分类">
            {{ document.data_classification }}
          </a-descriptions-item>
          <a-descriptions-item label="产品">
            {{ document.product || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="版本标签">
            {{ document.version_values.join(', ') || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="所有者">
            {{ shortId(document.owner_user_id) }}
          </a-descriptions-item>
          <a-descriptions-item label="当前版本">
            {{ shortId(document.current_version_id) }}
          </a-descriptions-item>
        </a-descriptions>
      </a-card>

      <a-card
        v-if="canManageDocument"
        data-testid="document-grants"
        class="page-card"
      >
        <div class="detail-heading">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <div>
            <h3>文档授权</h3>
            <p>私有文档可额外授权给当前团队成员访问。</p>
          </div>
          <span class="muted-text">{{ grants.length }} 人</span>
        </div>
        <a-form
          class="inline-form"
          :model="{ grantUserId }"
          layout="vertical"
          @submit-success="addGrant"
        >
          <a-form-item class="inline-field" field="grantUserId">
            <template #label>团队成员</template>
            <a-select v-model="grantUserId" data-testid="document-grant-user">
              <a-option value="" disabled>选择成员</a-option>
              <a-option
                v-for="member in grantCandidates"
                :key="member.user_id"
                :value="member.user_id"
              >
                {{ member.display_name }} ({{ member.email }})
              </a-option>
            </a-select>
          </a-form-item>
          <a-button
            data-testid="document-grant-add"
            :disabled="savingGrant || !grantUserId"
            type="primary"
            html-type="submit"
          >
            <UserPlus :size="16" />
            添加授权
          </a-button>
        </a-form>
        <div v-if="grants.length" class="stack-list grant-list">
          <div v-for="grant in grants" :key="grant.id" class="list-row">
            <div>
              <strong>{{ memberName(grant.user_id) }}</strong>
              <span class="cell-subtitle">
                由 {{ shortId(grant.granted_by) }} 授权 ·
                {{ formatDate(grant.created_at) }}
              </span>
            </div>
            <a-button
              :data-testid="`document-grant-revoke-${grant.id}`"
              :disabled="savingGrant"
              @click="revokeGrant(grant.id)"
              type="text"
              html-type="button"
              status="danger"
            >
              撤销
            </a-button>
          </div>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><ShieldCheck :size="20" /></template>
          <span>暂无额外授权</span>
        </a-empty>
      </a-card>

      <a-card class="page-card">
        <div class="section-heading">
          <h3>版本时间线</h3>
          <span class="muted-text">{{ versions.length }} 个版本</span>
        </div>
        <div v-if="versions.length" class="table-wrap">
          <a-table
            :data="versions"
            :pagination="false"
            row-key="id"
            :bordered="false"
            :scroll="{ x: 960 }"
          >
            <template #columns>
              <a-table-column title="版本" :width="90">
                <template #cell="{ record: version }">
                  <strong>{{ shortId(version.id) }}</strong>
                  <span class="cell-subtitle">
                    {{ version.content_fingerprint.slice(0, 18) }}…
                  </span>
                </template>
              </a-table-column>
              <a-table-column title="状态" :width="100">
                <template #cell="{ record: version }">
                  <a-tag :color="statusColor(version.status)">
                    {{ statusLabel(version.status) }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="大小">
                <template #cell="{ record: version }">
                  {{ formatBytes(version.file_size_bytes) }}
                </template>
              </a-table-column>
              <a-table-column title="Chunk" :width="180">
                <template #cell="{ record: version }">
                  {{ version.chunk_count }}
                </template>
              </a-table-column>
              <a-table-column title="索引 Generation">
                <template #cell="{ record: version }">
                  {{ shortId(version.index_generation) }}
                </template>
              </a-table-column>
              <a-table-column title="创建时间" :width="180">
                <template #cell="{ record: version }">
                  {{ formatDate(version.created_at) }}
                </template>
              </a-table-column>
              <a-table-column title="操作" :width="180">
                <template #cell="{ record: version }">
                  <RouterLink
                    :to="`/documents/${document.id}/versions/${version.id}`"
                    custom
                    v-slot="{ href, navigate }"
                  >
                    <a-button type="text" :href="href" @click="navigate">
                      <FileClock :size="14" />
                      查看
                    </a-button>
                  </RouterLink>
                </template>
              </a-table-column>
            </template>
          </a-table>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><FileClock :size="22" /></template>
          <span>暂无版本记录</span>
        </a-empty>
        <div
          v-if="versionsHasMore"
          class="load-more"
          data-testid="document-versions-load-more"
        >
          <a-button
            :disabled="loadingMoreVersions"
            @click="loadMoreVersions"
            type="secondary"
            html-type="button"
          >
            {{ loadingMoreVersions ? '加载中' : '加载更多版本' }}
          </a-button>
        </div>
      </a-card>

      <div class="split-grid">
        <a-card class="page-card">
          <div class="section-heading">
            <h3>Chunk 概览</h3>
            <RouterLink
              :to="`/chunks?document_id=${document.id}`"
              custom
              v-slot="{ href, navigate }"
            >
              <a-button type="text" :href="href" @click="navigate">
                <Boxes :size="14" />
                管理 Chunk
              </a-button>
            </RouterLink>
          </div>
          <div class="metric-grid compact-metrics">
            <article class="metric-card">
              <span>总数</span>
              <strong>{{ chunks.length }}</strong>
            </article>
            <article class="metric-card">
              <span>启用</span>
              <strong>
                {{ chunks.filter((item) => item.status === 'enabled').length }}
              </strong>
            </article>
            <article class="metric-card">
              <span>禁用</span>
              <strong>
                {{ chunks.filter((item) => item.status === 'disabled').length }}
              </strong>
            </article>
          </div>
          <div
            v-if="chunksHasMore"
            class="load-more"
            data-testid="document-chunks-load-more"
          >
            <a-button
              :disabled="loadingMoreChunks"
              @click="loadMoreChunks"
              type="secondary"
              html-type="button"
            >
              {{ loadingMoreChunks ? '加载中' : '加载更多 Chunk' }}
            </a-button>
          </div>
        </a-card>
        <a-card class="page-card">
          <div class="section-heading">
            <h3>最近任务</h3>
            <RouterLink to="/tasks" custom v-slot="{ href, navigate }">
              <a-button type="text" :href="href" @click="navigate">
                <RefreshCw :size="14" />
                任务中心
              </a-button>
            </RouterLink>
          </div>
          <div v-if="tasks.length" class="stack-list">
            <div v-for="task in tasks" :key="task.id" class="list-row">
              <div>
                <strong>{{ statusLabel(task.current_stage || task.status) }}</strong>
                <span class="cell-subtitle">
                  {{ task.stage_progress_pct }}% ·
                  {{ formatDate(task.created_at) }}
                </span>
              </div>
              <a-tag :color="statusColor(task.status)">
                {{ statusLabel(task.status) }}
              </a-tag>
            </div>
          </div>
          <a-empty v-else class="page-empty">
            <template #image><RefreshCw :size="20" /></template>
            <span>暂无入库任务</span>
          </a-empty>
          <div
            v-if="tasksHasMore"
            class="load-more"
            data-testid="document-tasks-load-more"
          >
            <a-button
              :disabled="loadingMoreTasks"
              @click="loadMoreTasks"
              type="secondary"
              html-type="button"
            >
              {{ loadingMoreTasks ? '加载中' : '加载更多任务' }}
            </a-button>
          </div>
        </a-card>
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
