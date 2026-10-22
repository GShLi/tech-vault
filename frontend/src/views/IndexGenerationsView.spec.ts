import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import IndexGenerationsView from './IndexGenerationsView.vue'

const apiMocks = vi.hoisted(() => ({
  listGenerations: vi.fn(),
  reindexGeneration: vi.fn(),
  validateGeneration: vi.fn(),
  activateGeneration: vi.fn(),
  rollbackGeneration: vi.fn(),
  getGenerationValidation: vi.fn(),
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

vi.mock('@arco-design/web-vue', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@arco-design/web-vue')>()),
  Message: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

const generation = {
  id: 'generation-1',
  team_id: 'team-1',
  status: 'active',
  chunk_count: 12,
  embedding_model: 'bge-m3',
  error_message: null,
  validation_errors: [],
  created_at: '2026-10-19T12:00:00+00:00',
  validated_at: '2026-10-19T12:01:00+00:00',
  activated_at: '2026-10-19T12:02:00+00:00',
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
  const team = useTeamStore()
  team.selectTeam('team-1')
  return pinia
}

describe('IndexGenerationsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listGenerations.mockResolvedValue({
      data: [generation],
      meta: { next_cursor: null, has_more: false, request_id: 'req-list' },
    })
    apiMocks.reindexGeneration.mockResolvedValue({
      generation: { ...generation, id: 'generation-2', status: 'active' },
      run: {
        generation_id: 'generation-2',
        status: 'active',
        execution_mode: 'inline',
        task_id: null,
        passed: true,
        checked_chunks: 12,
        errors: [],
      },
    })
  })

  it('lets a leader start a full generation rebuild and renders run status', async () => {
    const pinia = makeStore('leader')
    const wrapper = mount(IndexGenerationsView, {
      global: {
        plugins: [pinia],
        stubs: {
          ASpin: true,
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })
    await flushPromises()

    const button = wrapper.find('[data-testid="generation-reindex"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    await flushPromises()

    expect(apiMocks.reindexGeneration).toHaveBeenCalledWith('team-1')
    expect(
      wrapper.find('[data-testid="generation-reindex-status"]').text(),
    ).toContain('active')
    expect(
      wrapper.find('[data-testid="generation-reindex-status"]').text(),
    ).toContain('inline')
  })

  it('hides the full rebuild entry from a regular member', async () => {
    const pinia = makeStore('member')
    const wrapper = mount(IndexGenerationsView, {
      global: {
        plugins: [pinia],
        stubs: {
          ASpin: true,
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="generation-reindex"]').exists()).toBe(
      false,
    )
  })
})
