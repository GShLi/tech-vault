<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Alert as AAlert, Button as AButton, Card as ACard, Form as AForm, FormItem as AFormItem,
  Input as AInput, Modal as AModal, Option as AOption, Select as ASelect, Upload as AUpload,
  Table as ATable, TableColumn as ATableColumn, Progress as AProgress, Tag as ATag, type FileItem } from '@arco-design/web-vue'
import { ArrowLeft, Upload } from 'lucide-vue-next'
import { api, normalizeApiError, type ApiRequestError } from '@/api/client'
import { useTeamStore } from '@/stores/team'
import { useUploadQueue } from '@/composables/useUploadQueue'
import { useUnsavedChanges } from '@/composables/useUnsavedChanges'
import { formatBytes, parseLines } from '@/utils/format'
import type { KnowledgeBase, UploadBatch, UploadLimits } from '@/types/api'

const route = useRoute()
const router = useRouter()
const team = useTeamStore()
const kb = ref<KnowledgeBase | null>(null)
const limits = ref<UploadLimits | null>(null)
const resumeBatch = ref<UploadBatch | null>(null)
const loadError = ref<ApiRequestError | null>(null)
const product = ref('')
const versionValues = ref('')
const visibility = ref('team_shared')
const dataClassification = ref('internal')
const queue = useUploadQueue()
const { entries, uploading, error, finished, selectionErrors, successful, failed } = queue
const statuses = { pending: '待上传', uploading: '上传中', uploaded: '已上传', failed: '上传失败' }
const selectedBytes = computed(() => entries.value.reduce((total, item) => total + item.file.size, 0))
const duplicateNames = computed(() => new Set(entries.value.map((entry) => entry.file.name)).size < entries.value.length)
let requestId = 0
const seenFileIds = new Set<string>()
useUnsavedChanges(() => uploading.value || entries.value.some((entry) => entry.status !== 'uploaded'), () => queue.reset(),
  '尚未上传成功的文件需要重新选择。已被服务器接收的文件会继续处理。是否离开？')
async function load() {
  const request = ++requestId, teamId = team.selectedTeamId, kbId = String(route.params.kbId || '')
  queue.reset(); seenFileIds.clear(); kb.value = null; resumeBatch.value = null; loadError.value = null
  if (!teamId || !kbId) return
  try {
    const [current, configuration, batch] = await Promise.all([api.getKb(teamId, kbId), api.uploadLimits(),
      route.query.batchId ? api.getUploadBatch(teamId, String(route.query.batchId)) : Promise.resolve(null)])
    if (request !== requestId) return
    if (batch && batch.kb_id !== kbId) throw new Error('上传批次不属于当前知识库。')
    kb.value = current; limits.value = configuration; resumeBatch.value = batch
    if (batch) {
      product.value = batch.metadata.product; versionValues.value = batch.metadata.version_values.join(', ')
      visibility.value = batch.metadata.visibility; dataClassification.value = batch.metadata.data_classification
    }
  } catch (caught) { if (request === requestId) loadError.value = normalizeApiError(caught) }
}
function onFileChange(files: FileItem[]) {
  if (!limits.value || uploading.value) return
  const fresh = files.filter((file) => file.file && !seenFileIds.has(file.uid))
  fresh.forEach((file) => seenFileIds.add(file.uid))
  queue.add(fresh.map((file) => file.file!), limits.value, resumeBatch.value)
}
function start() {
  if (!team.selectedTeamId || !kb.value) return
  return queue.start({ team_id: team.selectedTeamId, kb_id: kb.value.id, product: product.value.trim(),
    version_values: parseLines(versionValues.value), visibility: visibility.value, data_classification: dataClassification.value }, limits.value?.upload_concurrency)
}
async function viewProgress() {
  const batches = queue.submittedBatchIds.value
  const path = successful.value.length === 1 && entries.value.length === 1
    ? `/tasks/${successful.value[0].runId}`
    : batches.length === 1 ? `/upload-batches/${batches[0]}` : '/upload-batches'
  finished.value = false
  // The batch preserves failed upload records; local files are intentionally discarded on navigation.
  queue.reset()
  await router.push({ path, query: { kbId: String(route.params.kbId || '') } })
}
function continueUploading() {
  if (resumeBatch.value) {
    for (const entry of successful.value) {
      const file = resumeBatch.value.files.find((item) => item.client_id === entry.id)
      if (file) file.run_id = entry.runId || null
    }
  }
  queue.continueUploading()
}
watch(() => [team.selectedTeamId, route.params.kbId, route.query.batchId], load, { immediate: true })
onBeforeUnmount(() => { requestId++ })
</script>

