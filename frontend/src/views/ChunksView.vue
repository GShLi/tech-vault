<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Boxes, RefreshCw } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError, loadAllPages } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { ChunkView, DocumentDetailView, DocumentView, KnowledgeBase } from '@/types/api'
import { shortId } from '@/utils/format'

const route = useRoute()
const auth = useAuthStore()
const team = useTeamStore()
const kbs = ref<KnowledgeBase[]>([])
const documents = ref<DocumentView[]>([])
const chunks = ref<ChunkView[]>([])
const selectedDocument = ref<DocumentDetailView | null>(null)
const selectedKbId = ref('')
const selectedDocumentId = ref('')
const selectedChunkIds = ref<string[]>([])
const loading = ref(false)
const loadingMoreChunks = ref(false)
const chunksNextCursor = ref<string | null>(null)
const chunksHasMore = ref(false)
const error = ref<ApiRequestError | null>(null)
const canManageSelectedDocument = computed(
  () =>
    Boolean(selectedDocument.value) &&
    (team.canManage ||
      auth.me?.user.is_super_admin === true ||
      selectedDocument.value?.owner_user_id === auth.me?.user.id),
)

async function loadKbs(): Promise<void> {
  if (!team.selectedTeamId) return
  kbs.value = await loadAllPages((cursor) =>
    api.listKbs(team.selectedTeamId!, cursor, 100),
  )
  const queryDocumentId = String(route.query.document_id ?? '')
  if (queryDocumentId) {
    const documentView = await api.getDoc(team.selectedTeamId, queryDocumentId)
    selectedDocumentId.value = documentView.id
    selectedKbId.value = documentView.knowledge_base_id
  } else if (!selectedKbId.value && kbs.value.length) {
    selectedKbId.value = kbs.value[0].id
  }
}

async function loadDocuments(): Promise<void> {
  if (!team.selectedTeamId || !selectedKbId.value) {
    documents.value = []
    return
  }
  documents.value = await loadAllPages((cursor) =>
    api.listDocs(team.selectedTeamId!, selectedKbId.value, cursor, 100),
  )
  if (!documents.value.some((item) => item.id === selectedDocumentId.value)) {
    selectedDocumentId.value = documents.value[0]?.id ?? ''
  }
}

async function loadSelectedDocument(): Promise<void> {
  if (!team.selectedTeamId || !selectedDocumentId.value) {
    selectedDocument.value = null
    return
  }
  selectedDocument.value = await api.getDoc(
    team.selectedTeamId,
    selectedDocumentId.value,
  )
}

async function loadSelectionData(): Promise<void> {
  await loadSelectedDocument()
  await loadChunks()
}

async function loadChunks(): Promise<void> {
  if (!team.selectedTeamId || !selectedDocumentId.value) {
    chunks.value = []
    return
  }
  const page = await api.listChunks(team.selectedTeamId, selectedDocumentId.value)
  chunks.value = page.data
  chunksNextCursor.value = page.meta.next_cursor
  chunksHasMore.value = page.meta.has_more
  selectedChunkIds.value = []
}

async function loadMoreChunks(): Promise<void> {
  if (!team.selectedTeamId || !selectedDocumentId.value || !chunksNextCursor.value) return
  loadingMoreChunks.value = true
  try {
    const page = await api.listChunks(
      team.selectedTeamId,
      selectedDocumentId.value,
      chunksNextCursor.value,
    )
    const existingIds = new Set(chunks.value.map((chunk) => chunk.id))
    chunks.value = [...chunks.value, ...page.data.filter((chunk) => !existingIds.has(chunk.id))]
    chunksNextCursor.value = page.meta.next_cursor
    chunksHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreChunks.value = false
  }
}

