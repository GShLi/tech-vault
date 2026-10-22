import { control, setControlValue } from '@/test/arco'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTeamStore } from '@/stores/team'
import KnowledgeBaseDetailView from './KnowledgeBaseDetailView.vue'

const apiMocks = vi.hoisted(() => ({
  getKb: vi.fn(),
  listDocs: vi.fn(),
  listIngestions: vi.fn(),
  listKbMembers: vi.fn(),
  listMembers: vi.fn(),
  updateKbMembers: vi.fn(),
  updateKb: vi.fn(),
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

const kb = {
  id: 'kb-1',
  team_id: 'team-1',
  name: 'Java 资料',
  description: 'Spring 与 JDK 文档',
  status: 'active',
  default_model_policy_mode: 'local_only',
  document_count: 0,
  version: 1,
  created_at: '2026-10-19T12:00:00+00:00',
  updated_at: '2026-10-19T12:00:00+00:00',
}

const teamMembers = [
  {
    team_id: 'team-1',
    user_id: 'user-1',
    email: 'leader@example.com',
    display_name: 'Leader',
    role: 'leader',
    status: 'active',
    joined_at: '2026-10-19T12:00:00+00:00',
  },
  {
    team_id: 'team-1',
    user_id: 'user-2',
    email: 'member@example.com',
    display_name: 'Member',
    role: 'member',
    status: 'active',
    joined_at: '2026-10-19T11:00:00+00:00',
  },
  {
    team_id: 'team-1',
    user_id: 'user-3',
    email: 'viewer@example.com',
    display_name: 'Viewer',
    role: 'viewer',
    status: 'active',
    joined_at: '2026-10-19T10:00:00+00:00',
  },
  {
    team_id: 'team-1',
    user_id: 'user-4',
    email: 'disabled@example.com',
    display_name: 'Disabled',
    role: 'member',
    status: 'disabled',
    joined_at: '2026-10-19T09:00:00+00:00',
  },
]

function kbMember(userId: string) {
  const member = teamMembers.find((item) => item.user_id === userId)
  if (!member) throw new Error(`Unknown member ${userId}`)
  return {
    kb_id: 'kb-1',
    user_id: member.user_id,
    email: member.email,
    display_name: member.display_name,
    status: member.status,
  }
}

function pageEnvelope<T>(data: T[]) {
  return {
    data,
    meta: {
      next_cursor: null,
      has_more: false,
      request_id: 'req-kb-members',
    },
  }
}

function pageEnvelopeWithCursor<T>(data: T[], nextCursor: string | null) {
  return {
    data,
    meta: {
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
      request_id: 'req-kb-members',
    },
  }
}

function documentView(id: string, fileName: string) {
  return {
    id,
    knowledge_base_id: 'kb-1',
    file_name: fileName,
    source_type: 'upload',
    product: null,
    version_values: [],
    visibility: 'team_shared',
    data_classification: 'internal',
    doc_status: 'active',
    deleted_at: null,
    purged_at: null,
    version: 1,
    created_at: '2026-10-19T12:00:00+00:00',
    updated_at: '2026-10-19T12:00:00+00:00',
  }
}

function makePinia(role: 'leader' | 'member' | 'viewer' = 'leader') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.token = 'token'
  auth.me = {
    user: {
      id: role === 'leader' ? 'user-1' : `user-${role}`,
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
  const team = useTeamStore()
  team.selectTeam('team-1')
  return pinia
}

async function mountPage(role: 'leader' | 'member' | 'viewer' = 'leader') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/knowledge-bases/:kbId', component: KnowledgeBaseDetailView },
      { path: '/knowledge-bases', component: { template: '<div />' } },
      {
        path: '/knowledge-bases/:kbId/settings',
        component: { template: '<div />' },
      },
      {
        path: '/knowledge-bases/:kbId/upload',
        component: { template: '<div />' },
      },
      { path: '/documents/:documentId', component: { template: '<div />' } },
      { path: '/tasks', component: { template: '<div />' } },
      { path: '/tasks/:taskId', component: { template: '<div />' } },
    ],
  })
  await router.push('/knowledge-bases/kb-1')
  await router.isReady()

  const wrapper = mount(KnowledgeBaseDetailView, {
    global: {
      plugins: [makePinia(role), router],
      stubs: {
        ASpin: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('KnowledgeBaseDetailView member scope', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.getKb.mockResolvedValue(kb)
    apiMocks.listDocs.mockResolvedValue({
      data: [],
      meta: { next_cursor: null, has_more: false, request_id: 'req-docs' },
    })
    apiMocks.listIngestions.mockResolvedValue({
      data: [],
      meta: { next_cursor: null, has_more: false, request_id: 'req-tasks' },
    })
    apiMocks.listKbMembers.mockResolvedValue(
      pageEnvelope([kbMember('user-1'), kbMember('user-2')]),
    )
    apiMocks.listMembers.mockResolvedValue({
      data: teamMembers,
      meta: { next_cursor: null, has_more: false, request_id: 'req-members' },
    })
    apiMocks.updateKbMembers.mockResolvedValue([
      kbMember('user-1'),
      kbMember('user-3'),
    ])
  })

  it('loads and displays the current knowledge base member scope', async () => {
    const wrapper = await mountPage('member')

    expect(apiMocks.listKbMembers).toHaveBeenCalledWith(
      'team-1',
      'kb-1',
      null,
      100,
    )
    expect(wrapper.text()).toContain('Leader')
    expect(wrapper.text()).toContain('leader@example.com')
    expect(wrapper.text()).toContain('Member')
    expect(wrapper.text()).toContain('member@example.com')
    expect(wrapper.find('[data-testid="kb-member-save"]').exists()).toBe(false)
  })

  it('lets a leader select any active team member and refreshes after save', async () => {
    apiMocks.listKbMembers
      .mockResolvedValueOnce(
        pageEnvelope([kbMember('user-1'), kbMember('user-2')]),
      )
      .mockResolvedValueOnce(
        pageEnvelope([kbMember('user-1'), kbMember('user-3')]),
      )

    const wrapper = await mountPage('leader')

    expect(
      control(wrapper, '[data-testid="kb-member-option-user-2"]').exists(),
    ).toBe(true)
    expect(
      control(wrapper, '[data-testid="kb-member-option-user-3"]').exists(),
    ).toBe(true)
    expect(
      wrapper.find('[data-testid="kb-member-option-user-4"]').exists(),
    ).toBe(false)

    await setControlValue(
      control(wrapper, '[data-testid="kb-member-option-user-2"]'),
      false,
    )
    await setControlValue(
      control(wrapper, '[data-testid="kb-member-option-user-3"]'),
      true,
    )
    await wrapper.get('[data-testid="kb-member-save"]').trigger('click')
    await flushPromises()

    expect(apiMocks.updateKbMembers).toHaveBeenCalledWith({
      team_id: 'team-1',
      kb_id: 'kb-1',
      user_ids: ['user-1', 'user-3'],
    })
    expect(apiMocks.listKbMembers).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('viewer@example.com')
  })

  it.each(['member', 'viewer'] as const)(
    'keeps the %s role read-only',
    async (role) => {
      const wrapper = await mountPage(role)

      expect(
        wrapper.find('[data-testid="kb-member-option-user-1"]').exists(),
      ).toBe(false)
      expect(wrapper.find('[data-testid="kb-member-save"]').exists()).toBe(
        false,
      )
      expect(apiMocks.listMembers).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('leader@example.com')
    },
  )

  it('keeps the knowledge base page usable when member scope loading fails', async () => {
    apiMocks.listKbMembers.mockRejectedValueOnce(new Error('成员范围加载失败'))

    const wrapper = await mountPage('member')

    expect(wrapper.text()).toContain('Java 资料')
    expect(wrapper.text()).toContain('成员范围加载失败')
    expect(wrapper.find('[data-testid="kb-member-retry"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="kb-member-save"]').exists()).toBe(false)
  })

  it('shows upload without a GitHub source entry point', async () => {
    const wrapper = await mountPage('member')

    expect(wrapper.text()).toContain('上传文档')
    expect(wrapper.text()).not.toContain('来源')
    expect(
      wrapper.find('a[href="/knowledge-bases/kb-1/settings"]').exists(),
    ).toBe(false)
  })

  it('loads document pages on demand and filters tasks by knowledge base', async () => {
    apiMocks.listDocs
      .mockResolvedValueOnce(
        pageEnvelopeWithCursor(
          [documentView('doc-1', 'first.md')],
          'cursor-docs',
        ),
      )
      .mockResolvedValueOnce(
        pageEnvelopeWithCursor([documentView('doc-2', 'second.md')], null),
      )

    const wrapper = await mountPage('member')

    expect(apiMocks.listDocs).toHaveBeenNthCalledWith(
      1,
      'team-1',
      'kb-1',
      null,
      20,
      '',
    )
    expect(apiMocks.listDocs).toHaveBeenCalledTimes(1)
    const more = wrapper.findAll('button').find((button) => button.text() === '加载更多文档')!
    await more.trigger('click')
    await flushPromises()
    expect(apiMocks.listDocs).toHaveBeenNthCalledWith(
      2,
      'team-1',
      'kb-1',
      'cursor-docs',
      20,
      '',
    )
    expect(wrapper.text()).toContain('first.md')
    expect(wrapper.text()).toContain('second.md')
    expect(apiMocks.listIngestions).toHaveBeenCalledWith('team-1', null, 5, 'kb-1')
  })
  it('edits the title in place and can cancel without saving', async () => {
    const wrapper = await mountPage('leader')
    await wrapper.get('[data-testid="kb-inline-edit"]').trigger('click')
    await setControlValue(control(wrapper, '[data-testid="kb-inline-name"]'), '新版 Java 资料')
    const cancel = wrapper.findAll('button').find((button) => button.text() === '取消')!
    await cancel.trigger('click')
    expect(apiMocks.updateKb).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Java 资料')
    await wrapper.get('[data-testid="kb-inline-edit"]').trigger('click')
    apiMocks.updateKb.mockResolvedValue({ ...kb, name: '新版 Java 资料', version: 2 })
    await setControlValue(control(wrapper, '[data-testid="kb-inline-name"]'), '新版 Java 资料')
    await wrapper.get('[data-testid="kb-inline-save"]').trigger('click')
    await flushPromises()
    expect(apiMocks.updateKb).toHaveBeenCalledWith({ team_id: 'team-1', kb_id: 'kb-1', name: '新版 Java 资料', description: kb.description }, 1)
    expect(wrapper.text()).toContain('新版 Java 资料')
  })

  it('searches documents when Enter is pressed', async () => {
    const wrapper = await mountPage('member')
    const input = wrapper.get('input[placeholder="搜索文件名"]')
    await input.setValue(' records ')
    await input.trigger('keydown', { key: 'Enter', code: 'Enter', keyCode: 13 })
    await flushPromises()
    expect(apiMocks.listDocs).toHaveBeenLastCalledWith('team-1', 'kb-1', null, 20, 'records')
    wrapper.unmount()
  })

})
