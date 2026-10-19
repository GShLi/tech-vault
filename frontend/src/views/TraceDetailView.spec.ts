import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { TraceView } from '@/types/api'
import TraceDetailView from './TraceDetailView.vue'

const apiMocks = vi.hoisted(() => ({
  getTrace: vi.fn(),
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

const trace: TraceView = {
  id: 'trace-row-1',
  trace_id: 'trace-1',
  team_id: 'team-1',
  chat_id: 'chat-1',
  message_id: 'message-1',
  engine_mode: 'dual_engine',
  original_query: '虚拟线程为什么更快？',
  rewritten_query: 'Java 虚拟线程为什么更快？',
  filters: {},
  bm25_candidates: [],
  dense_candidates: [],
  rrf_candidates: [],
  rerank_candidates: [],
  final_context: [],
  stage_latency_ms: {
    policy_ms: 0.42,
    rewrite_ms: 9.126,
    bm25_ms: 22.4,
    dense_ms: 18.2,
    retrieval_ms: 1250,
    gateway_embedding_ms: 38.6635420000232,
    generation_ms: 61000,
  },
  degraded: false,
  error_code: null,
  model: {},
  feedback: [],
  created_at: '2026-10-20T08:00:00Z',
}

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
      created_at: '2026-10-20T08:00:00Z',
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
      { path: '/traces', component: { template: '<div>traces</div>' } },
      { path: '/traces/:traceId', component: TraceDetailView },
    ],
  })
  await router.push('/traces/trace-1')
  await router.isReady()
  const wrapper = mount(TraceDetailView, {
    global: {
      plugins: [makePinia(), router],
      stubs: { ASpin: { template: '<span />' } },
    },
  })
  await flushPromises()
  return wrapper
}

describe('TraceDetailView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getTrace.mockResolvedValue(trace)
  })

  it('renders stage latency as Chinese labels with compact units', async () => {
    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('策略校验')
    expect(wrapper.text()).toContain('查询改写')
    expect(wrapper.text()).toContain('关键词检索')
    expect(wrapper.text()).toContain('向量检索')
    expect(wrapper.text()).toContain('混合检索')
    expect(wrapper.text()).toContain('向量化调用')
    expect(wrapper.text()).toContain('答案生成')
    expect(wrapper.text()).toContain('<1 ms')
    expect(wrapper.text()).toContain('9.13 ms')
    expect(wrapper.text()).toContain('38.66 ms')
    expect(wrapper.text()).toContain('1.25 s')
    expect(wrapper.text()).toContain('1.02 min')
  })

  it('shows the English key, description and exact value in the tooltip', async () => {
    const wrapper = await mountPage()

    const row = wrapper.get('[data-testid="trace-stage-gateway_embedding_ms"]')
    expect(row.attributes('title')).toContain('gateway_embedding_ms')
    expect(row.attributes('title')).toContain('调用 Embedding 模型生成查询向量')
    expect(row.attributes('title')).toContain('38.6635420000232 ms')
  })
})