<template>
  <div>
    <div class="page-header">
      <div class="heading-with-back">
        <RouterLink :to="`/knowledge-bases/${route.params.kbId}`" custom v-slot="{ href, navigate }"><a-button type="text" :href="href" @click="navigate" aria-label="返回知识库"><ArrowLeft :size="18" /></a-button></RouterLink>
        <div><h2>上传文档</h2><p>目标知识库：<strong data-testid="upload-target">{{ kb?.name || '正在加载' }}</strong></p></div>
      </div>
      <RouterLink :to="{ path: '/upload-batches', query: { kbId: route.params.kbId } }">查看上传批次</RouterLink>
    </div>
    <a-alert v-if="loadError || error" type="error" class="page-alert">{{ (loadError || error)?.message }}<a-button v-if="loadError" type="text" @click="load">重新加载</a-button></a-alert>
    <a-card v-if="kb && limits" class="page-card">
      <a-alert v-if="resumeBatch" type="info" class="page-alert">补传当前批次中未收到的文件；请重新选择同名、同大小的原文件。已上传的文件会自动跳过。</a-alert>
      <a-form :model="{ product, versionValues, visibility, dataClassification }" layout="vertical" @submit-success="start">
        <div class="upload-metadata-grid">
          <a-form-item field="product" label="产品"><a-input v-model="product" data-testid="upload-product" placeholder="例如 Spring Boot" :disabled="uploading || !!resumeBatch" /></a-form-item>
          <a-form-item field="versionValues" label="版本标签"><a-input v-model="versionValues" data-testid="upload-versions" placeholder="多个版本用逗号分隔" :disabled="uploading || !!resumeBatch" /></a-form-item>
          <a-form-item field="visibility" label="可见性"><a-select v-model="visibility" :disabled="uploading || !!resumeBatch"><a-option value="team_shared">团队共享</a-option><a-option value="private">私有</a-option></a-select></a-form-item>
          <a-form-item field="dataClassification" label="数据分类"><a-select v-model="dataClassification" :disabled="uploading || !!resumeBatch"><a-option value="internal">内部</a-option><a-option value="private">私有</a-option><a-option value="restricted">受限</a-option><a-option value="public">公开</a-option></a-select></a-form-item>
        </div>
        <p class="muted-text">以上设置用于新加入批次的所有文件；重试文件沿用原批次设置。</p>
        <a-upload multiple draggable accept=".md,.txt,.pdf,.docx" :file-list="[]" :show-file-list="false" :auto-upload="false" :disabled="uploading" @change="onFileChange">
          <template #upload-button><div class="upload-dropzone"><Upload :size="24" /><strong>点击选择或拖拽多个文档</strong><span>每批最多 {{ limits.max_files }} 个文件，单文件 {{ formatBytes(limits.max_file_bytes) }}，总计 {{ formatBytes(limits.max_total_bytes) }}</span></div></template>
        </a-upload>
        <a-alert v-if="selectionErrors.length" type="warning" class="page-alert"><div v-for="message in selectionErrors.slice(0, 5)" :key="message">{{ message }}</div><span v-if="selectionErrors.length > 5">另有 {{ selectionErrors.length - 5 }} 个文件未加入。</span></a-alert>
        <a-alert v-if="duplicateNames" type="warning" class="page-alert">清单中有同名文件，将分别创建文档，不会覆盖已有文件；可移除不需要的项。</a-alert>
        <div class="section-heading upload-summary"><span>已选 {{ entries.length }} 个文件 · {{ formatBytes(selectedBytes) }} · 已上传 {{ successful.length }} · 失败 {{ failed.length }}</span><a-button v-if="entries.length" :disabled="uploading" type="text" @click="queue.reset">清空清单</a-button></div>
        <a-table v-if="entries.length" :data="entries" row-key="id" :pagination="{ pageSize: 20 }" :bordered="false" :scroll="{ x: 720 }">
          <template #columns>
            <a-table-column title="文件" :width="280"><template #cell="{ record }"><strong>{{ record.file.name }}</strong><span class="cell-subtitle">{{ formatBytes(record.file.size) }}</span></template></a-table-column>
            <a-table-column title="上传进度"><template #cell="{ record }"><a-progress :percent="record.progress / 100" :status="record.status === 'failed' ? 'danger' : 'normal'" /></template></a-table-column>
            <a-table-column title="状态"><template #cell="{ record }"><a-tag :color="record.status === 'failed' ? 'red' : record.status === 'uploaded' ? 'green' : 'gray'">{{ statuses[record.status as keyof typeof statuses] }}</a-tag><span v-if="record.error" class="cell-subtitle">{{ record.error }}</span></template></a-table-column>
            <a-table-column title="操作" :width="80"><template #cell="{ record }"><a-button v-if="record.status !== 'uploaded'" type="text" :disabled="uploading" @click="entries = entries.filter((item) => item.id !== record.id)">移除</a-button></template></a-table-column>
          </template>
        </a-table>
        <div class="upload-actions"><a-button type="primary" html-type="submit" :loading="uploading" :disabled="!entries.some((entry) => entry.status !== 'uploaded')"><Upload :size="16" />{{ failed.length ? '重试失败项并上传' : '开始上传' }}</a-button><span class="muted-text">同时上传 {{ limits.upload_concurrency }} 个文件，其余自动排队。</span></div>
      </a-form>
    </a-card>
    <a-modal v-model:visible="finished" :title="failed.length ? '本次上传已结束' : '上传完成'" :footer="false" :mask-closable="false" :closable="false" :esc-to-close="false" width="480px">
      <p>已上传 {{ successful.length }} 个文件，{{ failed.length }} 个上传失败。已上传文件正在后台解析，完成后可用于问答。</p>
      <a-alert v-if="error" type="warning">{{ error.message }}</a-alert>
      <div class="modal-actions"><a-button @click="continueUploading">继续上传</a-button><a-button type="primary" @click="viewProgress">查看处理进度</a-button></div>
    </a-modal>
  </div>
</template>

<style scoped>
.upload-metadata-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }
.upload-dropzone { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 28px 16px; color: var(--color-text-2); }
.upload-dropzone strong { color: var(--color-text-1); }
.upload-summary { margin-top: 20px; }
.upload-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; margin-top: 20px; }
@media (max-width: 640px) { .upload-metadata-grid { grid-template-columns: 1fr; } }
</style>
