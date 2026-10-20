<script setup lang="ts">
import { computed, ref } from 'vue'
import { ListPlus, Plus } from 'lucide-vue-next'
import { Message } from '@arco-design/web-vue'

import { api, ApiRequestError } from '@/api/client'
import type { ProviderModelsInput, ProviderType } from '@/types/api'
import { parseLines } from '@/utils/format'
import { providerTypeOptions } from '@/utils/providers'

const props = withDefaults(
  defineProps<{
    admin?: boolean
    teamId?: string | null
    canManage?: boolean
  }>(),
  {
    admin: false,
    teamId: null,
    canManage: true,
  },
)

const emit = defineEmits<{ created: [] }>()

const name = ref('')
const providerType = ref<ProviderType>('openai_chat_completions')
const baseUrl = ref('')
const apiKey = ref('')
const availableModels = ref<string[]>([])
const selectedModels = ref<string[]>([])
const manualModels = ref('')
const fetchingModels = ref(false)
const saving = ref(false)
const error = ref<ApiRequestError | null>(null)

const canCreate = computed(() => props.admin || (Boolean(props.teamId) && props.canManage))
const canFetchModels = computed(
  () => canCreate.value && Boolean(baseUrl.value.trim()) && Boolean(apiKey.value.trim()),
)
const effectiveModelIds = computed(() =>
  Array.from(
    new Set([...selectedModels.value, ...parseLines(manualModels.value)]),
  ),
)

function modelInput(): ProviderModelsInput {
  return {
    provider_type: providerType.value,
    base_url: baseUrl.value.trim(),
    api_key: apiKey.value.trim(),
  }
}

function resetModels(): void {
  availableModels.value = []
  selectedModels.value = []
  manualModels.value = ''
}

async function fetchModels(): Promise<void> {
  if (!canFetchModels.value) return
  fetchingModels.value = true
  error.value = null
  try {
    const result = props.admin
      ? await api.discoverAdminProviderModels(modelInput())
      : await api.discoverProviderModels(props.teamId as string, modelInput())
    availableModels.value = result.models
    selectedModels.value = [...result.models]
    if (!result.models.length) {
      Message.warning('上游未返回模型，可继续手动填写模型 ID')
    }
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
    Message.error('获取模型列表失败，可手动填写模型 ID')
  } finally {
    fetchingModels.value = false
  }
}

function selectAllModels(): void {
  selectedModels.value = [...availableModels.value]
}

function clearSelectedModels(): void {
  selectedModels.value = []
}

async function createProvider(): Promise<void> {
  if (!canCreate.value || !effectiveModelIds.value.length) return
  saving.value = true
  error.value = null
  const payload = {
    name: name.value.trim(),
    provider_type: providerType.value,
    base_url: baseUrl.value.trim(),
    api_key: apiKey.value.trim(),
    model_ids: effectiveModelIds.value,
  }
  try {
    if (props.admin) {
      await api.createAdminProvider(payload)
    } else {
      await api.createProvider({ team_id: props.teamId as string, ...payload })
    }
    Message.success('供应商已创建')
    name.value = ''
    baseUrl.value = ''
    apiKey.value = ''
    resetModels()
    emit('created')
  } catch (caught) {
    error.value = caught instanceof ApiRequestError ? caught : null
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="provider-create-form">
    <div class="section-heading">
      <h3>{{ admin ? '新增平台供应商' : '添加团队供应商' }}</h3>
      <ListPlus :size="16" />
    </div>
    <div v-if="error" class="error-banner" role="alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </div>
    <form class="form-stack" data-testid="provider-create" @submit.prevent="createProvider">
      <label class="field">
        <span>名称</span>
        <input v-model="name" data-testid="provider-name" type="text" required />
      </label>
      <label class="field">
        <span>上游格式</span>
        <select v-model="providerType" data-testid="provider-type" @change="resetModels">
          <option
            v-for="option in providerTypeOptions"
            :key="option.value"
            :value="option.value"
          >{{ option.label }}</option>
        </select>
      </label>
      <label class="field">
        <span>Base URL</span>
        <input
          v-model="baseUrl"
          data-testid="provider-base-url"
          type="url"
          required
          placeholder="https://api.example.com/v1"
        />
      </label>
      <label class="field">
        <span>API Key</span>
        <input
          v-model="apiKey"
          data-testid="provider-api-key"
          type="password"
          required
          autocomplete="new-password"
          placeholder="只写不读，保存后仅显示掩码"
        />
      </label>

      <div class="model-discovery-actions">
        <button
          class="secondary-button"
          type="button"
          data-testid="provider-fetch-models"
          :disabled="fetchingModels || !canFetchModels"
          @click="fetchModels"
        >
          <ListPlus :size="15" />{{ fetchingModels ? '获取中' : '获取模型' }}
        </button>
        <span class="muted-text">从当前 Base URL 读取上游模型列表</span>
      </div>

      <div v-if="availableModels.length" class="model-choice-panel">
        <div class="model-choice-heading">
          <strong>可用模型</strong>
          <div class="row-actions">
            <button class="inline-link" type="button" @click="selectAllModels">全选</button>
            <button class="inline-link" type="button" @click="clearSelectedModels">清空</button>
          </div>
        </div>
        <div class="model-choice-grid">
          <label v-for="model in availableModels" :key="model" class="model-choice">
            <input
              v-model="selectedModels"
              type="checkbox"
              :value="model"
              :data-testid="`provider-model-${model}`"
            />
            <span>{{ model }}</span>
          </label>
        </div>
      </div>

      <label class="field">
        <span>补充模型 ID（逗号或换行）</span>
        <textarea
          v-model="manualModels"
          data-testid="provider-manual-models"
          rows="2"
          placeholder="上游不支持模型列表时，可在这里手动填写"
        />
      </label>

      <button
        class="primary-button"
        type="submit"
        :disabled="saving || !canCreate || !effectiveModelIds.length"
      >
        <Plus :size="16" />{{ saving ? '创建中' : '创建供应商' }}
      </button>
    </form>
  </div>
</template>
