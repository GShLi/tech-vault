import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { TOKEN_STORAGE_KEY } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import type { IngestionRun } from '@/types/api'
import TaskDetailView from './TaskDetailView.vue'

const apiMocks = vi.hoisted(() => ({
  getIngestionRun: vi.fn(),
  retryIngestion: vi.fn(),
  cancelIngestion: vi.fn(),
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

function ingestionRun(overrides: Partial<IngestionRun> = {}): IngestionRun {
  return {
    id: 'run-1',
    document_version_id: 'version-1',
    status: 'queued',
    current_stage: 'queued',
    stage_progress_pct: 0,
    error_code: null,
    retryable: false,
    created_at: '2026-10-19T12:00:00+00:00',
    updated_at: '2026-10-19T12:00:00+00:00',
    ...overrides,
  }
}

function sseResponse(blocks: string[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      blocks.forEach((block) => controller.enqueue(encoder.encode(block)))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

function eventBlock(event: string, data: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

async function mountPage(runId = 'run-1') {
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
  sessionStorage.setItem(TOKEN_STORAGE_KEY, 'token')

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/tasks/:runId', component: TaskDetailView }],
  })
  await router.push(`/tasks/${runId}`)
  await router.isReady()

  const wrapper = mount(TaskDetailView, {
    global: {
      plugins: [pinia, router],
      stubs: {
        ASpin: true,
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('TaskDetailView ingestion SSE', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    vi.stubGlobal('fetch', fetchMock)
    apiMocks.getIngestionRun.mockResolvedValue(ingestionRun())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('explains index waiting without offering a duplicate retry', async () => {
    apiMocks.getIngestionRun.mockResolvedValue(
      ingestionRun({ current_stage: 'waiting_index', retryable: true }),
    )
    fetchMock.mockResolvedValue(sseResponse([]))
    const { wrapper } = await mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('等待前序文档处理')
    expect(wrapper.text()).toContain('本任务会自动继续，无需重新上传')
    expect(wrapper.findAll('button').some((button) => button.text() === '重试')).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === '取消')).toBe(true)
    wrapper.unmount()
  })

  it('automatically applies progress and failed events to the run', async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        eventBlock('progress', {
          run_id: 'run-1',
          status: 'chunking',
          stage: 'chunking',
          percent: 50,
          error_code: null,
          retryable: false,
        }),
        eventBlock('failed', {
          run_id: 'run-1',
          status: 'failed',
          stage: 'embedding',
          percent: 72,
          error_code: 'EMBEDDING_FAILED',
          retryable: true,
        }),
      ]),
    )

    const { wrapper } = await mountPage()

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('72%')
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/v1/ingestions/events?team_id=team-1&run_id=run-1',
    )
    expect(wrapper.text()).toContain('embedding')
    expect(wrapper.text()).toContain('EMBEDDING_FAILED')
    expect(wrapper.text()).toContain('failed')
  })

  it.each([
    ['completed', 100, null, '已完成'],
    ['cancelled', 38, 'CANCELLED', '已取消'],
  ])(
    'applies a terminal %s event',
    async (event, percent, errorCode, label) => {
      fetchMock.mockResolvedValue(
        sseResponse([
          eventBlock(event, {
            run_id: 'run-1',
            status: event,
            stage: event === 'completed' ? 'completed' : 'cancelled',
            percent,
            error_code: errorCode,
            retryable: event !== 'completed',
          }),
        ]),
      )

      const { wrapper } = await mountPage()

      await vi.waitFor(() => {
        expect(wrapper.text()).toContain(`${percent}%`)
      })
      expect(wrapper.findComponent({ name: 'Tag' }).text()).toContain(label)
      if (errorCode) expect(wrapper.text()).toContain(errorCode)
    },
  )

  it('aborts the active event stream when the component unmounts', async () => {
    let streamController: ReadableStreamDefaultController<Uint8Array> | null =
      null
    fetchMock.mockImplementation((_input, init) => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller
          init?.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('Aborted', 'AbortError'))
          })
        },
      })
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        }),
      )
    })

    const { wrapper } = await mountPage()
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
    const signal = fetchMock.mock.calls[0]?.[1]?.signal

    expect(signal).toBeInstanceOf(AbortSignal)
    expect(signal?.aborted).toBe(false)
    wrapper.unmount()
    expect(signal?.aborted).toBe(true)
    expect(streamController).not.toBeNull()
    await flushPromises()
  })
})
