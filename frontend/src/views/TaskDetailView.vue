<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, ArrowLeft, RefreshCw, Radio, XCircle } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError, getAccessToken } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { IngestionRun } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'
import { readSseEvents, type ParsedSseEvent } from '@/utils/sse'

const route = useRoute()
const team = useTeamStore()
const run = ref<IngestionRun | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const events = ref<string[]>([])
const readingEvents = ref(false)
const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

let activeStreamController: AbortController | null = null
let loadVersion = 0

const canCancel = computed(
  () => run.value != null && !['completed', 'failed', 'cancelled'].includes(run.value.status),
)

function currentRunId(): string {
  return String(route.params.runId ?? '')
}

function toApiError(caught: unknown, fallback: string): ApiRequestError {
  return caught instanceof ApiRequestError
    ? caught
    : new ApiRequestError(caught instanceof Error ? caught.message : fallback, 'UNKNOWN_ERROR')
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
  if (!['progress', 'completed', 'failed', 'cancelled'].includes(event.event)) return false
  const current = run.value
  if (!current) return false

  const data = event.data
  if (typeof data.run_id === 'string' && data.run_id !== current.id) return false
  const status = typeof data.status === 'string' ? data.status : event.event
  const stage = typeof data.stage === 'string' ? data.stage : null
  const rawPercent = typeof data.percent === 'number' ? data.percent : current.stage_progress_pct
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
      throw new ApiRequestError('无法读取任务事件流。', 'SSE_ERROR', '', response.status)
    }
    await readSseEvents(response, (event) => {
      if (activeStreamController !== controller || run.value?.id !== currentRun.id) return
      if (applyEvent(event) && activeStreamController === controller) {
        readingEvents.value = false
      }
    })
  } catch (caught) {
    const aborted = controller.signal.aborted ||
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
        <RouterLink class="icon-button" to="/tasks" title="返回任务中心">
          <ArrowLeft :size="18" />
        </RouterLink>
        <div>
          <h2>任务详情</h2>
          <p>{{ run ? shortId(run.id) : '正在读取任务信息' }}</p>
        </div>
      </div>
      <div v-if="run" class="row-actions">
        <button class="secondary-button" type="button" @click="refresh">
          <RefreshCw :size="16" />
          {{ readingEvents ? '连接中' : '刷新' }}
        </button>
        <button
          v-if="run.retryable || ['failed', 'cancelled'].includes(run.status)"
          class="secondary-button"
          type="button"
          @click="retry"
        >
          <RefreshCw :size="16" />
          重试
        </button>
        <button v-if="canCancel" class="secondary-button danger-text" type="button" @click="cancel">
          <XCircle :size="16" />
          取消
        </button>
      </div>
    </div>

    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </div>

    <div v-if="loading && !run" class="panel loading-state">
      <a-spin />
      <span>正在加载任务</span>
    </div>
    <template v-else-if="run">
      <section class="panel detail-panel">
        <div class="detail-heading">
          <div class="detail-icon"><Activity :size="20" /></div>
          <div>
            <h3>{{ run.current_stage || '等待调度' }}</h3>
            <p>文档版本 {{ shortId(run.document_version_id) }}</p>
          </div>
          <StatusPill :status="run.status" />
        </div>
        <div class="progress-track large" aria-hidden="true">
          <span :style="{ width: `${Math.min(100, Math.max(0, run.stage_progress_pct))}%` }" />
        </div>
        <dl class="detail-grid">
          <div><dt>进度</dt><dd>{{ run.stage_progress_pct }}%</dd></div>
          <div><dt>失败原因</dt><dd>{{ run.error_code || '—' }}</dd></div>
          <div><dt>可重试</dt><dd>{{ run.retryable ? '是' : '否' }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatDate(run.created_at) }}</dd></div>
          <div><dt>更新时间</dt><dd>{{ formatDate(run.updated_at) }}</dd></div>
        </dl>
      </section>

      <section class="panel detail-panel">
        <div class="section-heading">
          <h3>事件流</h3>
          <span class="muted-text">{{ readingEvents ? '实时更新中' : '连接已结束' }}</span>
        </div>
        <pre v-if="events.length" class="event-log">{{ events.join('\n') }}</pre>
        <div v-else class="empty-state compact">
          <Radio :size="22" />
          <span>尚未收到任务阶段事件。</span>
        </div>
      </section>
    </template>
  </div>
</template>
