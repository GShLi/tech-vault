<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Save, ShieldCheck } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import StatusPill from '@/components/StatusPill.vue'
import type { ModelPolicy } from '@/types/api'
import { statusLabel } from '@/utils/format'

const policy = ref<ModelPolicy | null>(null)
const mode = ref('local_only')
const maxClassification = ref('internal')
const loading = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    policy.value = await api.getAdminPolicy()
    mode.value = policy.value.mode
    maxClassification.value = policy.value.max_data_classification
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    policy.value = await api.updateAdminPolicy({
      mode: mode.value,
      max_data_classification: maxClassification.value,
      allowed_provider_ids: policy.value?.allowed_provider_ids ?? [],
    })
    Message.success('平台模型策略已更新')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header"><div><h2>全局模型策略</h2><p>平台级模型调用上限，团队策略只能在其范围内收紧。</p></div><StatusPill v-if="policy" :status="policy.mode" /></div>
    <div v-if="error" class="error-banner" role="alert"><strong>{{ error.message }}</strong><span v-if="error.requestId">请求 ID：{{ error.requestId }}</span></div>
    <div v-if="loading && !policy" class="panel loading-state"><a-spin /><span>正在加载平台策略</span></div>
    <section v-else class="panel detail-panel narrow-panel">
      <div class="detail-heading"><div class="detail-icon"><ShieldCheck :size="20" /></div><div><h3>策略默认值</h3><p>当前模式：{{ statusLabel(policy?.mode) }}</p></div></div>
      <form class="form-stack" @submit.prevent="save">
        <label class="field"><span>平台模式</span><select v-model="mode"><option value="local_only">仅本地模型</option><option value="external_allowed">允许外部模型</option><option value="external_required">仅外部模型</option></select></label>
        <label class="field"><span>允许的最大数据分类</span><select v-model="maxClassification"><option value="public">公开</option><option value="internal">内部</option><option value="private">私有</option><option value="restricted">受限</option></select></label>
        <button class="primary-button" type="submit" :disabled="saving"><Save :size="16" />{{ saving ? '保存中' : '保存平台策略' }}</button>
      </form>
    </section>
  </div>
</template>
