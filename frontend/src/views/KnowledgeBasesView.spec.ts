import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import KnowledgeBasesView from './KnowledgeBasesView.vue'

const apiMocks = vi.hoisted(() => ({
  listKbs: vi.fn(),
  createKb: vi.fn(),
  updateKb: vi.fn(),
  archiveKb: vi.fn(),
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

const membership = {
  team_id: 'team-1',
  team_name: 'Platform',
  role: 'leader' as const,
  status: 'active',
}

function makeStore(role: 'leader' | 'member' = 'leader') {
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
      created_at: '2026-10-19T12:00:00+00:00',
    },
    memberships: [{ ...membership, role }],
  }
  const team = useTeamStore()
  team.selectTeam('team-1')
  return pinia
}

describe('KnowledgeBasesView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listKbs.mockResolvedValue({
      data: [
        {
          id: 'kb-1',
          team_id: 'team-1',
          name: 'Java 资料',
          description: 'JDK notes',
          status: 'active',
          default_model_policy_mode: 'local_only',
          document_count: 0,
          version: 1,
          created_at: '2026-10-19T12:00:00+00:00',
          updated_at: '2026-10-19T12:00:00+00:00',
        },
      ],
      meta: {
        next_cursor: null,
        has_more: false,
        request_id: 'req-1',
      },
    })
  })

  it('renders knowledge bases and allows a leader to create one', async () => {
    const pinia = makeStore('leader')
    const wrapper = mount(KnowledgeBasesView, {
      global: {
        plugins: [pinia],
        stubs: { AModal: true, ASpin: true, ATag: true },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Java 资料')
    expect(wrapper.find('[data-testid="kb-create-open"]').exists()).toBe(true)
    expect(apiMocks.listKbs).toHaveBeenCalledWith('team-1', null)
  })

  it('hides management actions for a member', async () => {
    const pinia = makeStore('member')
    const wrapper = mount(KnowledgeBasesView, {
      global: {
        plugins: [pinia],
        stubs: { AModal: true, ASpin: true, ATag: true },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Java 资料')
    expect(wrapper.find('[data-testid="kb-create-open"]').exists()).toBe(false)
  })
})
