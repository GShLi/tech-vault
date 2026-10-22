import { computed, ref, type Ref } from 'vue'
import type { ModelProvider } from '@/types/api'

/** Shared eligibility policy for chat and evaluation model pickers. */
export function useProviderSelection(
  providers: Ref<ModelProvider[]>,
  allowedProviderIds: Ref<string[]>,
) {
  const selectedProviderId = ref('')
  const selectedModelId = ref('')
  const eligibleProviders = computed(() => {
    const allowedIds = new Set(allowedProviderIds.value)
    return providers.value.filter(
      (provider) =>
        provider.status === 'active' &&
        provider.has_api_key === true &&
        allowedIds.has(provider.id) &&
        Array.isArray(provider.model_ids) &&
        provider.model_ids.length > 0,
    )
  })

  const selectedProvider = computed(
    () =>
      eligibleProviders.value.find(
        (provider) => provider.id === selectedProviderId.value,
      ) ?? null,
  )

  const modelOptions = computed(() =>
    Array.isArray(selectedProvider.value?.model_ids)
      ? (selectedProvider.value?.model_ids ?? [])
      : [],
  )

  const hasProviderAndModel = computed(
    () =>
      Boolean(selectedProvider.value) &&
      Boolean(selectedModelId.value) &&
      modelOptions.value.includes(selectedModelId.value),
  )

  return {
    selectedProviderId,
    selectedModelId,
    eligibleProviders,
    selectedProvider,
    modelOptions,
    hasProviderAndModel,
  }
}
