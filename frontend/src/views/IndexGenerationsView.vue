<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { CheckCircle2, DatabaseZap, Play, RefreshCcw, RotateCcw, ShieldCheck } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import { useTeamStore } from '@/stores/team'
import type { GenerationReindexResult, GenerationValidation, IndexGeneration } from '@/types/api'
import { formatDate, shortId } from '@/utils/format'

const team = useTeamStore()
const items = ref<IndexGeneration[]>([])
const loading = ref(false)
const actionId = ref('')
const error = ref<ApiRequestError | null>(null)
const nextCursor = ref<string | null>(null)
const hasMore = ref(false)
const validation = ref<GenerationValidation | null>(null)
const validationGeneration = ref('')
const reindexResult = ref<GenerationReindexResult | null>(null)

async function load(reset = true): Promise<void> {
  if (!team.selectedTeamId) return
  loading.value = true
  error.value = null
  try {
    const page = await api.listGenerations(team.selectedTeamId, reset ? null : nextCursor.value)
    items.value = reset ? page.data : [...items.value, ...page.data]
    nextCursor.value = page.meta.next_cursor
    hasMore.value = page.meta.has_more
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function runAction(action: 'validate' | 'activate', item: IndexGeneration): Promise<void> {
  if (!team.selectedTeamId) return
  actionId.value = item.id
  error.value = null
  try {
    if (action === 'validate') {
      const result = await api.validateGeneration(team.selectedTeamId, item.id)
      validation.value = result
      validationGeneration.value = item.id
      if (result.passed) Message.success('Generation 校验通过')
      else Message.error('Generation 校验失败')
    } else {
      await api.activateGeneration(team.selectedTeamId, item.id)
      Message.success('Generation 已激活')
    }
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    actionId.value = ''
  }
}

async function rollback(): Promise<void> {
  if (!team.selectedTeamId) return
  actionId.value = 'rollback'
  error.value = null
  try {
    await api.rollbackGeneration(team.selectedTeamId)
    Message.success('已回滚到上一个已验证 Generation')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    actionId.value = ''
  }
}

async function startReindex(): Promise<void> {
  if (!team.selectedTeamId) return
  actionId.value = 'reindex'
  error.value = null
  try {
    const result = await api.reindexGeneration(team.selectedTeamId)
    reindexResult.value = result
    if (result.run.status === 'queued') Message.success('全量重建任务已排队')
    else if (result.run.status === 'failed') Message.error('全量重建失败')
    else Message.success('全量重建已完成')
    await load()
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    actionId.value = ''
  }
}

async function showValidation(item: IndexGeneration): Promise<void> {
  if (!team.selectedTeamId) return
  try {
    validation.value = await api.getGenerationValidation(team.selectedTeamId, item.id)
    validationGeneration.value = item.id
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  }
}

onMounted(load)
watch(() => team.selectedTeamId, () => load())
</script>

<template>
  <div>
    <div class="page-header"><div><h2>索引 Generation</h2><p>全量重建、验证、激活和回滚团队检索索引版本。</p></div><div class="row-actions"><button class="secondary-button" type="button" :disabled="loading" @click="load()"><RefreshCcw :size="16" />刷新</button><button v-if="team.canManage" class="secondary-button" type="button" data-testid="generation-reindex" :disabled="loading || actionId === 'reindex'" @click="startReindex"><Play :size="16" />全量重建</button><button v-if="team.canManage" class="secondary-button" type="button" :disabled="actionId === 'rollback'" @click="rollback"><RotateCcw :size="16" />回滚</button></div></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span><button class="inline-link" type="button" @click="load()">重试</button></div>
    <div v-if="reindexResult" class="notice-box" data-testid="generation-reindex-status"><strong>Generation {{ shortId(reindexResult.generation.id) }}</strong><span>运行状态：{{ reindexResult.run.status }} · {{ reindexResult.run.execution_mode }} · 检查 Chunk {{ reindexResult.run.checked_chunks }}</span></div>
    <div v-if="loading && !items.length" class="panel loading-state"><a-spin /><span>正在加载索引版本</span></div>
    <div v-else-if="!items.length" class="panel empty-state"><DatabaseZap :size="28" /><h3>暂无索引 Generation</h3><p>文档入库后会创建可验证的索引版本。</p></div>
    <div v-else class="panel">
      <div class="table-wrap"><table><thead><tr><th>Generation</th><th>状态</th><th>Chunk</th><th>Embedding 模型</th><th>校验/激活时间</th><th class="actions-column">操作</th></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td data-label="Generation"><strong>{{ shortId(item.id) }}</strong><span class="cell-subtitle">{{ formatDate(item.created_at) }}</span></td><td data-label="状态"><StatusPill :status="item.status" /></td><td data-label="Chunk">{{ item.chunk_count }}</td><td data-label="Embedding 模型">{{ item.embedding_model }}</td><td data-label="校验/激活时间">{{ formatDate(item.activated_at || item.validated_at) }}</td><td data-label="操作"><div class="row-actions"><button class="ghost-button" type="button" @click="showValidation(item)"><ShieldCheck :size="14" />校验结果</button><button v-if="team.canManage && item.status !== 'active'" class="ghost-button" type="button" :disabled="actionId === item.id" @click="runAction(item.status === 'validated' ? 'activate' : 'validate', item)"><CheckCircle2 :size="14" />{{ item.status === 'validated' ? '激活' : '验证' }}</button></div></td></tr></tbody></table></div>
      <div v-if="hasMore" class="load-more"><button class="secondary-button" type="button" :disabled="loading" @click="load(false)">加载更多</button></div>
    </div>
    <div v-if="validation" class="modal-backdrop" @click.self="validation = null"><div class="modal-panel"><div class="modal-heading"><div><h3>Generation 校验</h3><span class="cell-subtitle">{{ validationGeneration }}</span></div><button class="icon-button" type="button" @click="validation = null">×</button></div><div class="detail-grid"><div><dt>结果</dt><dd>{{ validation.passed ? '通过' : '失败' }}</dd></div><div><dt>检查 Chunk</dt><dd>{{ validation.checked_chunks }}</dd></div><div><dt>校验时间</dt><dd>{{ formatDate(validation.validated_at) }}</dd></div></div><div v-if="validation.errors.length" class="error-banner" role="alert"><strong>校验错误</strong><span v-for="item in validation.errors" :key="item">{{ item }}</span></div><div v-else class="notice-box"><strong>所有检查已通过</strong><span>该索引可以激活。</span></div></div></div>
  </div>
</template>
