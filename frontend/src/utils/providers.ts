import type { ProviderType } from '@/types/api'

export const providerTypeOptions: Array<{ value: ProviderType; label: string }> = [
  { value: 'openai_responses', label: 'OpenAI Responses' },
  { value: 'openai_chat_completions', label: 'OpenAI Chat Completions' },
  { value: 'anthropic_messages', label: 'Anthropic Messages' },
]

export function providerTypeLabel(value?: string | null): string {
  return providerTypeOptions.find((item) => item.value === value)?.label ?? value ?? '—'
}
