<script setup lang="ts">
import {
  ApiRequestError,
  api,
  getAccessToken,
  normalizeApiError,
} from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Empty as AEmpty,
  Message,
  Spin as ASpin,
  Tag as ATag,
} from '@arco-design/web-vue'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Download, Gauge, Square } from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import { useTeamStore } from '@/stores/team'
import type { EvaluationReport, EvaluationRun } from '@/types/api'
import { formatDate, shortId, statusLabel } from '@/utils/format'
import { readSseEvents } from '@/utils/sse'

const route = useRoute()
const team = useTeamStore()
const run = ref<EvaluationRun | null>(null)
const report = ref<EvaluationReport | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)
const streamStatus = ref('')
const streamStage = ref('')
const streaming = ref(false)

let eventAbort: AbortController | null = null
let loadVersion = 0

const metricEntries = computed(() =>
  Object.entries(report.value?.metrics ?? {}),
)
const currentStatus = computed(
  () => streamStatus.value || run.value?.status || '',
)
const apiBaseUrl = computed(() =>
  (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, ''),
)

function abortEventStream(): void {
  eventAbort?.abort()
  eventAbort = null
  streaming.value = false
}

function isAbortError(caught: unknown): boolean {
  return caught instanceof DOMException
    ? caught.name === 'AbortError'
    : caught instanceof Error && caught.name === 'AbortError'
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

async function fetchReportData(
  teamId: string,
  runId: string,
): Promise<{ run: EvaluationRun; report: EvaluationReport }> {
  const [runView, reportView] = await Promise.all([
    api.getEvalRun(teamId, runId),
    api.getEvalReport(teamId, runId),
  ])
  return { run: runView, report: reportView }
}

async function load(): Promise<void> {
  const version = ++loadVersion
  const runId = String(route.params.runId ?? '')
  if (!team.selectedTeamId || !runId) return
  abortEventStream()
  streamStatus.value = ''
  streamStage.value = ''
  loading.value = true
  error.value = null
  try {
    const data = await fetchReportData(team.selectedTeamId, runId)
    if (version !== loadVersion) return
    run.value = data.run
    report.value = data.report
  } catch (caught) {
    if (version === loadVersion) {
      error.value = normalizeApiError(caught)
    }
  } finally {
    if (version === loadVersion) loading.value = false
  }
  if (
    version === loadVersion &&
    run.value &&
    ['queued', 'running'].includes(run.value.status)
  ) {
    void connectEventStream(team.selectedTeamId, runId)
  }
}

async function connectEventStream(
  teamId: string,
  runId: string,
): Promise<void> {
  abortEventStream()
  const controller = new AbortController()
  eventAbort = controller
  streaming.value = true
  let terminalHandled = false

  try {
    const query = new URLSearchParams({ team_id: teamId, run_id: runId })
    const response = await fetch(
      `${apiBaseUrl.value}/evals/runs/events?${query}`,
      {
        headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
        signal: controller.signal,
      },
    )
    if (!response.ok) {
      throw new ApiRequestError('无法读取评测事件流。', 'SSE_ERROR')
    }

    await readSseEvents(response, async (event) => {
      if (eventAbort !== controller) return
      const status = stringValue(event.data.status)
      const stage = stringValue(event.data.stage)
      if (status) streamStatus.value = status
      if (stage) streamStage.value = stage

      if (
        !terminalHandled &&
        ['completed', 'failed', 'cancelled'].includes(event.event)
      ) {
        terminalHandled = true
        try {
          const data = await fetchReportData(teamId, runId)
          if (eventAbort !== controller) return
          run.value = data.run
          report.value = data.report
        } catch (caught) {
          if (eventAbort === controller) {
            error.value = normalizeApiError(caught)
          }
        }
      }
    })
  } catch (caught) {
    if (!controller.signal.aborted && !isAbortError(caught)) {
      error.value = normalizeApiError(caught)
    }
  } finally {
    if (eventAbort === controller) {
      eventAbort = null
      streaming.value = false
    }
  }
}

async function cancel(): Promise<void> {
  if (!team.selectedTeamId || !run.value) return
  try {
    await api.cancelEvalRun(team.selectedTeamId, run.value.id)
    Message.success('评测已取消')
    await load()
  } catch (caught) {
    error.value = normalizeApiError(caught)
  }
}

function exportReport(): void {
  const blob = new Blob([JSON.stringify(report.value, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `evaluation-${run.value?.id ?? 'report'}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(load)
watch(() => route.params.runId, load)
onBeforeUnmount(() => {
  loadVersion += 1
  abortEventStream()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink
          :to="run ? `/evaluations/${run.dataset_id}` : '/evaluations'"
          custom
          v-slot="{ href, navigate }"
        >
          <a-button
            type="text"
            :href="href"
            @click="navigate"
            title="返回黄金集"
          >
            <ArrowLeft :size="18" />
          </a-button>
        </RouterLink>
        <div>
          <h2>评测报告</h2>
          <p>{{ run ? shortId(run.id) : '正在读取运行结果' }}</p>
        </div>
      </div>
      <div class="row-actions">
        <a-button
          :disabled="!report"
          @click="exportReport"
          type="secondary"
          html-type="button"
        >
          <Download :size="16" />
          导出 JSON
        </a-button>
        <a-button
          v-if="run && ['running', 'queued'].includes(run.status)"
          @click="cancel"
          type="secondary"
          html-type="button"
          status="danger"
        >
          <Square :size="16" />
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
      <span>正在加载评测报告</span>
    </div>
    <template v-else-if="run">
      <a-card class="page-card">
        <div class="detail-heading">
          <div class="detail-icon"><Gauge :size="20" /></div>
          <div>
            <h3>{{ run.engine_mode }}</h3>
            <p>
              黄金集 {{ shortId(run.dataset_id) }} ·
              {{ formatDate(run.created_at) }}
            </p>
          </div>
          <a-tag :color="statusColor(currentStatus)">
            {{ statusLabel(currentStatus) }}
          </a-tag>
        </div>
        <a-descriptions
          :column="{ xs: 1, sm: 2, lg: 3 }"
          bordered
          class="detail-descriptions"
        >
          <a-descriptions-item label="基线运行">
            {{ run.baseline_run_id ? shortId(run.baseline_run_id) : '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="供应商">
            {{ run.provider_id ? shortId(run.provider_id) : '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="模型">
            {{ run.model_id || '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="运行状态">
            {{ currentStatus }}
          </a-descriptions-item>
          <a-descriptions-item label="当前阶段">
            {{ streamStage || (streaming ? '等待事件' : '—') }}
          </a-descriptions-item>
        </a-descriptions>
      </a-card>

      <section class="metric-grid" v-if="metricEntries.length">
        <article
          v-for="[key, value] in metricEntries"
          :key="key"
          class="metric-card"
        >
          <span>{{ key }}</span>
          <strong>
            {{
              typeof value === 'number'
                ? value.toFixed(4)
                : JSON.stringify(value)
            }}
          </strong>
        </article>
      </section>

      <a-card class="page-card">
        <div class="section-heading"><h3>报告明细</h3></div>
        <pre
          v-if="Object.keys(report?.report ?? {}).length"
          class="json-block"
          >{{ JSON.stringify(report?.report, null, 2) }}</pre
        >
        <a-empty v-else class="page-empty">
          <template #image><Gauge :size="22" /></template>
          <span>当前运行尚未生成指标。完成后刷新页面查看报告。</span>
        </a-empty>
      </a-card>
    </template>
  </div>
</template>
