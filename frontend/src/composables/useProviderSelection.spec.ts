import { ref } from 'vue'
import type { ModelProvider } from '@/types/api'
import { useProviderSelection } from './useProviderSelection'

it('restricts models to active configured providers allowed by policy', () => {
  const provider = (id: string, overrides = {}): ModelProvider =>
    ({
      id,
      status: 'active',
      has_api_key: true,
      model_ids: ['model-a'],
      ...overrides,
    }) as ModelProvider
  const providers = ref([
    provider('allowed'),
    provider('unapproved'),
    provider('disabled', { status: 'disabled' }),
    provider('empty', { model_ids: [] }),
    provider('no-key', { has_api_key: false }),
  ])
  const allowed = ref(['allowed', 'disabled', 'empty', 'no-key'])
  const selection = useProviderSelection(providers, allowed)
  expect(selection.eligibleProviders.value.map((item) => item.id)).toEqual([
    'allowed',
  ])
  selection.selectedProviderId.value = 'allowed'
  selection.selectedModelId.value = 'model-a'
  expect(selection.hasProviderAndModel.value).toBe(true)
  selection.selectedModelId.value = 'unknown'
  expect(selection.hasProviderAndModel.value).toBe(false)
  allowed.value = []
  expect(selection.modelOptions.value).toEqual([])
  expect(selection.hasProviderAndModel.value).toBe(false)
})
