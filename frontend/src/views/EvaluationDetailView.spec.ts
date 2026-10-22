import { control, setControlValue, selectOptions } from '@/test/arco'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import EvaluationDetailView from './EvaluationDetailView.vue'

const apiMocks = vi.hoisted(() => ({
  getEvalDataset: vi.fn(),
  getPolicy: vi.fn(),
  listEvalCases: vi.fn(),
  listEvalRuns: vi.fn(),
  listProviders: vi.fn(),
  startEvalRun: vi.fn(),
}))

const messageMocks = vi.hoisted(() => ({
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

const dataset = {
  id: 'dataset-1',
  name: 'Golden Set',
  description: null,
  case_count: 1,
  version: 1,
}

const policy = {
  mode: 'external_allowed',
  allowed_provider_ids: ['provider-1'],
  max_data_classification: 'internal',
  allow_chat_history: true,
  allow_document_metadata: true,
  require_redaction: false,
  version: 1,
}

const providers = [
  {
    id: 'provider-1',
    name: 'Provider One',
    provider_type: 'openai_chat_completions',
    base_url: 'https://provider-one.example/v1',
    model_ids: ['gpt-a', 'gpt-b'],
    status: 'active',
    has_api_key: true,
  },
]

function pageEnvelope<T>(data: T[]) {
  return {
    data,
    meta: {
      next_cursor: null,
      has_more: false,
      request_id: 'req-evaluation-detail',
    },
  }
}

async function mountPage() {
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
      created_at: '2026-10-20T12:00:00+00:00',
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

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/evaluations', component: { template: '<div />' } },
      {
        path: '/evaluations/:datasetId',
        component: EvaluationDetailView,
      },
      {
        path: '/evaluations/runs/:runId',
        component: { template: '<div>run</div>' },
      },
    ],
  })
  await router.push('/evaluations/dataset-1')
  await router.isReady()

  const wrapper = mount(EvaluationDetailView, {
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

describe('EvaluationDetailView provider selection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getEvalDataset.mockResolvedValue(dataset)
    apiMocks.getPolicy.mockResolvedValue(policy)
    apiMocks.listEvalCases.mockResolvedValue(
      pageEnvelope([
        {
          id: 'case-1',
          dataset_id: 'dataset-1',
          query_id: 'q1',
          query_type: 'concept',
          query: 'What is RAG?',
          relevant_chunk_ids: ['chunk-1'],
          filters: {},
          relevance: { 'chunk-1': 1 },
          created_at: '2026-10-20T12:00:00+00:00',
        },
      ]),
    )
    apiMocks.listEvalRuns.mockResolvedValue(pageEnvelope([]))
    apiMocks.listProviders.mockResolvedValue(pageEnvelope(providers))
    apiMocks.startEvalRun.mockResolvedValue({ id: 'run-1', status: 'queued' })
  })

  it('disables start until provider and model are selected and sends both ids', async () => {
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="open-evaluation-run"]').trigger('click')
    await flushPromises()

    const submit = wrapper.get('[data-testid="run-start-submit"]')
    expect(submit.attributes('disabled')).toBeDefined()
    expect(
      (
        await selectOptions(
          control(wrapper, '[data-testid="run-provider-select"]'),
        )
      ).map((option) => option.label),
    ).toEqual(['选择供应商', 'Provider One'])

    await setControlValue(
      control(wrapper, '[data-testid="run-provider-select"]'),
      'provider-1',
    )
    await flushPromises()
    await setControlValue(
      control(wrapper, '[data-testid="run-model-select"]'),
      'gpt-a',
    )
    await flushPromises()

    expect(submit.attributes('disabled')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(apiMocks.startEvalRun).toHaveBeenCalledWith(
      expect.objectContaining({
        team_id: 'team-1',
        dataset_id: 'dataset-1',
        provider_id: 'provider-1',
        model_id: 'gpt-a',
      }),
    )
  })

  it('exposes providers inherited from the effective deployment policy', async () => {
    apiMocks.getPolicy.mockResolvedValueOnce({
      ...policy,
      allowed_provider_ids: ['provider-1'],
      version: 7,
    })
    const wrapper = await mountPage()

    await wrapper.get('[data-testid="open-evaluation-run"]').trigger('click')
    await flushPromises()

    expect(
      (
        await selectOptions(
          control(wrapper, '[data-testid="run-provider-select"]'),
        )
      ).map((option) => option.label),
    ).toEqual(['选择供应商', 'Provider One'])
  })
})
