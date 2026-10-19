import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { ChunkHistoryView, ChunkView } from '@/types/api'
import ChunkDetailView from './ChunkDetailView.vue'

const apiMocks = vi.hoisted(() => ({
  getChunk: vi.fn(),
  getChunkHistory: vi.fn(),
  getDoc: vi.fn(),
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

const chunk: ChunkView = {
  id: 'chk_1',
  document_id: 'doc-1',
  content: '当前 Chunk 内容',
  heading_path: ['检索'],
  source_locator: {},
  status: 'enabled',
  version: 2,
  created_at: '2026-10-19T12:00:00+00:00',
  updated_at: '2026-10-19T12:00:00+00:00',
}

function documentView(ownerUserId: string) {
  return {
    id: 'doc-1',
    knowledge_base_id: 'kb-1',
    file_name: 'guide.md',
    source_type: 'upload',
    product: null,
    version_values: [],
    visibility: 'private',
    data_classification: 'internal',
    doc_status: 'active',
    deleted_at: null,
    purged_at: null,
    version: 1,
    created_at: '2026-10-19T12:00:00+00:00',
    updated_at: '2026-10-19T12:00:00+00:00',
    owner_user_id: ownerUserId,
    current_version_id: 'version-1',
    source_uri: null,
    version_family: null,
  }
}

function history(id: string, content: string): ChunkHistoryView {
  return {
    id,
    action: 'update',
    old_content: null,
    new_content: content,
    actor_id: 'user-1',
    created_at: '2026-10-19T12:00:00+00:00',
  }
}

function historyPage(data: ChunkHistoryView[], nextCursor: string | null = null) {
  return {
    data,
    meta: {
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
      request_id: 'req-history',
    },
  }
}

async function mountPage(options: {
  role?: 'leader' | 'member' | 'viewer'
  userId?: string
  ownerUserId?: string
} = {}) {
  const {
    role = 'leader',
    userId = role === 'leader' ? 'user-1' : 'user-2',
    ownerUserId = 'user-1',
  } = options
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = {
    user: {
      id: userId,
      email: `${role}@example.com`,
      display_name: role,
      status: 'active',
      is_super_admin: false,
      is_builtin: false,
      created_at: '2026-10-19T12:00:00+00:00',
    },
    memberships: [
      {
        team_id: 'team-1',
        team_name: 'Platform',
        role,
        status: 'active',
      },
    ],
  }
  useTeamStore().selectTeam('team-1')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/chunks/:chunkId', component: ChunkDetailView }],
  })
  await router.push('/chunks/chk_1')
  await router.isReady()
  apiMocks.getDoc.mockResolvedValue(documentView(ownerUserId))

  const wrapper = mount(ChunkDetailView, {
    global: {
      plugins: [pinia, router],
      stubs: {
        ASpin: true,
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('ChunkDetailView pagination', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getChunk.mockResolvedValue(chunk)
    apiMocks.getChunkHistory
      .mockResolvedValueOnce(historyPage([history('history-1', '初始记录')], 'cursor-1'))
      .mockResolvedValueOnce(historyPage([history('history-2', '更早记录')]))
  })

  it('loads the next history page with the returned cursor', async () => {
    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('初始记录')
    expect(wrapper.find('[data-testid="chunk-history-load-more"]').exists()).toBe(true)

    await wrapper.get('[data-testid="chunk-history-load-more"] button').trigger('click')
    await flushPromises()

    expect(apiMocks.getChunkHistory).toHaveBeenLastCalledWith(
      'team-1',
      'chk_1',
      'cursor-1',
    )
    expect(wrapper.text()).toContain('更早记录')
    expect(wrapper.find('[data-testid="chunk-history-load-more"]').exists()).toBe(false)
  })

  it('allows a member who owns the document to edit the chunk', async () => {
    const wrapper = await mountPage({
      role: 'member',
      userId: 'user-2',
      ownerUserId: 'user-2',
    })

    expect(apiMocks.getDoc).toHaveBeenCalledWith('team-1', 'doc-1')
    expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('保存修改')
  })

  it('keeps chunk editing read-only for a member who does not own the document', async () => {
    const wrapper = await mountPage({
      role: 'member',
      userId: 'user-2',
      ownerUserId: 'user-1',
    })

    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('保存修改')
    expect(wrapper.text()).not.toContain('重建文档 Chunk')
  })
})
