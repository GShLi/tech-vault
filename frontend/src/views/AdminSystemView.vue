<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Card as ACard,
  Descriptions as ADescriptions,
  DescriptionsItem as ADescriptionsItem,
  Spin as ASpin,
  Tag as ATag,
} from '@arco-design/web-vue'

import { statusLabel } from '@/utils/format'
import { onMounted, ref } from 'vue'
import {
  CheckCircle2,
  Database,
  RefreshCw,
  Server,
  ShieldCheck,
} from 'lucide-vue-next'

import { statusColor } from '@/utils/status'
import type { HealthView, VersionView } from '@/types/api'

const health = ref<HealthView | null>(null)
const ready = ref<HealthView | null>(null)
const version = ref<VersionView | null>(null)
const loading = ref(false)
const error = ref<ApiRequestError | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [healthView, readyView, versionView] = await Promise.all([
      api.getHealth(),
      api.getReady(),
      api.getVersion(),
    ])
    health.value = healthView
    ready.value = readyView
    version.value = versionView
  } catch (caught) {
    error.value = normalizeApiError(caught)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>系统状态</h2>
        <p>平台 API、依赖就绪状态与当前版本。</p>
      </div>
      <a-button
        :disabled="loading"
        @click="load"
        type="secondary"
        html-type="button"
      >
        <RefreshCw :size="16" />
        重新检查
      </a-button>
    </div>
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
      <a-button @click="load" type="text" html-type="button">重试</a-button>
    </a-alert>
    <div v-if="loading && !health" class="panel loading-state">
      <a-spin />
      <span>正在检查系统状态</span>
    </div>
    <template v-else>
      <div class="metric-grid system-grid">
        <article class="metric-card system-card">
          <div class="detail-icon"><Server :size="20" /></div>
          <span>API Health</span>
          <strong>{{ health?.status || 'unknown' }}</strong>
          <a-tag
            :color="statusColor(health?.status === 'ok' ? 'active' : 'failed')"
          >
            {{ health?.status === 'ok' ? '运行中' : '异常' }}
          </a-tag>
        </article>
        <article class="metric-card system-card">
          <div class="detail-icon"><Database :size="20" /></div>
          <span>依赖 Ready</span>
          <strong>{{ ready?.status || 'unknown' }}</strong>
          <a-tag
            :color="
              statusColor(ready?.status === 'ready' ? 'active' : 'failed')
            "
          >
            {{ ready?.status === 'ready' ? '就绪' : '未就绪' }}
          </a-tag>
        </article>
        <article class="metric-card system-card">
          <div class="detail-icon"><ShieldCheck :size="20" /></div>
          <span>版本</span>
          <strong>{{ version?.version || '—' }}</strong>
          <a-tag :color="statusColor('active')">{{ '已部署' }}</a-tag>
        </article>
      </div>
      <a-card class="page-card">
        <div class="section-heading">
          <h3>检查说明</h3>
          <CheckCircle2 :size="16" />
        </div>
        <a-descriptions
          :column="{ xs: 1, sm: 2, lg: 3 }"
          bordered
          class="detail-descriptions"
        >
          <a-descriptions-item label="Health">
            后端进程可响应请求
          </a-descriptions-item>
          <a-descriptions-item label="Ready">
            数据库与必需依赖可接受流量
          </a-descriptions-item>
          <a-descriptions-item label="Version">
            当前部署版本号
          </a-descriptions-item>
        </a-descriptions>
      </a-card>
    </template>
  </div>
</template>
