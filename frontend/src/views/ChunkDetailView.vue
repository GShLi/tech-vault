<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, History, RefreshCw, Save } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { ChunkHistoryView, ChunkView, DocumentDetailView } from '@/types/api'
import { formatDate } from '@/utils/format'

const route = useRoute()
const auth = useAuthStore()
const team = useTeamStore()
const chunk = ref<ChunkView | null>(null)
const document = ref<DocumentDetailView | null>(null)
const history = ref<ChunkHistoryView[]>([])
const content = ref('')
const loading = ref(false)
const loadingMoreHistory = ref(false)
const historyNextCursor = ref<string | null>(null)
const historyHasMore = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)
const canManageChunk = computed(
  () =>
    Boolean(chunk.value) &&
    (team.canManage ||
      auth.me?.user.is_super_admin === true ||
      document.value?.owner_user_id === auth.me?.user.id),
)

function chunkId(): string {
  return String(route.params.chunkId ?? '')
}

async function load(): Promise<void> {
  if (!team.selectedTeamId || !chunkId()) return
  loading.value = true
  error.value = null
  try {
    const [chunkView, historyPage] = await Promise.all([
      api.getChunk(team.selectedTeamId, chunkId()),
      api.getChunkHistory(team.selectedTeamId, chunkId()),
    ])
    const documentView = await api.getDoc(team.selectedTeamId, chunkView.document_id)
    chunk.value = chunkView
    document.value = documentView
    content.value = chunkView.content
    history.value = historyPage.data
    historyNextCursor.value = historyPage.meta.next_cursor
    historyHasMore.value = historyPage.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function loadMoreHistory(): Promise<void> {
  if (!team.selectedTeamId || !chunkId() || !historyNextCursor.value) return
  loadingMoreHistory.value = true
  try {
    const page = await api.getChunkHistory(
      team.selectedTeamId,
      chunkId(),
      historyNextCursor.value,
    )
    history.value = [...history.value, ...page.data]
    historyNextCursor.value = page.meta.next_cursor
    historyHasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loadingMoreHistory.value = false
  }
}

async function save(): Promise<void> {
  if (!team.selectedTeamId || !chunk.value) return
  saving.value = true
  error.value = null
  try {
    chunk.value = await api.updateChunk(team.selectedTeamId, chunk.value.id, content.value, chunk.value.version)
    Message.success('Chunk 已保存')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

async function toggle(): Promise<void> {
  if (!team.selectedTeamId || !chunk.value) return
  try {
    if (chunk.value.status === 'enabled') await api.disableChunks(team.selectedTeamId, [chunk.value.id])
    else await api.enableChunks(team.selectedTeamId, [chunk.value.id])
    Message.success('Chunk 状态已更新')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

async function regenerate(): Promise<void> {
  if (!team.selectedTeamId || !chunk.value) return
  try {
    const result = await api.regenerateChunks(team.selectedTeamId, chunk.value.document_id)
    Message.success(`已提交重建任务：${result.run_id}`)
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(load)
watch(() => route.params.chunkId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink class="icon-button" to="/chunks" title="返回 Chunk 管理"><ArrowLeft :size="18" /></RouterLink>
        <div><h2>Chunk 详情</h2><p>{{ chunk ? chunk.id : '正在读取 Chunk' }}</p></div>
      </div>
      <div v-if="chunk && canManageChunk" class="row-actions">
        <button class="secondary-button" type="button" @click="toggle">{{ chunk.status === 'enabled' ? '禁用' : '启用' }}</button>
        <button class="secondary-button" type="button" @click="regenerate"><RefreshCw :size="16" />重建文档 Chunk</button>
      </div>
    </div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !chunk" class="panel loading-state"><a-spin /><span>正在加载 Chunk</span></div>
    <template v-else-if="chunk">
      <div class="split-grid">
        <section class="panel detail-panel">
          <div class="detail-heading"><div class="detail-icon"><History :size="20" /></div><div><h3>分块内容</h3><p>{{ chunk.heading_path.join(' / ') || '无结构路径' }}</p></div><StatusPill :status="chunk.status" /></div>
          <form class="form-stack" @submit.prevent="save">
            <label class="field"><span>内容</span><textarea v-model="content" rows="16" :disabled="!canManageChunk" /></label>
            <button v-if="chunk && canManageChunk" class="primary-button" type="submit" :disabled="saving || content === chunk.content"><Save :size="16" />{{ saving ? '保存中' : '保存修改' }}</button>
          </form>
          <dl class="detail-grid"><div><dt>文档</dt><dd>{{ chunk.document_id }}</dd></div><div><dt>来源定位</dt><dd><code>{{ JSON.stringify(chunk.source_locator) }}</code></dd></div><div><dt>版本</dt><dd>v{{ chunk.version }}</dd></div><div><dt>更新时间</dt><dd>{{ formatDate(chunk.updated_at) }}</dd></div></dl>
        </section>
        <section class="panel detail-panel">
          <div class="section-heading"><h3>变更历史</h3><span class="muted-text">{{ history.length }} 条</span></div>
          <div v-if="history.length" class="timeline">
            <article v-for="item in history" :key="item.id" class="timeline-item"><div class="timeline-dot" /><div><strong>{{ item.action }}</strong><span class="cell-subtitle">{{ formatDate(item.created_at) }} · {{ item.actor_id }}</span><p class="pre-wrap">{{ item.new_content || '—' }}</p></div></article>
          </div>
          <div v-else class="empty-state compact"><History :size="22" /><span>暂无变更记录</span></div>
          <div v-if="historyHasMore" class="load-more" data-testid="chunk-history-load-more">
            <button class="secondary-button" type="button" :disabled="loadingMoreHistory" @click="loadMoreHistory">
              {{ loadingMoreHistory ? '加载中' : '加载更多记录' }}
            </button>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
