import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import EvaluationsView from './EvaluationsView.vue'
import TasksView from './TasksView.vue'

const apiMocks = vi.hoisted(() => ({
  listIngestions: vi.fn(),
  retryIngestion: vi.fn(),
  cancelIngestion: vi.fn(),
  listEvalDatasets: vi.fn(),
  createEvalDataset: vi.fn(),
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

function setupStores() {
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

describe('P0 operations views', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders ingestion tasks with progress and management actions', async () => {
    apiMocks.listIngestions.mockResolvedValue({
      data: [
        {
          id: 'run-1',
          document_version_id: 'version-1',
          status: 'failed',
          current_stage: 'embedding',
          stage_progress_pct: 62,
          error_code: 'EMBEDDING_TIMEOUT',
          retryable: true,
          created_at: '2026-10-19T12:00:00+00:00',
          updated_at: '2026-10-19T12:01:00+00:00',
        },
      ],
      meta: { next_cursor: null, has_more: false, request_id: 'req-1' },
    })

    const wrapper = mount(TasksView, {
      global: {
        plugins: [setupStores()],
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
          ASpin: true,
          ATag: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('向量化中')
    expect(wrapper.text()).toContain('62%')
    expect(wrapper.text()).toContain('EMBEDDING_TIMEOUT')
    expect(wrapper.find('[data-testid="task-retry-run-1"]').exists()).toBe(true)
  })

  it('renders golden datasets and lets a leader create one', async () => {
    apiMocks.listEvalDatasets.mockResolvedValue({
      data: [
        {
          id: 'dataset-1',
          name: '核心检索回归',
          description: 'P0 黄金集',
          case_count: 12,
          version: 3,
          created_at: '2026-10-19T12:00:00+00:00',
        },
      ],
      meta: { next_cursor: null, has_more: false, request_id: 'req-2' },
    })

    const wrapper = mount(EvaluationsView, {
      global: {
        plugins: [setupStores()],
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
          ASpin: true,
          ATag: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('核心检索回归')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.find('[data-testid="eval-create-open"]').exists()).toBe(true)
  })
})
