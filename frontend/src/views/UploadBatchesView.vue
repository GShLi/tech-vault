<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Alert as AAlert, Button as AButton, Table as ATable, TableColumn as ATableColumn, Tag as ATag } from '@arco-design/web-vue'
import { api, normalizeApiError, type ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { formatDate, shortId, statusLabel } from '@/utils/format'
import { statusColor } from '@/utils/status'
import type { UploadBatch } from '@/types/api'
const route = useRoute()
const team = useTeamStore()
const batches = ref<UploadBatch[]>([])
const error = ref<ApiRequestError | null>(null)
const loading = ref(false)
let version = 0
async function load() {
  const request = ++version, teamId = team.selectedTeamId, kbId = String(route.query.kbId || '')
  batches.value = []; error.value = null
  if (!teamId || !kbId) return
  loading.value = true
  try { const result = await api.listUploadBatches(teamId, kbId); if (request === version) batches.value = result }
  catch (caught) { if (request === version) error.value = normalizeApiError(caught) }
  finally { if (request === version) loading.value = false }
}
watch(() => [team.selectedTeamId, route.query.kbId], load, { immediate: true })
</script>
<template>
  <div>
    <div class="page-header"><div><h2>上传批次</h2><p>当前知识库中你最近的 100 个上传批次。</p></div><div class="row-actions"><a-button @click="load" :loading="loading">刷新</a-button><RouterLink :to="`/knowledge-bases/${route.query.kbId}`">返回知识库</RouterLink></div></div>
    <a-alert v-if="error" type="error" class="page-alert">{{ error.message }}</a-alert>
    <a-table :data="batches" row-key="id" :pagination="{ pageSize: 20 }" :loading="loading" :scroll="{ x: 680 }">
      <template #columns>
        <a-table-column title="批次"><template #cell="{ record }"><RouterLink :to="`/upload-batches/${record.id}`">{{ shortId(record.id) }}</RouterLink></template></a-table-column>
        <a-table-column title="文件数" data-index="total" />
        <a-table-column title="已完成"><template #cell="{ record }">{{ record.counts.completed || 0 }}</template></a-table-column>
        <a-table-column title="状态"><template #cell="{ record }"><a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag></template></a-table-column>
        <a-table-column title="创建时间"><template #cell="{ record }">{{ formatDate(record.created_at) }}</template></a-table-column>
      </template>
    </a-table>
  </div>
</template>
