import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useTeamStore } from '@/stores/team'
import type { EvaluationReport, EvaluationRun } from '@/types/api'
import EvaluationRunView from './EvaluationRunView.vue'

const apiMocks = vi.hoisted(() => ({
  cancelEvalRun: vi.fn(),
  getEvalReport: vi.fn(),
  getEvalRun: vi.fn(),
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

const runningRun: EvaluationRun = {
  id: 'run-1',
  dataset_id: 'dataset-1',
  engine_mode: 'dual_engine',
  status: 'running',
  baseline_run_id: null,
  provider_id: 'provider-1',
  model_id: 'model-a',
  created_at: '2026-10-19T12:00:00+00:00',
}

const completedRun: EvaluationRun = {
  ...runningRun,
  status: 'succeeded',
}

const runningReport: EvaluationReport = {
  run_id: 'run-1',
  status: 'running',
  metrics: {},
  report: {},
}

const completedReport: EvaluationReport = {
  run_id: 'run-1',
  status: 'succeeded',
  metrics: { recall_at_10: 0.92 },
  report: { cases: 12 },
}

function setupPinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useTeamStore().selectTeam('team-1')
  return pinia
}

async function mountPage() {
  const pinia = setupPinia()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/evaluations',
        component: { template: '<div>evaluations</div>' },
      },
      {
        path: '/evaluations/:datasetId',
        component: { template: '<div>dataset</div>' },
      },
      {
        path: '/evaluations/runs/:runId',
        component: EvaluationRunView,
      },
    ],
  })
  await router.push('/evaluations/runs/run-1')
  await router.isReady()
  const wrapper = mount(EvaluationRunView, {
    global: {
      plugins: [pinia, router],
      stubs: {
        ASpin: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

function sseResponse(
  events: Array<{ event: string; data: unknown }>,
): Response {
  const encoder = new TextEncoder()
  const chunks = events.map(
    ({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
  )
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
        controller.close()
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}

describe('EvaluationRunView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.cancelEvalRun.mockResolvedValue({
      id: 'run-1',
      status: 'cancelled',
    })
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('consumes SSE and refreshes the run and report after a terminal event', async () => {
    apiMocks.getEvalRun
      .mockResolvedValueOnce(runningRun)
      .mockResolvedValueOnce(completedRun)
    apiMocks.getEvalReport
      .mockResolvedValueOnce(runningReport)
      .mockResolvedValueOnce(completedReport)
    vi.mocked(fetch).mockResolvedValue(
      sseResponse([
        {
          event: 'progress',
          data: { run_id: 'run-1', status: 'running', stage: 'rerank' },
        },
        {
          event: 'completed',
          data: { run_id: 'run-1', status: 'succeeded', stage: 'completed' },
        },
      ]),
    )

    const wrapper = await mountPage()

    await vi.waitFor(() => {
      expect(apiMocks.getEvalRun).toHaveBeenCalledTimes(2)
      expect(apiMocks.getEvalReport).toHaveBeenCalledTimes(2)
    })

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/evals/runs/events?team_id=team-1&run_id=run-1',
      expect.objectContaining({
        headers: { Authorization: 'Bearer access-token' },
        signal: expect.any(AbortSignal),
      }),
    )
    expect(wrapper.text()).toContain('succeeded')
    expect(wrapper.text()).toContain('provider-1')
    expect(wrapper.text()).toContain('model-a')
    expect(wrapper.text()).toContain('0.9200')
  })

  it('aborts the SSE request when the view is unmounted', async () => {
    apiMocks.getEvalRun.mockResolvedValue(runningRun)
    apiMocks.getEvalReport.mockResolvedValue(runningReport)
    let signal: AbortSignal | undefined

    vi.mocked(fetch).mockImplementation((_input, init) => {
      signal = init?.signal ?? undefined
      return Promise.resolve({
        ok: true,
        body: {
          getReader: () => ({
            read: () =>
              new Promise((_resolve, reject) => {
                signal?.addEventListener(
                  'abort',
                  () => reject(new DOMException('Aborted', 'AbortError')),
                  { once: true },
                )
              }),
          }),
        },
      } as unknown as Response)
    })

    const wrapper = await mountPage()
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce())

    expect(signal?.aborted).toBe(false)
    wrapper.unmount()
    expect(signal?.aborted).toBe(true)
  })
})
