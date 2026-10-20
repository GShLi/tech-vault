import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type {
  ChatView,
  KnowledgeBase,
  MessageView,
  ModelPolicy,
  ModelProvider,
} from '@/types/api'
import ChatPage from './ChatPage.vue'

const apiMocks = vi.hoisted(() => ({
  cancelMessage: vi.fn(),
  createChat: vi.fn(),
  deleteChat: vi.fn(),
  getPolicy: vi.fn(),
  listChats: vi.fn(),
  listFacets: vi.fn(),
  listKbs: vi.fn(),
  listMessages: vi.fn(),
  listProviders: vi.fn(),
  submitFeedback: vi.fn(),
  updateChat: vi.fn(),
}))

const messageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}))

vi.mock('@arco-design/web-vue', () => ({
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
    getAccessToken: vi.fn().mockReturnValue('access-token'),
  }
})

const chat: ChatView = {
  id: 'chat-1',
  team_id: 'team-1',
  user_id: 'user-1',
  title: 'Spring 问题',
  knowledge_base_ids: ['kb-1'],
  version: 1,
  created_at: '2026-10-19T12:00:00+00:00',
  updated_at: '2026-10-19T12:00:00+00:00',
}

const knowledgeBase: KnowledgeBase = {
  id: 'kb-1',
  team_id: 'team-1',
  name: 'Java 资料',
  description: null,
  status: 'active',
  default_model_policy_mode: 'local_only',
  document_count: 4,
  version: 1,
  created_at: '2026-10-19T12:00:00+00:00',
  updated_at: '2026-10-19T12:00:00+00:00',
}

const modelPolicy: ModelPolicy = {
  mode: 'external_allowed',
  allowed_provider_ids: [
    'provider-1',
    'provider-2',
    'provider-empty-models',
  ],
  max_data_classification: 'internal',
  allow_chat_history: true,
  allow_document_metadata: true,
  require_redaction: false,
  version: 1,
}

const providers: ModelProvider[] = [
  {
    id: 'provider-1',
    name: 'Provider One',
    provider_type: 'openai_responses',
    base_url: 'https://provider-one.example/v1',
    model_ids: ['gpt-a', 'gpt-b'],
    status: 'active',
    has_api_key: true,
  },
  {
    id: 'provider-2',
    name: 'Provider Two',
    provider_type: 'anthropic_messages',
    model_ids: ['claude-a'],
    status: 'active',
    has_api_key: true,
  },
  {
    id: 'provider-no-key',
    name: 'Provider Without Key',
    provider_type: 'openai_chat_completions',
    model_ids: ['no-key-model'],
    status: 'active',
    has_api_key: false,
  },
  {
    id: 'provider-disabled',
    name: 'Disabled Provider',
    provider_type: 'openai_chat_completions',
    model_ids: ['disabled-model'],
    status: 'disabled',
    has_api_key: true,
  },
  {
    id: 'provider-not-allowed',
    name: 'Policy Blocked Provider',
    provider_type: 'openai_chat_completions',
    model_ids: ['blocked-model'],
    status: 'active',
    has_api_key: true,
  },
  {
    id: 'provider-empty-models',
    name: 'Provider Without Models',
    provider_type: 'openai_chat_completions',
    model_ids: [],
    status: 'active',
    has_api_key: true,
  },
]

const userMessage: MessageView = {
  id: 'message-user',
  chat_id: 'chat-1',
  role: 'user',
  content: '虚拟线程如何配置？',
  status: 'completed',
  trace_id: null,
  citation_ids: [],
  refusal_reason: null,
  created_at: '2026-10-19T12:00:00+00:00',
}

const assistantMessage: MessageView = {
  id: 'message-assistant-history',
  chat_id: 'chat-1',
  role: 'assistant',
  content: '启用 spring.threads.virtual.enabled 即可。',
  status: 'completed',
  trace_id: 'trace-history',
  citation_ids: [],
  refusal_reason: null,
  created_at: '2026-10-19T12:01:00+00:00',
}

