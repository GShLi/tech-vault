import { flushPromises, mount } from '@vue/test-utils'

import type { ModelPolicy, ModelProvider } from '@/types/api'
import AdminPolicyView from './AdminPolicyView.vue'

const apiMocks = vi.hoisted(() => ({
  getAdminPolicy: vi.fn(),
  listAdminProviders: vi.fn(),
  updateAdminPolicy: vi.fn(),
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

const adminPolicy: ModelPolicy = {
  mode: 'external_allowed',
  allowed_provider_ids: ['provider-openai'],
  max_data_classification: 'restricted',
  allow_chat_history: false,
  allow_document_metadata: false,
  require_redaction: true,
  version: 3,
}

const openAiProvider: ModelProvider = {
  id: 'provider-openai',
  name: 'OpenAI Primary',
  provider_type: 'openai_responses',
  base_url: 'https://api.openai.com/v1',
  model_ids: ['gpt-4.1', 'gpt-4.1-mini'],
  status: 'active',
  has_api_key: true,
  api_key_masked: '****1234',
  api_key_updated_at: '2026-10-19T12:00:00+00:00',
}

const anthropicProvider: ModelProvider = {
  id: 'provider-anthropic',
  name: 'Anthropic Backup',
  provider_type: 'anthropic_messages',
  base_url: 'https://api.anthropic.com',
  model_ids: ['claude-sonnet-4-20250514'],
  status: 'disabled',
  has_api_key: false,
  api_key_masked: '',
  api_key_updated_at: null,
}

function page(data: ModelProvider[], nextCursor: string | null = null) {
  return {
    data,
    meta: {
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
      request_id: 'req-admin-providers',
    },
  }
}

async function mountPage() {
  const wrapper = mount(AdminPolicyView, {
    global: {
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="String(to)"><slot /></a>',
        },
        ASpin: { template: '<span />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('AdminPolicyView provider admission', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getAdminPolicy.mockResolvedValue(adminPolicy)
    apiMocks.listAdminProviders.mockResolvedValue(page([openAiProvider]))
    apiMocks.updateAdminPolicy.mockResolvedValue(adminPolicy)
  })

  it('loads every provider page and renders identity, status, models, and API key availability', async () => {
    apiMocks.listAdminProviders
      .mockResolvedValueOnce(page([openAiProvider], 'cursor-providers'))
      .mockResolvedValueOnce(page([anthropicProvider]))

    const wrapper = await mountPage()

    expect(apiMocks.listAdminProviders).toHaveBeenNthCalledWith(1, null, 100)
    expect(apiMocks.listAdminProviders).toHaveBeenNthCalledWith(
      2,
      'cursor-providers',
      100,
    )
    expect(wrapper.text()).toContain('OpenAI Primary')
    expect(wrapper.text()).toContain('OpenAI Responses')
    expect(wrapper.text()).toContain('启用')
    expect(wrapper.text()).toContain('gpt-4.1-mini')
    expect(wrapper.text()).toContain('****1234')
    expect(wrapper.text()).toContain('API Key 可用')
    expect(wrapper.text()).toContain('Anthropic Backup')
    expect(wrapper.text()).toContain('Anthropic Messages')
    expect(wrapper.text()).toContain('已禁用')
    expect(wrapper.text()).toContain('claude-sonnet-4-20250514')
    expect(wrapper.text()).toContain('API Key 不可用')
  })

  it('saves the complete selected provider ID array after selecting an unselected provider', async () => {
    apiMocks.listAdminProviders.mockResolvedValue(
      page([openAiProvider, anthropicProvider]),
    )
    const wrapper = await mountPage()
    const providerCheckbox = wrapper.get(
      '[data-testid="provider-admission-provider-anthropic"] input[type="checkbox"]',
    )

    expect((providerCheckbox.element as HTMLInputElement).checked).toBe(false)
    await providerCheckbox.setValue(true)
    expect((providerCheckbox.element as HTMLInputElement).checked).toBe(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(apiMocks.updateAdminPolicy).toHaveBeenCalledWith({
      mode: 'external_allowed',
      max_data_classification: 'restricted',
      allowed_provider_ids: ['provider-openai', 'provider-anthropic'],
    })
  })

  it('links to provider management when the platform has no providers', async () => {
    apiMocks.listAdminProviders.mockResolvedValue(page([]))

    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('暂无平台供应商')
    expect(wrapper.find('a[href="/admin/model-providers"]').exists()).toBe(true)
  })

  it('keeps provider selections editable in local-only mode and explains that external calls are disabled', async () => {
    apiMocks.getAdminPolicy.mockResolvedValue({
      ...adminPolicy,
      mode: 'local_only',
      allowed_provider_ids: [],
    })
    apiMocks.listAdminProviders.mockResolvedValue(page([openAiProvider]))

    const wrapper = await mountPage()
    const providerCheckbox = wrapper.get(
      '[data-testid="provider-admission-provider-openai"] input[type="checkbox"]',
    )

    expect(wrapper.text()).toContain('外部模型调用当前已禁用')
    expect(providerCheckbox.attributes('disabled')).toBeUndefined()
  })
})
