<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  Form as AForm,
  FormItem as AFormItem,
  Message,
  Spin as ASpin,
  Tag as ATag,
  Textarea as ATextarea,
  Timeline as ATimeline,
  TimelineItem as ATimelineItem,
} from '@arco-design/web-vue'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, History, RefreshCw, Save } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type {
  ChunkHistoryView,
  ChunkView,
  DocumentDetailView,
} from '@/types/api'
import { formatDate, statusLabel } from '@/utils/format'

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
    const documentView = await api.getDoc(
      team.selectedTeamId,
      chunkView.document_id,
    )
    chunk.value = chunkView
    document.value = documentView
    content.value = chunkView.content
    history.value = historyPage.data
    historyNextCursor.value = historyPage.meta.next_cursor
    historyHasMore.value = historyPage.meta.has_more
  } catch (caught) {
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
  } finally {
    loadingMoreHistory.value = false
  }
}

async function save(): Promise<void> {
  if (!team.selectedTeamId || !chunk.value) return
  saving.value = true
  error.value = null
  try {
    chunk.value = await api.updateChunk(
      team.selectedTeamId,
      chunk.value.id,
      content.value,
      chunk.value.version,
    )
    Message.success('Chunk 已保存')
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    saving.value = false
  }
}

async function toggle(): Promise<void> {
  if (!team.selectedTeamId || !chunk.value) return
  try {
    if (chunk.value.status === 'enabled')
      await api.disableChunks(team.selectedTeamId, [chunk.value.id])
    else await api.enableChunks(team.selectedTeamId, [chunk.value.id])
    Message.success('Chunk 状态已更新')
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}

async function regenerate(): Promise<void> {
  if (!team.selectedTeamId || !chunk.value) return
  try {
    const result = await api.regenerateChunks(
      team.selectedTeamId,
      chunk.value.document_id,
    )
    Message.success(`已提交重建任务：${result.run_id}`)
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}

onMounted(load)
watch(() => route.params.chunkId, load)
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink to="/chunks" custom v-slot="{ href, navigate }">
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回 Chunk 管理"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>Chunk 详情</h2>
          <p>{{ chunk ? chunk.id : '正在读取 Chunk' }}</p>
        </div>
      </div>
      <div v-if="chunk && canManageChunk" class="row-actions">
        <a-button @click="toggle" type="secondary" html-type="button">
          {{ chunk.status === 'enabled' ? '禁用' : '启用' }}
        </a-button>
        <a-button @click="regenerate" type="secondary" html-type="button">
          <RefreshCw :size="16" />
          重建文档 Chunk
        </a-button>
      </div>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <div v-if="loading && !chunk" class="panel loading-state">
      <a-spin />
      <span>正在加载 Chunk</span>
    </div>
    <template v-else-if="chunk">
      <div class="split-grid">
        <a-card class="page-card">
          <div class="detail-heading">
            <div class="detail-icon"><History :size="20" /></div>
            <div>
              <h3>分块内容</h3>
              <p>{{ chunk.heading_path.join(' / ') || '无结构路径' }}</p>
            </div>
            <a-tag :color="statusColor(chunk.status)">
              {{ statusLabel(chunk.status) }}
            </a-tag>
          </div>
          <a-form
            class="form-stack"
            :model="{ content }"
            layout="vertical"
            @submit-success="save"
          >
            <a-form-item field="content">
              <template #label>内容</template>
              <a-textarea
                v-model="content"
                :disabled="!canManageChunk"
                :textarea-attrs="{ rows: '16' }"
              ></a-textarea>
            </a-form-item>
            <a-button
              v-if="chunk && canManageChunk"
              :disabled="saving || content === chunk.content"
              type="primary"
              html-type="submit"
            >
              <Save :size="16" />
              {{ saving ? '保存中' : '保存修改' }}
            </a-button>
          </a-form>
          <a-descriptions
            :column="{ xs: 1, sm: 2, lg: 3 }"
            bordered
            class="detail-descriptions"
          >
            <a-descriptions-item label="文档">
              {{ chunk.document_id }}
            </a-descriptions-item>
            <a-descriptions-item label="来源定位">
              <code>{{ JSON.stringify(chunk.source_locator) }}</code>
            </a-descriptions-item>
            <a-descriptions-item label="版本">
              v{{ chunk.version }}
            </a-descriptions-item>
            <a-descriptions-item label="更新时间">
              {{ formatDate(chunk.updated_at) }}
            </a-descriptions-item>
          </a-descriptions>
        </a-card>
        <a-card class="page-card">
          <div class="section-heading">
            <h3>变更历史</h3>
            <span class="muted-text">{{ history.length }} 条</span>
          </div>
          <a-timeline v-if="history.length">
            <a-timeline-item v-for="item in history" :key="item.id">
              <div>
                <strong>{{ item.action }}</strong>
                <span class="cell-subtitle">
                  {{ formatDate(item.created_at) }} · {{ item.actor_id }}
                </span>
                <p class="pre-wrap">{{ item.new_content || '—' }}</p>
              </div>
            </a-timeline-item>
          </a-timeline>
          <a-empty v-else class="page-empty">
            <template #image><History :size="22" /></template>
            <span>暂无变更记录</span>
          </a-empty>
          <div
            v-if="historyHasMore"
            class="load-more"
            data-testid="chunk-history-load-more"
          >
            <a-button
              :disabled="loadingMoreHistory"
              @click="loadMoreHistory"
              type="secondary"
              html-type="button"
            >
              {{ loadingMoreHistory ? '加载中' : '加载更多记录' }}
            </a-button>
          </div>
        </a-card>
      </div>
    </template>
  </div>
</template>