function messagePage(
  data: MessageView[] = [],
  nextCursor: string | null = null,
) {
  return {
    data,
    meta: {
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
      request_id: 'req-messages',
    },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function makePinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = {
    user: {
      id: 'user-1',
      email: 'member@example.com',
      display_name: 'Member',
      status: 'active',
      is_super_admin: false,
      is_builtin: false,
      created_at: '2026-10-19T12:00:00+00:00',
    },
    memberships: [
      {
        team_id: 'team-1',
        team_name: 'Platform',
        role: 'member',
        status: 'active',
      },
    ],
  }
  const team = useTeamStore()
  team.selectTeam('team-1')
  return pinia
}

function sseResponse(events: Array<{ event: string; data: unknown }>) {
  const encoder = new TextEncoder()
  const chunks = events.map(
    ({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
  )
  let index = 0
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'text/event-stream' },
    body: {
      getReader: () => ({
        read: async () => {
          if (index >= chunks.length) return { done: true, value: undefined }
          const value = encoder.encode(chunks[index])
          index += 1
          return { done: false, value }
        },
      }),
    },
  } as unknown as Response
}

function blockedSseResponse(
  signal: AbortSignal,
  events: Array<{ event: string; data: unknown }> = [],
) {
  const encoder = new TextEncoder()
  const chunks = events.map(
    ({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
  )
  let index = 0
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'text/event-stream' },
    body: {
      getReader: () => ({
        read: async () => {
          if (index < chunks.length) {
            const value = encoder.encode(chunks[index])
            index += 1
            return { done: false, value }
          }
          return new Promise((_, reject) => {
            const abort = () => reject(new DOMException('Aborted', 'AbortError'))
            if (signal.aborted) {
              abort()
              return
            }
            signal.addEventListener('abort', abort, { once: true })
          })
        },
      }),
    },
  } as unknown as Response
}

async function selectProviderAndModel(
  wrapper: VueWrapper,
  providerId = 'provider-1',
  modelId = 'gpt-a',
): Promise<void> {
  await wrapper.get('[data-testid="chat-provider-select"]').setValue(providerId)
  await wrapper.get('[data-testid="chat-model-select"]').setValue(modelId)
}

async function mountPage(path = '/chat/chat-1') {
  const pinia = makePinia()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/chat', component: ChatPage },
      { path: '/chat/:chatId', component: ChatPage },
      { path: '/knowledge-bases', component: { template: '<div>kb</div>' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(ChatPage, {
    global: { plugins: [pinia, router] },
  })
  await flushPromises()
  return { router, wrapper }
}

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listChats.mockResolvedValue({
      data: [chat],
      meta: { next_cursor: null, has_more: false, request_id: 'req-1' },
    })
    apiMocks.listKbs.mockResolvedValue({
      data: [knowledgeBase],
      meta: { next_cursor: null, has_more: false, request_id: 'req-2' },
    })
    apiMocks.listFacets.mockResolvedValue({
      products: ['spring-boot'],
      versions: ['3.2', '3.1'],
      sources: ['file'],
      knowledge_base_ids: ['kb-1'],
    })
    apiMocks.getPolicy.mockResolvedValue(modelPolicy)
    apiMocks.listProviders.mockResolvedValue({
      data: providers,
      meta: { next_cursor: null, has_more: false, request_id: 'req-providers' },
    })
    apiMocks.listMessages.mockResolvedValue(messagePage([userMessage]))
    apiMocks.cancelMessage.mockResolvedValue({
      message_id: 'message-assistant',
      status: 'cancelled',
    })
    apiMocks.submitFeedback.mockResolvedValue({
      id: 'feedback-1',
      message_id: 'message-assistant-history',
      feedback_type: 'useful',
    })
    apiMocks.createChat.mockResolvedValue({
      ...chat,
      id: 'chat-2',
      title: '新会话',
      knowledge_base_ids: ['kb-1'],
    })
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps send disabled until provider and model are selected', async () => {
    const { wrapper } = await mountPage('/chat')
    const providerSelect = wrapper.get('[data-testid="chat-provider-select"]')
    const modelSelect = wrapper.get('[data-testid="chat-model-select"]')

    expect((providerSelect.element as HTMLSelectElement).value).toBe('')
    expect((modelSelect.element as HTMLSelectElement).value).toBe('')
    expect(modelSelect.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="send-message"]').attributes('disabled')).toBeDefined()
    await providerSelect.setValue('provider-1')
    expect(wrapper.get('[data-testid="send-message"]').attributes('disabled')).toBeDefined()
    await modelSelect.setValue('gpt-a')
    expect(wrapper.get('[data-testid="send-message"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="question-input"]').setValue('Question')
    expect(wrapper.get('[data-testid="send-message"]').attributes('disabled')).toBeUndefined()
  })

  it('only exposes active, keyed, policy-allowed providers and their models', async () => {
    const { wrapper } = await mountPage('/chat')
    const providerSelect = wrapper.get('[data-testid="chat-provider-select"]')

    expect(providerSelect.findAll('option').map((option) => option.text())).toEqual([
      '选择供应商',
      'Provider One',
      'Provider Two',
    ])

    await providerSelect.setValue('provider-1')
    expect(
      wrapper
        .get('[data-testid="chat-model-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择模型', 'gpt-a', 'gpt-b'])

    await wrapper.get('[data-testid="chat-provider-select"]').setValue('provider-2')
    expect(
      (wrapper.get('[data-testid="chat-model-select"]').element as HTMLSelectElement)
        .value,
    ).toBe('')
    expect(
      wrapper
        .get('[data-testid="chat-model-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择模型', 'claude-a'])
  })

  it('exposes providers inherited from the effective deployment policy', async () => {
    apiMocks.getPolicy.mockResolvedValueOnce({
      ...modelPolicy,
      allowed_provider_ids: ['provider-1', 'provider-2'],
      version: 7,
    })

    const { wrapper } = await mountPage('/chat')

    expect(
      wrapper
        .get('[data-testid="chat-provider-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择供应商', 'Provider One', 'Provider Two'])
  })

  it('clears provider options before the next team provider request resolves', async () => {
    const { wrapper } = await mountPage('/chat')
    expect(
      wrapper
        .get('[data-testid="chat-provider-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择供应商', 'Provider One', 'Provider Two'])

    const nextProviders = deferred<{
      data: ModelProvider[]
      meta: {
        next_cursor: null
        has_more: boolean
        request_id: string
      }
    }>()
    const nextPolicy = deferred<ModelPolicy>()
    apiMocks.listProviders.mockReturnValueOnce(nextProviders.promise)
    apiMocks.getPolicy.mockReturnValueOnce(nextPolicy.promise)

    useTeamStore().selectTeam('team-2')
    await flushPromises()

    expect(
      wrapper
        .get('[data-testid="chat-provider-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择供应商'])
  })

  it('ignores a late provider response from the previous team', async () => {
    const oldProviders = deferred<{
      data: ModelProvider[]
      meta: {
        next_cursor: null
        has_more: boolean
        request_id: string
      }
    }>()
    const oldPolicy = deferred<ModelPolicy>()
    apiMocks.listProviders.mockImplementationOnce(() => oldProviders.promise)
    apiMocks.getPolicy.mockImplementationOnce(() => oldPolicy.promise)

    const { wrapper } = await mountPage('/chat')
    const teamTwoProvider: ModelProvider = {
      ...providers[1],
      id: 'provider-team-2',
      name: 'Team Two Provider',
      model_ids: ['team-2-model'],
    }
    apiMocks.listProviders.mockResolvedValueOnce({
      data: [teamTwoProvider],
      meta: { next_cursor: null, has_more: false, request_id: 'req-team-2' },
    })
    apiMocks.getPolicy.mockResolvedValueOnce({
      ...modelPolicy,
      allowed_provider_ids: ['provider-team-2'],
    })

    useTeamStore().selectTeam('team-2')
    await flushPromises()
    expect(
      wrapper
        .get('[data-testid="chat-provider-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择供应商', 'Team Two Provider'])

    oldProviders.resolve({
      data: providers,
      meta: { next_cursor: null, has_more: false, request_id: 'req-team-1' },
    })
    oldPolicy.resolve(modelPolicy)
    await flushPromises()

    expect(
      wrapper
        .get('[data-testid="chat-provider-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择供应商', 'Team Two Provider'])
  })

  it('ignores a late same-team provider response after a newer request', async () => {
    const firstProviders = deferred<{
      data: ModelProvider[]
      meta: {
        next_cursor: null
        has_more: boolean
        request_id: string
      }
    }>()
    const firstPolicy = deferred<ModelPolicy>()
    apiMocks.listProviders.mockImplementationOnce(() => firstProviders.promise)
    apiMocks.getPolicy.mockImplementationOnce(() => firstPolicy.promise)

    const { wrapper } = await mountPage('/chat')
    const teamTwoProvider: ModelProvider = {
      ...providers[1],
      id: 'provider-team-2',
      name: 'Team Two Provider',
      model_ids: ['team-2-model'],
    }
    const latestProvider: ModelProvider = {
      ...providers[1],
      id: 'provider-team-1-latest',
      name: 'Latest Team One Provider',
      model_ids: ['latest-model'],
    }
    apiMocks.listProviders
      .mockResolvedValueOnce({
        data: [teamTwoProvider],
        meta: { next_cursor: null, has_more: false, request_id: 'req-team-2' },
      })
      .mockResolvedValueOnce({
        data: [latestProvider],
        meta: { next_cursor: null, has_more: false, request_id: 'req-team-1-latest' },
      })
    apiMocks.getPolicy
      .mockResolvedValueOnce({
        ...modelPolicy,
        allowed_provider_ids: ['provider-team-2'],
      })
      .mockResolvedValueOnce({
        ...modelPolicy,
        allowed_provider_ids: ['provider-team-1-latest'],
      })

    useTeamStore().selectTeam('team-2')
    await flushPromises()
    useTeamStore().selectTeam('team-1')
    await flushPromises()
    expect(
      wrapper
        .get('[data-testid="chat-provider-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择供应商', 'Latest Team One Provider'])

    firstProviders.resolve({
      data: [providers[0]],
      meta: { next_cursor: null, has_more: false, request_id: 'req-team-1-first' },
    })
    firstPolicy.resolve(modelPolicy)
    await flushPromises()

    expect(
      wrapper
        .get('[data-testid="chat-provider-select"]')
        .findAll('option')
        .map((option) => option.text()),
    ).toEqual(['选择供应商', 'Latest Team One Provider'])
  })

  it('includes provider and model in the ask request', async () => {
    vi.mocked(fetch).mockResolvedValue(sseResponse([]))
    const { wrapper } = await mountPage('/chat')

    await wrapper.get('[data-testid="chat-provider-select"]').setValue('provider-1')
    await wrapper.get('[data-testid="chat-model-select"]').setValue('gpt-a')
    await wrapper.get('[data-testid="question-input"]').setValue('Question')
    await wrapper.get('[data-testid="send-message"]').trigger('click')
    await flushPromises()

    const request = vi.mocked(fetch).mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(request.body))).toMatchObject({
      provider_id: 'provider-1',
      model_id: 'gpt-a',
    })
  })

  it('uses contract filters and consumes rewrite, citation and delta events', async () => {
    const answer =
      '使用 spring.threads.virtual.enabled=true 开启虚拟线程。'
    vi.mocked(fetch).mockResolvedValue(
      sseResponse([
        {
          event: 'meta',
          data: {
            trace_id: 'trace-1',
            message_id: 'message-assistant',
            engine_mode: 'dual_engine',
            degraded: true,
          },
        },
        {
          event: 'rewrite',
          data: {
            original: '怎么开启？',
            rewritten: 'Spring Boot 3.2 如何开启虚拟线程？',
          },
        },
        {
          event: 'citation',
          data: {
            citation_id: 'c1',
            chunk_id: 'chunk-1',
            excerpt: '设置 spring.threads.virtual.enabled=true。',
            source_locator: { file_name: 'spring-boot.md', heading_path: ['线程'] },
          },
        },
        { event: 'delta', data: { text: answer } },
        {
          event: 'done',
          data: {
            message_id: 'message-assistant',
            status: 'completed',
            citation_ids: ['c1'],
          },
        },
      ]),
    )

    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('Spring 问题')
    expect(wrapper.text()).toContain('Java 资料')
    expect(wrapper.text()).toContain('虚拟线程如何配置？')

    await selectProviderAndModel(wrapper)
    await wrapper.get('[data-testid="chat-product-filter"]').setValue('spring-boot')
    await wrapper.get('[data-testid="chat-version-filter"]').setValue('3.2')
    await wrapper.get('[data-testid="question-input"]').setValue('虚拟线程如何配置？')
    await wrapper.get('[data-testid="send-message"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/chats/ask',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          team_id: 'team-1',
          chat_id: 'chat-1',
          provider_id: 'provider-1',
          model_id: 'gpt-a',
          question: '虚拟线程如何配置？',
          filters: {
            knowledge_base_ids: ['kb-1'],
            product: 'spring-boot',
            version_values: ['3.2'],
          },
          model_policy: 'inherit',
          stream: true,
        }),
      }),
    )
    expect(wrapper.text()).toContain(answer)
    expect(wrapper.text()).toContain('Spring Boot 3.2 如何开启虚拟线程？')
    expect(wrapper.text()).toContain('spring-boot.md')
    expect(wrapper.text()).toContain('降级')
  })

  it('keeps working when facets omit optional fields', async () => {
    apiMocks.listFacets.mockResolvedValueOnce({})

    const { wrapper } = await mountPage()

    expect(wrapper.find('[data-testid="chat-product-filter"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Java 资料')
  })

  it('renders history citations stored as objects without hydration', async () => {
    apiMocks.listMessages.mockResolvedValueOnce(
      messagePage([
        userMessage,
        {
          id: 'message-assistant-history',
          chat_id: 'chat-1',
          role: 'assistant',
          content: '启用参数即可。',
          status: 'completed',
          trace_id: 'trace-history',
          citation_ids: [
            {
              citation_id: 'c-history',
              chunk_id: 'chunk-history',
              document_name: '历史引用.md',
              excerpt: '历史引用正文',
            },
          ],
          refusal_reason: null,
          created_at: '2026-10-19T12:01:00+00:00',
        } as unknown as MessageView,
      ]),
    )

    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('启用参数即可。')
    expect(wrapper.text()).toContain('历史引用.md')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('opens, scrolls to, and briefly highlights a matching inline citation', async () => {
    apiMocks.listMessages.mockResolvedValueOnce(
      messagePage([
        userMessage,
        {
          ...assistantMessage,
          content: '启用参数即可 [c7]。',
          citation_ids: [
            {
              citation_id: 'c7',
              chunk_id: 'chunk-7',
              document_name: '线程配置.md',
              excerpt: '设置 spring.threads.virtual.enabled=true 可启用虚拟线程。',
              source_url: '/api/v1/docs/download?document_id=doc-7',
            },
          ],
        } as MessageView,
      ]),
    )
    const scrollIntoView = vi.mocked(Element.prototype.scrollIntoView)

    const { wrapper } = await mountPage()
    const inlineCitation = wrapper.get('[data-testid="inline-citation-c7"]')
    const detailsSelector = '[data-testid="citation-details-c7"]'

    expect(inlineCitation.element.tagName).toBe('BUTTON')
    expect(wrapper.find(detailsSelector).exists()).toBe(false)

    vi.useFakeTimers()
    await inlineCitation.trigger('click')
    await flushPromises()

    const entry = wrapper.get('[data-testid="citation-entry-c7"]')
    expect(wrapper.get(detailsSelector).text()).toContain(
      '设置 spring.threads.virtual.enabled=true 可启用虚拟线程。',
    )
    expect(entry.classes()).toContain('citation-item-highlighted')
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: 'smooth',
      block: 'center',
    })

    await vi.advanceTimersByTimeAsync(1600)
    await flushPromises()

    expect(entry.classes()).not.toContain('citation-item-highlighted')
    vi.useRealTimers()
  })

  it('toggles citation details from the citation entry button', async () => {
    apiMocks.listMessages.mockResolvedValueOnce(
      messagePage([
        userMessage,
        {
          ...assistantMessage,
          content: '启用参数即可 [c7]。',
          citation_ids: [
            {
              citation_id: 'c7',
              chunk_id: 'chunk-7',
              document_name: '线程配置.md',
              excerpt: '按需展开的引用正文。',
              source_url: '/api/v1/docs/download?document_id=doc-7',
            },
          ],
        } as MessageView,
      ]),
    )

    const { wrapper } = await mountPage()
    const entry = wrapper.get('[data-testid="citation-entry-c7"]')
    const detailsSelector = '[data-testid="citation-details-c7"]'

    expect(entry.element.tagName).toBe('BUTTON')
    expect(entry.attributes('type')).toBe('button')
    expect(wrapper.find(detailsSelector).exists()).toBe(false)

    await entry.trigger('click')
    expect(wrapper.get(detailsSelector).text()).toContain('按需展开的引用正文。')
    expect(
      wrapper.get(`${detailsSelector} a`).attributes('href'),
    ).toBe('/api/v1/docs/download?document_id=doc-7')

    await entry.trigger('click')
    expect(wrapper.find(detailsSelector).exists()).toBe(false)
  })

  it('renders unmatched citation markers as non-clickable safe text', async () => {
    apiMocks.listMessages.mockResolvedValueOnce(
      messagePage([
        userMessage,
        {
          ...assistantMessage,
          content: '<script>alert(1)</script> 已知 [c7]，缺失 [c9]。',
          citation_ids: [
            {
              citation_id: 'c7',
              chunk_id: 'chunk-7',
              document_name: '线程配置.md',
              excerpt: '已知引用正文。',
            },
          ],
        } as MessageView,
      ]),
    )
    const scrollIntoView = vi.mocked(Element.prototype.scrollIntoView)

    const { wrapper } = await mountPage()
    const unavailable = wrapper.get(
      '[data-testid="inline-citation-unavailable-c9"]',
    )

    expect(unavailable.element.tagName).toBe('SPAN')
    expect(unavailable.attributes('aria-disabled')).toBe('true')
    expect(wrapper.find('.message-row.assistant .message-content script').exists()).toBe(false)
    expect(wrapper.get('.message-row.assistant .message-content').text()).toContain(
      '<script>alert(1)</script>',
    )

    await unavailable.trigger('click')
    await flushPromises()

    expect(
      scrollIntoView.mock.calls.some(
        ([options]) =>
          typeof options === 'object' && options?.behavior === 'smooth',
      ),
    ).toBe(false)
    expect(wrapper.find('[data-testid="citation-details-c9"]').exists()).toBe(false)
  })

  it('loads the next message page with the returned cursor', async () => {
    apiMocks.listMessages
      .mockResolvedValueOnce(messagePage([userMessage], 'message-cursor-1'))
      .mockResolvedValueOnce(
        messagePage([
          {
            ...userMessage,
            id: 'message-user-2',
            content: '第二条历史消息',
          },
        ]),
      )

    const { wrapper } = await mountPage()

    expect(wrapper.find('[data-testid="chat-load-more"]').exists()).toBe(true)
    await wrapper.get('[data-testid="chat-load-more"] button').trigger('click')
    await flushPromises()

    expect(apiMocks.listMessages).toHaveBeenLastCalledWith(
      'team-1',
      'chat-1',
      'message-cursor-1',
    )
    expect(wrapper.text()).toContain('第二条历史消息')
    expect(wrapper.find('[data-testid="chat-load-more"]').exists()).toBe(false)
  })

  it('still accepts the legacy answer event', async () => {
    vi.mocked(fetch).mockResolvedValue(
      sseResponse([
        {
          event: 'answer',
          data: {
            message_id: 'message-legacy',
            content: '旧版回答内容',
            status: 'completed',
            citations: ['citation-legacy'],
          },
        },
      ]),
    )

    const { wrapper } = await mountPage()
    await selectProviderAndModel(wrapper)
    await wrapper.get('[data-testid="question-input"]').setValue('旧接口兼容')
    await wrapper.get('[data-testid="send-message"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('旧版回答内容')
  })

  it('creates a chat with the selected knowledge base', async () => {
    const { router, wrapper } = await mountPage('/chat')

    await wrapper.get('[data-testid="chat-new-title"]').setValue('新会话')
    await wrapper.get('[data-testid="chat-create"]').trigger('click')
    await flushPromises()

    expect(apiMocks.createChat).toHaveBeenCalledWith('team-1', '新会话', ['kb-1'])
    expect(router.currentRoute.value.path).toBe('/chat/chat-2')
  })

  it('handles a non-streamed refusal response', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({
        data: {
          message_id: 'message-refused',
          chat_id: 'chat-1',
          content: '知识库中没有足够依据。',
          citations: [],
          trace_id: 'trace-2',
          status: 'refused',
          refusal_reason: 'INSUFFICIENT_EVIDENCE',
          degraded: false,
        },
      }),
    } as unknown as Response)

    const { wrapper } = await mountPage()
    await wrapper.get('[data-testid="chat-stream-toggle"]').setValue(false)
    await selectProviderAndModel(wrapper)
    await wrapper.get('[data-testid="question-input"]').setValue('不存在的主题')
    await wrapper.get('[data-testid="send-message"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('知识库中没有足够依据')
    expect(wrapper.text()).toContain('依据不足')
  })

  it('submits feedback once for a completed assistant message', async () => {
    apiMocks.listMessages.mockResolvedValueOnce(
      messagePage([userMessage, assistantMessage]),
    )

    const { wrapper } = await mountPage()
    const useful = wrapper.get(
      '[data-testid="chat-feedback-useful-message-assistant-history"]',
    )

    await useful.trigger('click')
    await flushPromises()

    expect(apiMocks.submitFeedback).toHaveBeenCalledWith(
      'team-1',
      'message-assistant-history',
      'useful',
    )
    expect(useful.attributes('aria-pressed')).toBe('true')
    expect(messageMocks.success).toHaveBeenCalled()

    await useful.trigger('click')
    await flushPromises()

    expect(apiMocks.submitFeedback).toHaveBeenCalledTimes(1)
  })

  it('allows feedback retry after a failed submission', async () => {
    apiMocks.listMessages.mockResolvedValueOnce(
      messagePage([userMessage, assistantMessage]),
    )
    apiMocks.submitFeedback.mockRejectedValueOnce(new Error('feedback unavailable'))

    const { wrapper } = await mountPage()
    const useful = wrapper.get(
      '[data-testid="chat-feedback-useful-message-assistant-history"]',
    )

    await useful.trigger('click')
    await flushPromises()

    expect(messageMocks.error).toHaveBeenCalled()
    expect(useful.attributes('aria-pressed')).toBe('false')
    expect(useful.attributes('disabled')).toBeUndefined()
  })

  it('cancels a server-side assistant message before aborting the stream', async () => {
    let requestSignal: AbortSignal | undefined
    let resolveCancel: (() => void) | undefined
    apiMocks.cancelMessage.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveCancel = () =>
          resolve({ message_id: 'message-assistant-stream', status: 'cancelled' })
      }),
    )
    vi.mocked(fetch).mockImplementation(async (_input, init) => {
      requestSignal = init?.signal as AbortSignal
      return blockedSseResponse(requestSignal, [
        {
          event: 'meta',
          data: {
            trace_id: 'trace-stream',
            message_id: 'message-assistant-stream',
            engine_mode: 'dual_engine',
          },
        },
      ])
    })

    const { wrapper } = await mountPage()
    await selectProviderAndModel(wrapper)
    await wrapper.get('[data-testid="question-input"]').setValue('停止服务端生成')
    await wrapper.get('[data-testid="send-message"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="chat-stop"]').trigger('click')
    await flushPromises()

    expect(apiMocks.cancelMessage).toHaveBeenCalledWith(
      'team-1',
      'message-assistant-stream',
    )
    expect(requestSignal?.aborted).toBe(false)

    resolveCancel?.()
    await flushPromises()

    expect(requestSignal?.aborted).toBe(true)
  })

  it('aborts a local temporary message without calling the cancel API', async () => {
    let requestSignal: AbortSignal | undefined
    vi.mocked(fetch).mockImplementation(async (_input, init) => {
      requestSignal = init?.signal as AbortSignal
      return blockedSseResponse(requestSignal)
    })

    const { wrapper } = await mountPage()
    await selectProviderAndModel(wrapper)
    await wrapper.get('[data-testid="question-input"]').setValue('停止本地生成')
    await wrapper.get('[data-testid="send-message"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="chat-stop"]').trigger('click')
    await flushPromises()

    expect(apiMocks.cancelMessage).not.toHaveBeenCalled()
    expect(requestSignal?.aborted).toBe(true)
  })

  it('regenerates with the visible provider and model while preserving original filters', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        sseResponse([
          {
            event: 'meta',
            data: {
              message_id: 'message-assistant-first',
              trace_id: 'trace-first',
            },
          },
          { event: 'delta', data: { text: '第一版回答' } },
          {
            event: 'done',
            data: { message_id: 'message-assistant-first', status: 'completed' },
          },
        ]),
      )
      .mockResolvedValueOnce(
        sseResponse([
          {
            event: 'meta',
            data: {
              message_id: 'message-assistant-regenerated',
              trace_id: 'trace-regenerated',
            },
          },
          { event: 'delta', data: { text: '重新生成的回答' } },
          {
            event: 'done',
            data: {
              message_id: 'message-assistant-regenerated',
              status: 'completed',
            },
          },
        ]),
      )

    const { wrapper } = await mountPage()
    await selectProviderAndModel(wrapper)
    await wrapper.get('[data-testid="chat-product-filter"]').setValue('spring-boot')
    await wrapper.get('[data-testid="chat-version-filter"]').setValue('3.2')
    await wrapper.get('[data-testid="question-input"]').setValue('如何开启虚拟线程？')
    await wrapper.get('[data-testid="send-message"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="chat-product-filter"]').setValue('')
    await wrapper.get('[data-testid="chat-version-filter"]').setValue('3.1')
    await selectProviderAndModel(wrapper, 'provider-2', 'claude-a')
    await wrapper.get('[data-testid="chat-regenerate"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledTimes(2)
    const secondRequest = vi.mocked(fetch).mock.calls[1][1] as RequestInit
    expect(JSON.parse(String(secondRequest.body))).toMatchObject({
      team_id: 'team-1',
      chat_id: 'chat-1',
      provider_id: 'provider-2',
      model_id: 'claude-a',
      question: '如何开启虚拟线程？',
      filters: {
        knowledge_base_ids: ['kb-1'],
        product: 'spring-boot',
        version_values: ['3.2'],
      },
    })
    expect(wrapper.text()).toContain('第一版回答')
    expect(wrapper.text()).toContain('重新生成的回答')
  })
})
