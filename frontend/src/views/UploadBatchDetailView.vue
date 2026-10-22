<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Alert as AAlert, Button as AButton, Card as ACard, Empty as AEmpty,
  Input as AInput, Select as ASelect, Option as AOption, Table as ATable,
  TableColumn as ATableColumn, Tag as ATag, Progress as AProgress, Message } from '@arco-design/web-vue'
import { api, normalizeApiError, type ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { formatBytes, formatDate, shortId, statusLabel } from '@/utils/format'
import { statusColor } from '@/utils/status'
import type { UploadBatch } from '@/types/api'

const route = useRoute()
const team = useTeamStore()
const batch = ref<UploadBatch | null>(null)
const error = ref<ApiRequestError | null>(null)
const loading = ref(false)
const operating = ref(false)
const query = ref('')
const filter = ref('all')
let version = 0
let scopeVersion = 0
let timer: ReturnType<typeof setTimeout> | null = null
const rows = computed(() => (batch.value?.files || []).filter((file) =>
  file.file_name.toLowerCase().includes(query.value.toLowerCase()) &&
  (filter.value === 'all' || (filter.value === 'failed' ? ['failed', 'upload_failed'].includes(file.status) : file.status === filter.value))))
const hasMissing = computed(() => batch.value?.files.some((file) => !file.run_id))
const done = computed(() => batch.value?.counts.completed || 0)
function stop() { if (timer) clearTimeout(timer); timer = null }
async function load(poll = false) {
  stop()
  const request = ++version, teamId = team.selectedTeamId, id = String(route.params.batchId || '')
  if (!teamId || !id) return
  if (!poll) loading.value = true
  try {
    const result = await api.getUploadBatch(teamId, id)
    if (request !== version) return
    batch.value = result; error.value = null
    if (['uploading', 'queued', 'processing'].includes(result.status)) timer = setTimeout(() => void load(true), 3000)
  } catch (caught) { if (request === version) error.value = normalizeApiError(caught) }
  finally { if (request === version) loading.value = false }
}
async function retry(runId?: string) {
  if (!batch.value || !team.selectedTeamId || operating.value) return
  const current = scopeVersion
  operating.value = true
  try {
    if (runId) await api.retryIngestion(team.selectedTeamId, runId)
    else await api.retryUploadBatch(team.selectedTeamId, batch.value.id)
    if (current !== scopeVersion) return
    Message.success('任务已重新排队'); await load()
  } catch (caught) { if (current === scopeVersion) error.value = normalizeApiError(caught) }
  finally { if (current === scopeVersion) operating.value = false }
}
async function cancel(runId: string) {
  if (!team.selectedTeamId || operating.value) return
  const current = scopeVersion
  operating.value = true
  try { await api.cancelIngestion(team.selectedTeamId, runId); if (current === scopeVersion) await load() }
  catch (caught) { if (current === scopeVersion) error.value = normalizeApiError(caught) }
  finally { if (current === scopeVersion) operating.value = false }
}
watch(() => [team.selectedTeamId, route.params.batchId], () => { scopeVersion++; operating.value = false; batch.value = null; void load() }, { immediate: true })
onBeforeUnmount(() => { scopeVersion++; version++; stop() })
</script>

<template>
  <div>
    <div class="page-header"><div><h2>批次处理进度</h2><p>{{ batch ? `${shortId(batch.id)} · ${formatDate(batch.created_at)}` : '正在加载' }}</p></div><div class="row-actions"><a-button :loading="loading" @click="load()">刷新</a-button><RouterLink v-if="batch" :to="`/knowledge-bases/${batch.kb_id}`">返回知识库</RouterLink></div></div>
    <a-alert v-if="error" type="error" class="page-alert">{{ error.message }}</a-alert>
    <template v-if="batch">
      <a-card class="page-card">
        <div class="section-heading"><h3>共 {{ batch.total }} 个文件，{{ done }} 个已可用于问答</h3><a-tag :color="statusColor(batch.status)">{{ statusLabel(batch.status) }}</a-tag></div>
        <a-progress :percent="batch.total ? done / batch.total : 0" />
        <p>文件上传成功后仍需解析、切分和索引发布。关闭此页面不会中断已接收文件的处理。</p>
        <div class="row-actions">
          <a-button v-if="batch.status === 'uploading' || batch.status === 'queued' || batch.counts.failed" :loading="operating" @click="retry()">{{ batch.counts.failed ? '重试处理失败项' : '启动处理' }}</a-button>
          <RouterLink v-if="hasMissing" :to="{ path: `/knowledge-bases/${batch.kb_id}/upload`, query: { batchId: batch.id } }">补传未上传文件</RouterLink>
          <RouterLink :to="`/knowledge-bases/${batch.kb_id}/upload`">继续上传新文档</RouterLink>
        </div>
      </a-card>
      <a-card class="page-card">
        <div class="batch-filters"><a-input v-model="query" placeholder="搜索文件名" allow-clear /><a-select v-model="filter"><a-option value="all">全部文件</a-option><a-option value="failed">上传或处理失败</a-option><a-option value="queued">排队中</a-option><a-option value="prepared">等待发布</a-option><a-option value="completed">已完成</a-option><a-option value="cancelled">已取消</a-option></a-select></div>
        <a-table :data="rows" row-key="id" :pagination="{ pageSize: 20 }" :bordered="false" :scroll="{ x: 1000 }">
          <template #columns>
            <a-table-column title="文件" :width="260"><template #cell="{ record }"><RouterLink v-if="record.document_id" :to="`/documents/${record.document_id}`">{{ record.file_name }}</RouterLink><strong v-else>{{ record.file_name }}</strong><span class="cell-subtitle">{{ formatBytes(record.size_bytes) }}</span></template></a-table-column>
            <a-table-column title="阶段 / 进度" :width="220"><template #cell="{ record }">{{ statusLabel(record.stage) }}<a-progress :percent="record.progress / 100" /></template></a-table-column>
            <a-table-column title="状态" :width="120"><template #cell="{ record }"><a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag></template></a-table-column>
            <a-table-column title="原因"><template #cell="{ record }">{{ record.failure_details.message || record.error_code || (record.status === 'upload_failed' ? '服务器未收到该文件，请重新选择并补传。' : '—') }}</template></a-table-column>
            <a-table-column title="操作" :width="190"><template #cell="{ record }"><div class="row-actions"><RouterLink v-if="record.run_id" :to="`/tasks/${record.run_id}`">查看任务</RouterLink><a-button v-if="['failed', 'cancelled'].includes(record.status) && record.run_id" type="text" :disabled="operating" @click="retry(record.run_id)">重试</a-button><a-button v-if="['queued', 'running', 'prepared'].includes(record.status) && !['indexing', 'validating'].includes(record.stage)" type="text" status="danger" :disabled="operating" @click="cancel(record.run_id)">取消</a-button></div></template></a-table-column>
          </template>
          <template #empty><a-empty>没有符合条件的文件</a-empty></template>
        </a-table>
      </a-card>
    </template>
  </div>
</template>
<style scoped>
.batch-filters { display: flex; gap: 12px; max-width: 600px; margin-bottom: 20px; }
.batch-filters :deep(.arco-select) { max-width: 200px; }
@media (max-width: 640px) { .batch-filters { flex-direction: column; } }
</style>
