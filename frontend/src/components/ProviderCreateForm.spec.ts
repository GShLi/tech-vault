import { control, setControlValue, selectOptions } from '@/test/arco'
import { flushPromises, mount } from '@vue/test-utils'

import ProviderCreateForm from './ProviderCreateForm.vue'

const apiMocks = vi.hoisted(() => ({
  createAdminProvider: vi.fn(),
  createProvider: vi.fn(),
  discoverAdminProviderModels: vi.fn(),
  discoverProviderModels: vi.fn(),
}))

const messageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('@arco-design/web-vue', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@arco-design/web-vue')>()),
  Message: messageMocks,
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      ...apiMocks,
    },
  }
})

describe('ProviderCreateForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.discoverProviderModels.mockResolvedValue({
      provider_type: 'openai_chat_completions',
      models: ['gpt-a', 'gpt-b'],
    })
    apiMocks.createProvider.mockResolvedValue({ id: 'provider-1' })
  })

  it('offers the three supported upstream formats', async () => {
    const wrapper = mount(ProviderCreateForm, {
      props: { teamId: 'team-1', canManage: true },
    })
    const options = await selectOptions(
      control(wrapper, '[data-testid="provider-type"]'),
    )

    expect(options.map((option) => option.value)).toEqual([
      'openai_responses',
      'openai_chat_completions',
      'anthropic_messages',
    ])
    expect(options.map((option) => option.label)).toEqual([
      'OpenAI Responses',
      'OpenAI Chat Completions',
      'Anthropic Messages',
    ])
  })

  it('discovers models from the submitted base url and api key', async () => {
    const wrapper = mount(ProviderCreateForm, {
      props: { teamId: 'team-1', canManage: true },
    })

    await setControlValue(
      control(wrapper, '[data-testid="provider-name"]'),
      'Gateway',
    )
    await setControlValue(
      control(wrapper, '[data-testid="provider-type"]'),
      'openai_chat_completions',
    )
    await setControlValue(
      control(wrapper, '[data-testid="provider-base-url"]'),
      'https://gateway.example/v1/chat/completions',
    )
    await setControlValue(
      control(wrapper, '[data-testid="provider-api-key"]'),
      'sk-secret',
    )
    await wrapper.get('[data-testid="provider-fetch-models"]').trigger('click')
    await flushPromises()

    expect(apiMocks.discoverProviderModels).toHaveBeenCalledWith('team-1', {
      provider_type: 'openai_chat_completions',
      base_url: 'https://gateway.example/v1/chat/completions',
      api_key: 'sk-secret',
    })
    expect(wrapper.text()).toContain('gpt-a')
    expect(wrapper.text()).toContain('gpt-b')
  })

  it('creates a provider with the selected and manually entered models', async () => {
    const wrapper = mount(ProviderCreateForm, {
      props: { teamId: 'team-1', canManage: true },
    })

    await setControlValue(
      control(wrapper, '[data-testid="provider-name"]'),
      'Gateway',
    )
    await setControlValue(
      control(wrapper, '[data-testid="provider-base-url"]'),
      'https://gateway.example/v1',
    )
    await setControlValue(
      control(wrapper, '[data-testid="provider-api-key"]'),
      'sk-secret',
    )
    await wrapper.get('[data-testid="provider-fetch-models"]').trigger('click')
    await flushPromises()
    await setControlValue(
      control(wrapper, '[data-testid="provider-model-gpt-b"]'),
      false,
    )
    await setControlValue(
      control(wrapper, '[data-testid="provider-manual-models"]'),
      'manual-model',
    )
    await wrapper.get('[data-testid="provider-create"]').trigger('submit')
    await flushPromises()

    expect(apiMocks.createProvider).toHaveBeenCalledWith({
      team_id: 'team-1',
      name: 'Gateway',
      provider_type: 'openai_chat_completions',
      base_url: 'https://gateway.example/v1',
      api_key: 'sk-secret',
      model_ids: ['gpt-a', 'manual-model'],
    })
  })
})
