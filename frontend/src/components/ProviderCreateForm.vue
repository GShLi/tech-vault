<script setup lang="ts">
import { ApiRequestError, api, normalizeApiError } from '@/api/client'
import {
  Alert as AAlert,
  Button as AButton,
  Checkbox as ACheckbox,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  InputPassword as AInputPassword,
  Message,
  Option as AOption,
  Select as ASelect,
  Textarea as ATextarea,
} from '@arco-design/web-vue'
import { computed, ref } from 'vue'
import { ListPlus, Plus } from 'lucide-vue-next'

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

const canCreate = computed(
  () => props.admin || (Boolean(props.teamId) && props.canManage),
)
const canFetchModels = computed(
  () =>
    canCreate.value &&
    Boolean(baseUrl.value.trim()) &&
    Boolean(apiKey.value.trim()),
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
    error.value = normalizeApiError(caught)
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
    error.value = normalizeApiError(caught)
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
    <a-alert v-if="error" type="error" class="page-alert">
      <strong>{{ error.message }}</strong>
      <span v-if="error.requestId">请求 ID：{{ error.requestId }}</span>
    </a-alert>
    <a-form
      class="form-stack"
      data-testid="provider-create"
      :model="{
        name,
        providerType,
        baseUrl,
        apiKey,
        selectedModels,
        manualModels,
      }"
      layout="vertical"
      @submit-success="createProvider"
    >
      <a-form-item
        field="name"
        :rules="[{ required: true, message: '请填写名称' }]"
        :validate-trigger="['change', 'blur']"
      >
        <template #label>名称</template>
        <a-input
          v-model="name"
          data-testid="provider-name"
          type="text"
          :input-attrs="{ required: true }"
        ></a-input>
      </a-form-item>
      <a-form-item field="providerType">
        <template #label>上游格式</template>
        <a-select
          v-model="providerType"
          data-testid="provider-type"
          @change="resetModels"
        >
          <a-option
            v-for="option in providerTypeOptions"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </a-option>
        </a-select>
      </a-form-item>
      <a-form-item
        field="baseUrl"
        :rules="[
          { required: true, message: '请填写Base URL' },
          { type: 'url', message: '请输入有效的 URL' },
        ]"
        :validate-trigger="['change', 'blur']"
      >
        <template #label>Base URL</template>
        <a-input
          v-model="baseUrl"
          data-testid="provider-base-url"
          placeholder="https://api.example.com/v1"
          type="text"
          :input-attrs="{ required: true }"
        ></a-input>
      </a-form-item>
      <a-form-item
        field="apiKey"
        :rules="[{ required: true, message: '请填写API Key' }]"
        :validate-trigger="['change', 'blur']"
      >
        <template #label>API Key</template>
        <a-input-password
          v-model="apiKey"
          data-testid="provider-api-key"
          placeholder="只写不读，保存后仅显示掩码"
          :input-attrs="{ required: true, autocomplete: 'new-password' }"
        ></a-input-password>
      </a-form-item>
      <div class="model-discovery-actions">
        <a-button
          data-testid="provider-fetch-models"
          :disabled="fetchingModels || !canFetchModels"
          @click="fetchModels"
          type="secondary"
          html-type="button"
        >
          <ListPlus :size="15" />
          {{ fetchingModels ? '获取中' : '获取模型' }}
        </a-button>
        <span class="muted-text">从当前 Base URL 读取上游模型列表</span>
      </div>
      <div v-if="availableModels.length" class="model-choice-panel">
        <div class="model-choice-heading">
          <strong>可用模型</strong>
          <div class="row-actions">
            <a-button @click="selectAllModels" type="text" html-type="button">
              全选
            </a-button>
            <a-button
              @click="clearSelectedModels"
              type="text"
              html-type="button"
            >
              清空
            </a-button>
          </div>
        </div>
        <div class="model-choice-grid">
          <a-checkbox
            v-for="model in availableModels"
            :key="model"
            class="model-choice"
            v-model="selectedModels"
            :value="model"
            :data-testid="`provider-model-${model}`"
          >
            <span>{{ model }}</span>
          </a-checkbox>
        </div>
      </div>
      <a-form-item field="manualModels">
        <template #label>补充模型 ID（逗号或换行）</template>
        <a-textarea
          v-model="manualModels"
          data-testid="provider-manual-models"
          placeholder="上游不支持模型列表时，可在这里手动填写"
          :textarea-attrs="{ rows: '2' }"
        ></a-textarea>
      </a-form-item>
      <a-button
        :disabled="saving || !canCreate || !effectiveModelIds.length"
        type="primary"
        html-type="submit"
      >
        <Plus :size="16" />
        {{ saving ? '创建中' : '创建供应商' }}
      </a-button>
    </a-form>
  </div>
</template>
