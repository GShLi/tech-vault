<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CheckCircle2, Database, RefreshCw, Server, ShieldCheck } from 'lucide-vue-next'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
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
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>系统状态</h2><p>平台 API、依赖就绪状态与当前版本。</p></div><button class="secondary-button" type="button" :disabled="loading" @click="load"><RefreshCw :size="16" />重新检查</button></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span><button class="inline-link" type="button" @click="load">重试</button></div>
    <div v-if="loading && !health" class="panel loading-state"><a-spin /><span>正在检查系统状态</span></div>
    <template v-else>
      <div class="metric-grid system-grid">
        <article class="metric-card system-card"><div class="detail-icon"><Server :size="20" /></div><span>API Health</span><strong>{{ health?.status || 'unknown' }}</strong><StatusPill :status="health?.status === 'ok' ? 'active' : 'failed'" :label="health?.status === 'ok' ? '运行中' : '异常'" /></article>
        <article class="metric-card system-card"><div class="detail-icon"><Database :size="20" /></div><span>依赖 Ready</span><strong>{{ ready?.status || 'unknown' }}</strong><StatusPill :status="ready?.status === 'ready' ? 'active' : 'failed'" :label="ready?.status === 'ready' ? '就绪' : '未就绪'" /></article>
        <article class="metric-card system-card"><div class="detail-icon"><ShieldCheck :size="20" /></div><span>版本</span><strong>{{ version?.version || '—' }}</strong><StatusPill status="active" label="已部署" /></article>
      </div>
      <section class="panel detail-panel">
        <div class="section-heading"><h3>检查说明</h3><CheckCircle2 :size="16" /></div>
        <dl class="detail-grid"><div><dt>Health</dt><dd>后端进程可响应请求</dd></div><div><dt>Ready</dt><dd>数据库与必需依赖可接受流量</dd></div><div><dt>Version</dt><dd>当前部署版本号</dd></div></dl>
      </section>
    </template>
  </div>
</template>
