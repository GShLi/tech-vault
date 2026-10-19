<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Boxes, FileClock, Fingerprint } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { ChunkView, DocumentDetailView, DocumentVersion } from '@/types/api'
import { formatBytes, formatDate, shortId } from '@/utils/format'

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
      api.getDocumentVersion(team.selectedTeamId, documentId.value, versionId.value),
      api.listDocumentChunks(team.selectedTeamId, documentId.value),
    ])
    document.value = documentView
    version.value = versionView
    chunks.value = chunkPage.data
    chunksNextCursor.value = chunkPage.meta.next_cursor
    chunksHasMore.value = chunkPage.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadMoreChunks(): Promise<void> {
  if (!team.selectedTeamId || !documentId.value || !chunksNextCursor.value) return
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
    error.value = caught instanceof ApiRequestError ? caught : null
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
        <RouterLink class="icon-button" :to="`/documents/${documentId}`" title="返回文档详情"><ArrowLeft :size="18" /></RouterLink>
        <div><h2>文档版本</h2><p>{{ document?.file_name || '正在读取版本信息' }} · {{ shortId(versionId) }}</p></div>
      </div>
    </div>

    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !version" class="panel loading-state"><a-spin /><span>正在加载文档版本</span></div>
    <template v-else-if="version">
      <section class="panel detail-panel">
        <div class="detail-heading">
          <div class="detail-icon"><FileClock :size="20" /></div>
          <div><h3>{{ document?.file_name || shortId(documentId) }}</h3><p>{{ formatDate(version.created_at) }}</p></div>
          <StatusPill :status="version.status" />
        </div>
        <dl class="detail-grid">
          <div><dt>版本 ID</dt><dd>{{ shortId(version.id) }}</dd></div>
          <div><dt>文件大小</dt><dd>{{ formatBytes(version.file_size_bytes) }}</dd></div>
          <div><dt>Chunk 数量</dt><dd>{{ version.chunk_count }}</dd></div>
          <div><dt>索引 Generation</dt><dd>{{ shortId(version.index_generation) }}</dd></div>
        </dl>
        <div class="fingerprint"><Fingerprint :size="16" /><code>{{ version.content_fingerprint }}</code></div>
      </section>

      <section class="panel detail-panel">
        <div class="section-heading"><h3>Chunk 预览</h3><span class="muted-text">{{ chunks.length }} 条</span></div>
        <div v-if="chunks.length" class="stack-list">
          <article v-for="chunk in chunks" :key="chunk.id" class="text-card">
            <div class="list-card-heading">
              <div><strong>{{ chunk.heading_path.join(' / ') || shortId(chunk.id) }}</strong><span class="cell-subtitle">v{{ chunk.version }}</span></div>
              <StatusPill :status="chunk.status" />
            </div>
            <p class="pre-wrap">{{ chunk.content }}</p>
            <RouterLink class="ghost-button" :to="`/chunks/${chunk.id}`">打开 Chunk</RouterLink>
          </article>
        </div>
        <div v-else class="empty-state compact"><Boxes :size="22" /><span>该版本没有可展示的 Chunk</span></div>
        <div v-if="chunksHasMore" class="load-more" data-testid="version-chunks-load-more">
          <button class="secondary-button" type="button" :disabled="loadingMoreChunks" @click="loadMoreChunks">
            {{ loadingMoreChunks ? '加载中' : '加载更多 Chunk' }}
          </button>
        </div>
      </section>
    </template>
  </div>
</template>
