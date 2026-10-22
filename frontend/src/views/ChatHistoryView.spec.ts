import { control, setControlValue } from '@/test/arco'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { ChatView, KnowledgeBase } from '@/types/api'
import ChatHistoryView from './ChatHistoryView.vue'

const apiMocks = vi.hoisted(() => ({
  deleteChat: vi.fn(),
  listChats: vi.fn(),
  listKbs: vi.fn(),
}))

const messageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
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

const firstChat: ChatView = {
  id: 'chat-1',
  team_id: 'team-1',
  user_id: 'user-1',
  title: 'Java 线程',
  knowledge_base_ids: ['kb-1'],
  version: 1,
  created_at: '2026-10-19T12:00:00+00:00',
  updated_at: '2026-10-19T12:00:00+00:00',
}

const secondChat: ChatView = {
  ...firstChat,
  id: 'chat-2',
  title: 'Spring Boot',
  knowledge_base_ids: ['kb-2'],
}

const knowledgeBases: KnowledgeBase[] = [
  {
    id: 'kb-1',
    team_id: 'team-1',
    name: 'Java 资料',
    description: null,
    status: 'active',
    default_model_policy_mode: 'local_only',
    document_count: 1,
    version: 1,
    created_at: '2026-10-19T12:00:00+00:00',
    updated_at: '2026-10-19T12:00:00+00:00',
  },
  {
    id: 'kb-2',
    team_id: 'team-1',
    name: 'Spring 资料',
    description: null,
    status: 'active',
    default_model_policy_mode: 'local_only',
    document_count: 1,
    version: 1,
    created_at: '2026-10-19T12:00:00+00:00',
    updated_at: '2026-10-19T12:00:00+00:00',
  },
]

function makePinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = {
    user: {
      id: 'user-1',
      email: 'leader@example.com',
      display_name: 'Leader',
      status: 'active',
      is_super_admin: false,
      is_builtin: false,
      created_at: '2026-10-19T12:00:00+00:00',
    },
    memberships: [
      {
        team_id: 'team-1',
        team_name: 'Platform',
        role: 'leader',
        status: 'active',
      },
    ],
  }
  useTeamStore().selectTeam('team-1')
  return pinia
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/chats', component: ChatHistoryView },
      { path: '/chat/:chatId', component: { template: '<div>chat</div>' } },
      { path: '/chat', component: { template: '<div>chat</div>' } },
    ],
  })
  await router.push('/chats')
  await router.isReady()
  const wrapper = mount(ChatHistoryView, {
    global: {
      plugins: [makePinia(), router],
      stubs: { ASpin: { template: '<span />' } },
    },
  })
  await flushPromises()
  return wrapper
}

describe('ChatHistoryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listKbs.mockResolvedValue({
      data: knowledgeBases,
      meta: { next_cursor: null, has_more: false, request_id: 'req-kbs' },
    })
    apiMocks.listChats
      .mockResolvedValueOnce({
        data: [firstChat],
        meta: { next_cursor: 'cursor-2', has_more: true, request_id: 'req-1' },
      })
      .mockResolvedValueOnce({
        data: [secondChat],
        meta: { next_cursor: null, has_more: false, request_id: 'req-2' },
      })
    apiMocks.deleteChat.mockResolvedValue({ deleted: firstChat.id })
  })

  it('loads the next cursor and filters by knowledge base', async () => {
    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('Java 线程')
    await wrapper.get('[data-testid="chat-history-load-more"]').trigger('click')
    await flushPromises()

    expect(apiMocks.listChats).toHaveBeenLastCalledWith(
      'team-1',
      'cursor-2',
      20,
    )
    expect(wrapper.text()).toContain('Spring Boot')

    await setControlValue(
      control(wrapper, '[data-testid="chat-history-kb-filter"]'),
      'kb-2',
    )
    expect(wrapper.text()).toContain('Spring Boot')
    expect(wrapper.text()).not.toContain('Java 线程')
  })

  it('requires confirmation before deleting a chat', async () => {
    const wrapper = await mountPage()

    await wrapper
      .get(`[data-testid="chat-history-delete-${firstChat.id}"]`)
      .trigger('click')
    expect(apiMocks.deleteChat).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('确认删除')

    await wrapper
      .get('[data-testid="chat-history-delete-confirm"]')
      .trigger('click')
    await flushPromises()

    expect(apiMocks.deleteChat).toHaveBeenCalledWith('team-1', firstChat.id)
  })

  it('keeps pagination available when the loaded page has no filter match', async () => {
    apiMocks.listChats.mockReset()
    apiMocks.listChats
      .mockResolvedValueOnce({
        data: [firstChat],
        meta: { next_cursor: 'cursor-2', has_more: true, request_id: 'req-1' },
      })
      .mockResolvedValueOnce({
        data: [secondChat],
        meta: { next_cursor: null, has_more: false, request_id: 'req-2' },
      })
    const wrapper = await mountPage()

    await setControlValue(
      control(wrapper, '[data-testid="chat-history-kb-filter"]'),
      'kb-2',
    )
    expect(wrapper.text()).toContain('当前筛选下暂无会话')
    await wrapper.get('[data-testid="chat-history-load-more"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Spring Boot')
  })
})
