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

vi.mock('@arco-design/web-vue', () => ({ Message: messageMocks }))

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

  it('offers the three supported upstream formats', () => {
    const wrapper = mount(ProviderCreateForm, {
      props: { teamId: 'team-1', canManage: true },
    })
    const options = wrapper.get('[data-testid="provider-type"]').findAll('option')

    expect(options.map((option) => option.attributes('value'))).toEqual([
      'openai_responses',
      'openai_chat_completions',
      'anthropic_messages',
    ])
    expect(options.map((option) => option.text())).toEqual([
      'OpenAI Responses',
      'OpenAI Chat Completions',
      'Anthropic Messages',
    ])
  })

  it('discovers models from the submitted base url and api key', async () => {
    const wrapper = mount(ProviderCreateForm, {
      props: { teamId: 'team-1', canManage: true },
    })

    await wrapper.get('[data-testid="provider-name"]').setValue('Gateway')
    await wrapper
      .get('[data-testid="provider-type"]')
      .setValue('openai_chat_completions')
    await wrapper
      .get('[data-testid="provider-base-url"]')
      .setValue('https://gateway.example/v1/chat/completions')
    await wrapper.get('[data-testid="provider-api-key"]').setValue('sk-secret')
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

    await wrapper.get('[data-testid="provider-name"]').setValue('Gateway')
    await wrapper
      .get('[data-testid="provider-base-url"]')
      .setValue('https://gateway.example/v1')
    await wrapper.get('[data-testid="provider-api-key"]').setValue('sk-secret')
    await wrapper.get('[data-testid="provider-fetch-models"]').trigger('click')
    await flushPromises()
    await wrapper
      .get('[data-testid="provider-model-gpt-b"]')
      .setValue(false)
    await wrapper
      .get('[data-testid="provider-manual-models"]')
      .setValue('manual-model')
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