async function load(): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    await loadKbs()
    await loadDocuments()
    await loadSelectionData()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function bulk(action: 'enable' | 'disable'): Promise<void> {
  if (!team.selectedTeamId || !selectedChunkIds.value.length) return
  try {
    if (action === 'enable') await api.enableChunks(team.selectedTeamId, selectedChunkIds.value)
    else await api.disableChunks(team.selectedTeamId, selectedChunkIds.value)
    Message.success(action === 'enable' ? 'Chunk 已启用' : 'Chunk 已禁用')
    await loadChunks()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

function toggleSelection(chunkId: string): void {
  selectedChunkIds.value = selectedChunkIds.value.includes(chunkId)
    ? selectedChunkIds.value.filter((item) => item !== chunkId)
    : [...selectedChunkIds.value, chunkId]
}

onMounted(load)
watch(() => team.selectedTeamId, load)
async function onKbChange(): Promise<void> {
  selectedDocumentId.value = ''
  selectedDocument.value = null
  try {
    await loadDocuments()
    await loadSelectionData()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function onDocumentChange(): Promise<void> {
  try {
    await loadSelectionData()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div><h2>Chunk 管理</h2><p>检查分块质量，编辑、启用、禁用或重建文档 Chunk。</p></div>
      <button class="secondary-button" type="button" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button>
    </div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>

    <section class="panel toolbar-panel">
      <label class="inline-field"><span>知识库</span><select v-model="selectedKbId" @change="onKbChange"><option value="" disabled>选择知识库</option><option v-for="kb in kbs" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></label>
      <label class="inline-field"><span>文档</span><select v-model="selectedDocumentId" @change="onDocumentChange"><option value="" disabled>选择文档</option><option v-for="document in documents" :key="document.id" :value="document.id">{{ document.file_name }}</option></select></label>
      <div class="row-actions" v-if="canManageSelectedDocument && selectedChunkIds.length">
        <span class="muted-text">已选 {{ selectedChunkIds.length }}</span>
        <button class="secondary-button" type="button" @click="bulk('enable')">批量启用</button>
        <button class="secondary-button danger-text" type="button" @click="bulk('disable')">批量禁用</button>
      </div>
    </section>

    <div v-if="loading && !chunks.length" class="panel loading-state"><a-spin /><span>正在加载 Chunk</span></div>
    <div v-else-if="!selectedDocumentId" class="panel empty-state"><Boxes :size="28" /><h3>请选择文档</h3><p>选择知识库和文档后查看分块。</p></div>
    <div v-else-if="!chunks.length" class="panel empty-state"><Boxes :size="28" /><h3>暂无 Chunk</h3><p>文档可能仍在入库，或尚未成功解析。</p></div>
    <div v-else class="panel">
      <div class="table-wrap">
        <table>
          <thead><tr><th v-if="canManageSelectedDocument" class="check-column"></th><th>Chunk</th><th>内容</th><th>结构路径</th><th>状态</th><th>版本</th><th class="actions-column">操作</th></tr></thead>
          <tbody>
            <tr v-for="chunk in chunks" :key="chunk.id">
              <td v-if="canManageSelectedDocument" data-label="选择"><input type="checkbox" :checked="selectedChunkIds.includes(chunk.id)" @change="toggleSelection(chunk.id)" /></td>
              <td data-label="Chunk"><strong>{{ shortId(chunk.id) }}</strong></td>
              <td data-label="内容"><span class="truncate-cell wide">{{ chunk.content }}</span></td>
              <td data-label="结构路径">{{ chunk.heading_path.join(' / ') || '—' }}</td>
              <td data-label="状态"><StatusPill :status="chunk.status" /></td>
              <td data-label="版本">v{{ chunk.version }}</td>
              <td data-label="操作"><RouterLink class="ghost-button" :to="`/chunks/${chunk.id}`">{{ canManageSelectedDocument ? '编辑' : '查看' }}</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="chunksHasMore" class="load-more">
        <button class="secondary-button" type="button" :disabled="loadingMoreChunks" @click="loadMoreChunks">
          {{ loadingMoreChunks ? '加载中' : '加载更多' }}
        </button>
      </div>
    </div>
  </div>
</template>
