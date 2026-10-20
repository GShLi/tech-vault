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

const chunkTrace: TraceView = {
  ...trace,
  bm25_candidates: [
    {
      chunk_id: 'chunk-7',
      rank: 1,
      score: 0.91,
      matched_terms: ['Virtual', 'threads'],
    },
  ],
  dense_candidates: [{ chunk_id: 'chunk-7', rank: 1, score: 0.88 }],
  rrf_candidates: [{ chunk_id: 'chunk-7', rank: 1, score: 0.93 }],
  rerank_candidates: [{ chunk_id: 'chunk-7', rank: 1, score: 0.97 }],
  final_context: [{ chunk_id: 'chunk-7', rank: 1, score: 0.97 }],
  chunk_details: {
    'chunk-7': {
      id: 'chunk-7',
      document_id: 'doc-7',
      document_name: 'virtual-threads.md',
      knowledge_base_id: 'kb-7',
      knowledge_base_name: 'Java KB',
      content: 'Virtual threads are lightweight Java threads.',
      heading_path: ['Virtual Threads', 'Scheduling'],
      source_locator: { page_no: 3 },
      chunk_status: 'enabled',
      doc_status: 'active',
      visibility: 'team_shared',
      data_classification: 'internal',
      index_generation: 'generation-1',
      version: 2,
      version_values: ['3.2'],
      logical_chunk_key: 'logical-chunk-7',
      content_hash: 'hash-7',
      source_path: 'virtual-threads.md',
      created_at: '2026-10-20T08:00:00Z',
      updated_at: '2026-10-20T08:00:00Z',
    },
  },
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
      stubs: {
        ASpin: { template: '<span />' },
        ADrawer: {
          props: ['visible'],
          template:
            '<div v-if="visible" data-testid="chunk-detail-drawer"><slot /></div>',
        },
      },
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

  it('shows clickable chunk content and copies raw JSON from the detail drawer', async () => {
    apiMocks.getTrace.mockResolvedValueOnce(chunkTrace)
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })

    const wrapper = await mountPage()
    const trigger = wrapper.get('[data-testid="trace-chunk-chunk-7"]')

    expect(trigger.element.tagName).toBe('BUTTON')
    expect(trigger.attributes('title')).toBe('点击查看 Chunk 详情')
    expect(trigger.text()).toContain(
      'Virtual threads are lightweight Java threads.',
    )

    await trigger.trigger('click')

    const drawer = wrapper.get('[data-testid="chunk-detail-drawer"]')
    expect(drawer.text()).toContain('文档名称')
    expect(drawer.text()).toContain('virtual-threads.md')
    expect(drawer.text()).toContain('知识库')
    expect(drawer.text()).toContain('Java KB')
    expect(drawer.text()).toContain('标题路径')
    expect(drawer.text()).toContain('Virtual Threads / Scheduling')
    expect(drawer.text()).toContain(
      'Virtual threads are lightweight Java threads.',
    )

    await wrapper.get('[data-testid="copy-chunk-json"]').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining(
        '"content": "Virtual threads are lightweight Java threads."',
      ),
    )
    expect(wrapper.get('[data-testid="copy-chunk-json"]').text()).toContain(
      '已复制',
    )
  })

  it('marks restricted chunk content without exposing the document body', async () => {
    apiMocks.getTrace.mockResolvedValueOnce({
      ...chunkTrace,
      chunk_details: {
        'chunk-7': { id: 'chunk-7', restricted: true },
      },
    })

    const wrapper = await mountPage()
    const trigger = wrapper.get('[data-testid="trace-chunk-chunk-7"]')
    expect(trigger.text()).toContain('无权查看该 Chunk 内容')

    await trigger.trigger('click')
    const drawer = wrapper.get('[data-testid="chunk-detail-drawer"]')
    expect(drawer.text()).toContain('该 Chunk 属于私有文档，当前账号无权查看详情')
    expect(drawer.text()).not.toContain(
      'Virtual threads are lightweight Java threads.',
    )
    expect(wrapper.find('[data-testid="copy-chunk-json"]').exists()).toBe(false)
  })

  it('renders query rewrite source, filters and fallback reason', async () => {
    apiMocks.getTrace.mockResolvedValueOnce({
      ...trace,
      rewritten_query: 'Spring Boot 3.2 如何开启虚拟线程？',
      rewrite: {
        original_query: '它怎么开启？',
        rewritten_query: 'Spring Boot 3.2 如何开启虚拟线程？',
        changed: true,
        route: 'openai_chat_completions',
        model_id: 'gpt-5-mini',
        structured_mode: 'json_schema',
        extracted_filters: {
          product: 'spring-boot',
          version_values: ['3.2'],
        },
        applied_filters: {
          product: 'spring-boot',
          version_values: ['3.2'],
        },
        dropped_filters: [],
        fallback_reason: null,
        latency_ms: 820,
        input_tokens: 450,
        output_tokens: 24,
      },
    } as TraceView)

    const wrapper = await mountPage()
    const panel = wrapper.get('[data-testid="trace-rewrite"]')

    expect(panel.text()).toContain('它怎么开启？')
    expect(panel.text()).toContain('Spring Boot 3.2 如何开启虚拟线程？')
    expect(panel.text()).toContain('LLM 结构化')
    expect(panel.text()).toContain('spring-boot')
    expect(panel.text()).toContain('3.2')
    expect(panel.text()).toContain('gpt-5-mini')
  })

  it('highlights BM25 matched terms in the chunk preview', async () => {
    apiMocks.getTrace.mockResolvedValueOnce(chunkTrace)

    const wrapper = await mountPage()
    const marks = wrapper.findAll('.chunk-content-preview mark')

    expect(marks.map((mark) => mark.text())).toEqual([
      'Virtual',
      'threads',
      'threads',
    ])
    expect(wrapper.findAll('.chunk-content-preview').length).toBe(5)
    expect(wrapper.findAll('.chunk-content-preview mark').length).toBe(3)
  })
})
