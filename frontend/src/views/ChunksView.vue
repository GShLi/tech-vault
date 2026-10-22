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
  Checkbox as ACheckbox,
  Empty as AEmpty,
  FormItem as AFormItem,
  Message,
  Option as AOption,
  Select as ASelect,
  Spin as ASpin,
  Table as ATable,
  TableColumn as ATableColumn,
  Tag as ATag,
} from '@arco-design/web-vue'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Boxes, RefreshCw } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type {
  ChunkView,
  DocumentDetailView,
  DocumentView,
  KnowledgeBase,
} from '@/types/api'
import { shortId, statusLabel } from '@/utils/format'

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
  const page = await api.listChunks(
    team.selectedTeamId,
    selectedDocumentId.value,
  )
  chunks.value = page.data
  chunksNextCursor.value = page.meta.next_cursor
  chunksHasMore.value = page.meta.has_more
  selectedChunkIds.value = []
}

async function loadMoreChunks(): Promise<void> {
  if (
    !team.selectedTeamId ||
    !selectedDocumentId.value ||
    !chunksNextCursor.value
  )
    return
  loadingMoreChunks.value = true
  try {
    const page = await api.listChunks(
      team.selectedTeamId,
      selectedDocumentId.value,
      chunksNextCursor.value,
    )
    const existingIds = new Set(chunks.value.map((chunk) => chunk.id))
    chunks.value = [
      ...chunks.value,
      ...page.data.filter((chunk) => !existingIds.has(chunk.id)),
    ]
    chunksNextCursor.value = page.meta.next_cursor
    chunksHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function bulk(action: 'enable' | 'disable'): Promise<void> {
  if (!team.selectedTeamId || !selectedChunkIds.value.length) return
  try {
    if (action === 'enable')
      await api.enableChunks(team.selectedTeamId, selectedChunkIds.value)
    else await api.disableChunks(team.selectedTeamId, selectedChunkIds.value)
    Message.success(action === 'enable' ? 'Chunk 已启用' : 'Chunk 已禁用')
    await loadChunks()
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
  }
}

async function onDocumentChange(): Promise<void> {
  try {
    await loadSelectionData()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>Chunk 管理</h2>
        <p>检查分块质量，编辑、启用、禁用或重建文档 Chunk。</p>
      </div>
      <a-button
        :disabled="loading"
        @click="load"
        type="secondary"
        html-type="button"
      >
        <RefreshCw :size="16" />
        刷新
      </a-button>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>

    <section class="panel toolbar-panel">
      <a-form-item class="inline-field">
        <template #label>知识库</template>
        <a-select v-model="selectedKbId" @change="onKbChange">
          <a-option value="" disabled>选择知识库</a-option>
          <a-option v-for="kb in kbs" :key="kb.id" :value="kb.id">
            {{ kb.name }}
          </a-option>
        </a-select>
      </a-form-item>
      <a-form-item class="inline-field">
        <template #label>文档</template>
        <a-select v-model="selectedDocumentId" @change="onDocumentChange">
          <a-option value="" disabled>选择文档</a-option>
          <a-option
            v-for="document in documents"
            :key="document.id"
            :value="document.id"
          >
            {{ document.file_name }}
          </a-option>
        </a-select>
      </a-form-item>
      <div
        class="row-actions"
        v-if="canManageSelectedDocument && selectedChunkIds.length"
      >
        <span class="muted-text">已选 {{ selectedChunkIds.length }}</span>
        <a-button @click="bulk('enable')" type="secondary" html-type="button">
          批量启用
        </a-button>
        <a-button
          @click="bulk('disable')"
          type="secondary"
          html-type="button"
          status="danger"
        >
          批量禁用
        </a-button>
      </div>
    </section>

    <div v-if="loading && !chunks.length" class="panel loading-state">
      <a-spin />
      <span>正在加载 Chunk</span>
    </div>
    <a-empty v-else-if="!selectedDocumentId" class="page-empty">
      <template #image><Boxes :size="28" /></template>
      <h3>请选择文档</h3>
      <p>选择知识库和文档后查看分块。</p>
    </a-empty>
    <a-empty v-else-if="!chunks.length" class="page-empty">
      <template #image><Boxes :size="28" /></template>
      <h3>暂无 Chunk</h3>
      <p>文档可能仍在入库，或尚未成功解析。</p>
    </a-empty>
    <div v-else class="panel">
      <div class="table-wrap">
        <a-table
          :data="chunks"
          :pagination="false"
          row-key="id"
          :bordered="false"
          :scroll="{ x: 960 }"
        >
          <template #columns>
            <a-table-column v-if="canManageSelectedDocument">
              <template #cell="{ record: chunk }">
                <a-checkbox
                  @change="toggleSelection(chunk.id)"
                  :model-value="selectedChunkIds.includes(chunk.id)"
                  aria-label="选择"
                ></a-checkbox>
              </template>
            </a-table-column>
            <a-table-column title="Chunk" :width="180">
              <template #cell="{ record: chunk }">
                <strong>{{ shortId(chunk.id) }}</strong>
              </template>
            </a-table-column>
            <a-table-column title="内容">
              <template #cell="{ record: chunk }">
                <span class="truncate-cell wide">{{ chunk.content }}</span>
              </template>
            </a-table-column>
            <a-table-column title="结构路径">
              <template #cell="{ record: chunk }">
                {{ chunk.heading_path.join(' / ') || '—' }}
              </template>
            </a-table-column>
            <a-table-column title="状态" :width="100">
              <template #cell="{ record: chunk }">
                <a-tag :color="statusColor(chunk.status)">
                  {{ statusLabel(chunk.status) }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="版本" :width="90">
              <template #cell="{ record: chunk }">
                v{{ chunk.version }}
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="180">
              <template #cell="{ record: chunk }">
                <RouterLink
                  :to="`/chunks/${chunk.id}`"
                  custom
                  v-slot="{ href, navigate }"
                >
                  <a-button type="text" :href="href" @click="navigate">
                    {{ canManageSelectedDocument ? '编辑' : '查看' }}
                  </a-button>
                </RouterLink>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </div>
      <div v-if="chunksHasMore" class="load-more">
        <a-button
          :disabled="loadingMoreChunks"
          @click="loadMoreChunks"
          type="secondary"
          html-type="button"
        >
          {{ loadingMoreChunks ? '加载中' : '加载更多' }}
        </a-button>
      </div>
    </div>
  </div>
</template>
