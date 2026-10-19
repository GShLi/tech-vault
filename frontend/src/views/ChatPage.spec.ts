import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { ChatView, KnowledgeBase, MessageView } from '@/types/api'
import ChatPage from './ChatPage.vue'

const apiMocks = vi.hoisted(() => ({
  cancelMessage: vi.fn(),
  createChat: vi.fn(),
  deleteChat: vi.fn(),
  listChats: vi.fn(),
  listFacets: vi.fn(),
  listKbs: vi.fn(),
  listMessages: vi.fn(),
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

    await wrapper.get('[data-testid="chat-product-filter"]').setValue('spring-boot')
    await wrapper.get('[data-testid="chat-version-filter"]').setValue('3.2')
    await wrapper.get('[data-testid="chat-question"]').setValue('虚拟线程如何配置？')
    await wrapper.get('[data-testid="chat-send"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/chats/ask',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          team_id: 'team-1',
          chat_id: 'chat-1',
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
    await wrapper.get('[data-testid="chat-question"]').setValue('旧接口兼容')
    await wrapper.get('[data-testid="chat-send"]').trigger('click')
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
    await wrapper.get('[data-testid="chat-question"]').setValue('不存在的主题')
    await wrapper.get('[data-testid="chat-send"]').trigger('click')
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
    await wrapper.get('[data-testid="chat-question"]').setValue('停止服务端生成')
    await wrapper.get('[data-testid="chat-send"]').trigger('click')
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
    await wrapper.get('[data-testid="chat-question"]').setValue('停止本地生成')
    await wrapper.get('[data-testid="chat-send"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="chat-stop"]').trigger('click')
    await flushPromises()

    expect(apiMocks.cancelMessage).not.toHaveBeenCalled()
    expect(requestSignal?.aborted).toBe(true)
  })

  it('regenerates the latest question with its original filters without removing old messages', async () => {
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
    await wrapper.get('[data-testid="chat-product-filter"]').setValue('spring-boot')
    await wrapper.get('[data-testid="chat-version-filter"]').setValue('3.2')
    await wrapper.get('[data-testid="chat-question"]').setValue('如何开启虚拟线程？')
    await wrapper.get('[data-testid="chat-send"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-testid="chat-product-filter"]').setValue('')
    await wrapper.get('[data-testid="chat-version-filter"]').setValue('3.1')
    await wrapper.get('[data-testid="chat-regenerate"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledTimes(2)
    const secondRequest = vi.mocked(fetch).mock.calls[1][1] as RequestInit
    expect(JSON.parse(String(secondRequest.body))).toMatchObject({
      team_id: 'team-1',
      chat_id: 'chat-1',
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
