<script setup lang="ts">
import {
  ApiRequestError,
  api,
  getAccessToken,
  normalizeApiError as toApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  Message,
  Progress as AProgress,
  Spin as ASpin,
  Tag as ATag,
} from '@arco-design/web-vue'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, ArrowLeft, RefreshCw, Radio, XCircle } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { IngestionRun } from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'
import { readSseEvents, type ParsedSseEvent } from '@/utils/sse'

const route = useRoute()
const team = useTeamStore()
const run = ref<IngestionRun | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const events = ref<string[]>([])
const readingEvents = ref(false)
const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(
  /\/$/,
  '',
)

let activeStreamController: AbortController | null = null
let loadVersion = 0

const canCancel = computed(
  () =>
    run.value != null &&
    !['completed', 'failed', 'cancelled'].includes(run.value.status),
)

function currentRunId(): string {
  return String(route.params.runId ?? '')
}

function stopEventStream(): void {
  activeStreamController?.abort()
  activeStreamController = null
  readingEvents.value = false
}

async function load(): Promise<void> {
  const runId = currentRunId()
  if (!team.selectedTeamId || !runId) return
  const version = ++loadVersion
  stopEventStream()
  events.value = []
  loading.value = true
  error.value = null
  try {
    const nextRun = await api.getIngestionRun(team.selectedTeamId, runId)
    if (version !== loadVersion || currentRunId() !== runId) return
    run.value = nextRun
    if (!['completed', 'failed', 'cancelled'].includes(nextRun.status)) {
      void readEvents()
    }
  } catch (caught) {
    if (version === loadVersion && currentRunId() === runId) {
      error.value = toApiError(caught, '任务加载失败。')
    }
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function refresh(): Promise<void> {
  await load()
}

async function retry(): Promise<void> {
  if (!team.selectedTeamId || !run.value) return
  try {
    await api.retryIngestion(team.selectedTeamId, run.value.id)
    Message.success('任务已重新排队')
    await load()
  } catch (caught) {
    error.value = toApiError(caught, '任务重试失败。')
  }
}

async function cancel(): Promise<void> {
  if (!team.selectedTeamId || !run.value) return
  try {
    await api.cancelIngestion(team.selectedTeamId, run.value.id)
    Message.success('任务已取消')
    await load()
  } catch (caught) {
    error.value = toApiError(caught, '任务取消失败。')
  }
}

function applyEvent(event: ParsedSseEvent): boolean {
  if (!['progress', 'completed', 'failed', 'cancelled'].includes(event.event))
    return false
  const current = run.value
  if (!current) return false

  const data = event.data
  if (typeof data.run_id === 'string' && data.run_id !== current.id)
    return false
  const status = typeof data.status === 'string' ? data.status : event.event
  const stage = typeof data.stage === 'string' ? data.stage : null
  const rawPercent =
    typeof data.percent === 'number' ? data.percent : current.stage_progress_pct
  const percent = Math.min(100, Math.max(0, Math.round(rawPercent)))
  const errorCode = typeof data.error_code === 'string' ? data.error_code : null
  const retryable =
    typeof data.retryable === 'boolean' ? data.retryable : current.retryable

  run.value = {
    ...current,
    status,
    current_stage: stage,
    stage_progress_pct: percent,
    error_code: errorCode,
    retryable,
  }
  events.value.push(`[${event.event}] ${event.raw}`)
  return ['completed', 'failed', 'cancelled'].includes(event.event)
}

async function readEvents(): Promise<void> {
  if (!team.selectedTeamId || !run.value) return
  stopEventStream()
  const controller = new AbortController()
  const currentRun = run.value
  activeStreamController = controller
  readingEvents.value = true
  error.value = null
  try {
    const query = new URLSearchParams({
      team_id: team.selectedTeamId,
      run_id: currentRun.id,
    })
    const response = await fetch(`${apiBaseUrl}/ingestions/events?${query}`, {
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
      signal: controller.signal,
    })
    if (!response.ok) {
      throw new ApiRequestError(
        '无法读取任务事件流。',
        'SSE_ERROR',
        '',
        response.status,
      )
    }
    await readSseEvents(response, (event) => {
      if (
        activeStreamController !== controller ||
        run.value?.id !== currentRun.id
      )
        return
      if (applyEvent(event) && activeStreamController === controller) {
        readingEvents.value = false
      }
    })
  } catch (caught) {
    const aborted =
      controller.signal.aborted ||
      (caught instanceof DOMException && caught.name === 'AbortError')
    if (!aborted && activeStreamController === controller) {
      error.value = toApiError(caught, '任务事件流读取失败。')
    }
  } finally {
    if (activeStreamController === controller) {
      activeStreamController = null
      readingEvents.value = false
    }
  }
}

onMounted(() => void load())
watch(
  () => route.params.runId,
  (next, previous) => {
    if (String(next ?? '') === String(previous ?? '')) return
    run.value = null
    error.value = null
    void load()
  },
)
onBeforeUnmount(() => {
  loadVersion += 1
  stopEventStream()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink to="/tasks" custom v-slot="{ href, navigate }">
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回任务中心"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>任务详情</h2>
          <p>{{ run ? shortId(run.id) : '正在读取任务信息' }}</p>
        </div>
      </div>
      <div v-if="run" class="row-actions">
        <a-button @click="refresh" type="secondary" html-type="button">
          <RefreshCw :size="16" />
          {{ readingEvents ? '连接中' : '刷新' }}
        </a-button>
        <a-button
          v-if="['failed', 'cancelled'].includes(run.status)"
          @click="retry"
          type="secondary"
          html-type="button"
        >
          <RefreshCw :size="16" />
          重试
        </a-button>
        <a-button
          v-if="canCancel"
          @click="cancel"
          type="secondary"
          html-type="button"
          status="danger"
        >
          <XCircle :size="16" />
          取消
        </a-button>
      </div>
    </div>

    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>

    <div v-if="loading && !run" class="panel loading-state">
      <a-spin />
      <span>正在加载任务</span>
    </div>
    <template v-else-if="run">
      <a-alert v-if="run.current_stage === 'waiting_index'" type="info" class="page-alert">
        同一团队正在处理其他文档，本任务会自动继续，无需重新上传。
      </a-alert>
      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><Activity :size="20" /></div>
          <div>
            <h3>{{ run.current_stage ? statusLabel(run.current_stage) : '等待调度' }}</h3>
            <p>文档版本 {{ shortId(run.document_version_id) }}</p>
          </div>
          <a-tag :color="statusColor(run.status)">
            {{ statusLabel(run.status) }}
          </a-tag>
        </div>
        <a-progress
          :percent="
            Math.max(
              0,
              Math.min(
                1,
                Math.min(100, Math.max(0, run.stage_progress_pct)) / 100,
              ),
            )
          "
          :show-text="false"
          size="small"
        ></a-progress>
        <a-descriptions
          :column="{ xs: 1, sm: 2, lg: 3 }"
          bordered
          class="detail-descriptions"
        >
          <a-descriptions-item label="进度">
            {{ run.stage_progress_pct }}%
          </a-descriptions-item>
          <a-descriptions-item label="失败原因">
            {{ run.error_code || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="可重试">
            {{ run.retryable ? '是' : '否' }}
          </a-descriptions-item>
          <a-descriptions-item label="创建时间">
            {{ formatDate(run.created_at) }}
          </a-descriptions-item>
          <a-descriptions-item label="更新时间">
            {{ formatDate(run.updated_at) }}
          </a-descriptions-item>
        </a-descriptions>
      </a-card>

      <a-card class="page-card">
        <div class="section-heading">
          <h3>事件流</h3>
          <span class="muted-text">
            {{ readingEvents ? '实时更新中' : '连接已结束' }}
          </span>
        </div>
        <pre v-if="events.length" class="event-log">{{
          events.join('\n')
        }}</pre>
        <a-empty v-else class="page-empty">
          <template #image><Radio :size="22" /></template>
          <span>尚未收到任务阶段事件。</span>
        </a-empty>
      </a-card>
    </template>
  </div>
</template>
