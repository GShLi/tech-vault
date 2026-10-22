<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  Spin as ASpin,
  Tag as ATag,
} from '@arco-design/web-vue'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Boxes, FileClock, Fingerprint } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type {
  ChunkView,
  DocumentDetailView,
  DocumentVersion,
} from '@/types/api'
import { formatBytes, formatDate, shortId, statusLabel } from '@/utils/format'

const route = useRoute()
const team = useTeamStore()
const document = ref<DocumentDetailView | null>(null)
const version = ref<DocumentVersion | null>(null)
const chunks = ref<ChunkView[]>([])
const loading = ref(false)
const loadingMoreChunks = ref(false)
const chunksNextCursor = ref<string | null>(null)
const chunksHasMore = ref(false)
const error = ref<ApiRequestError | null>(null)

const documentId = computed(() => String(route.params.documentId ?? ''))
const versionId = computed(() => String(route.params.versionId ?? ''))

async function load(): Promise<void> {
  if (!team.selectedTeamId || !documentId.value || !versionId.value) return
  loading.value = true
  error.value = null
  try {
    const [documentView, versionView, chunkPage] = await Promise.all([
      api.getDoc(team.selectedTeamId, documentId.value),
      api.getDocumentVersion(
        team.selectedTeamId,
        documentId.value,
        versionId.value,
      ),
      api.listDocumentChunks(team.selectedTeamId, documentId.value),
    ])
    document.value = documentView
    version.value = versionView
    chunks.value = chunkPage.data
    chunksNextCursor.value = chunkPage.meta.next_cursor
    chunksHasMore.value = chunkPage.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

async function loadMoreChunks(): Promise<void> {
  if (!team.selectedTeamId || !documentId.value || !chunksNextCursor.value)
    return
  loadingMoreChunks.value = true
  try {
    const page = await api.listDocumentChunks(
      team.selectedTeamId,
      documentId.value,
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

onMounted(load)
watch(() => [route.params.documentId, route.params.versionId], load)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink
          :to="`/documents/${documentId}`"
          custom
          v-slot="{ href, navigate }"
        >
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回文档详情"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>文档版本</h2>
          <p>
            {{ document?.file_name || '正在读取版本信息' }} ·
            {{ shortId(versionId) }}
          </p>
        </div>
      </div>
    </div>

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div v-if="loading && !version" class="panel loading-state">
      <a-spin />
      <span>正在加载文档版本</span>
    </div>
    <template v-else-if="version">
      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><FileClock :size="20" /></div>
          <div>
            <h3>{{ document?.file_name || shortId(documentId) }}</h3>
            <p>{{ formatDate(version.created_at) }}</p>
          </div>
          <a-tag :color="statusColor(version.status)">
            {{ statusLabel(version.status) }}
          </a-tag>
        </div>
        <a-descriptions
          :column="{ xs: 1, sm: 2, lg: 3 }"
          bordered
          class="detail-descriptions"
        >
          <a-descriptions-item label="版本 ID">
            {{ shortId(version.id) }}
          </a-descriptions-item>
          <a-descriptions-item label="文件大小">
            {{ formatBytes(version.file_size_bytes) }}
          </a-descriptions-item>
          <a-descriptions-item label="Chunk 数量">
            {{ version.chunk_count }}
          </a-descriptions-item>
          <a-descriptions-item label="索引 Generation">
            {{ shortId(version.index_generation) }}
          </a-descriptions-item>
        </a-descriptions>
        <div class="fingerprint">
          <Fingerprint :size="16" />
          <code>{{ version.content_fingerprint }}</code>
        </div>
      </a-card>

      <a-card class="page-card">
        <div class="section-heading">
          <h3>Chunk 预览</h3>
          <span class="muted-text">{{ chunks.length }} 条</span>
        </div>
        <div v-if="chunks.length" class="stack-list">
          <article v-for="chunk in chunks" :key="chunk.id" class="text-card">
            <div class="list-card-heading">
              <div>
                <strong>
                  {{ chunk.heading_path.join(' / ') || shortId(chunk.id) }}
                </strong>
                <span class="cell-subtitle">v{{ chunk.version }}</span>
              </div>
              <a-tag :color="statusColor(chunk.status)">
                {{ statusLabel(chunk.status) }}
              </a-tag>
            </div>
            <p class="pre-wrap">{{ chunk.content }}</p>
            <RouterLink
              :to="`/chunks/${chunk.id}`"
              custom
              v-slot="{ href, navigate }"
            >
              <a-button type="text" :href="href" @click="navigate">
                打开 Chunk
              </a-button>
            </RouterLink>
          </article>
        </div>
        <a-empty v-else class="page-empty">
          <template #image><Boxes :size="22" /></template>
          <span>该版本没有可展示的 Chunk</span>
        </a-empty>
        <div
          v-if="chunksHasMore"
          class="load-more"
          data-testid="version-chunks-load-more"
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
    </template>
  </div>
</template>
