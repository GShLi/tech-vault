import { api, http } from './client'

describe('P0 API client coverage', () => {
  it.each([
    'createInvitation',
    'getInvitation',
    'acceptInvitation',
    'listFacets',
    'transferDocuments',
    'listKbMembers',
    'updateKbMembers',
    'listIngestions',
    'getIngestionRun',
    'retryIngestion',
    'cancelIngestion',
    'listDocumentVersions',
    'getDocumentVersion',
    'listDocumentChunks',
    'listDocumentGrants',
    'downloadDocument',
    'deleteDocument',
    'restoreDocument',
    'listTraces',
    'getTrace',
    'exportTrace',
    'listEvalDatasets',
    'getEvalDataset',
    'listEvalCases',
    'createEvalCase',
    'updateEvalCase',
    'deleteEvalCase',
    'importEvalCases',
    'listEvalRuns',
    'startEvalRun',
    'getEvalRun',
    'cancelEvalRun',
    'getEvalReport',
    'getPolicy',
    'updatePolicy',
    'listProviders',
    'createProvider',
    'testProvider',
    'getAdminPolicy',
    'updateAdminPolicy',
    'listAdminProviders',
    'createAdminProvider',
    'updateAdminProvider',
    'listAudit',
    'getAudit',
    'listGenerations',
    'getGeneration',
    'reindexGeneration',
    'validateGeneration',
    'activateGeneration',
    'rollbackGeneration',
    'getChunk',
    'updateChunk',
    'regenerateChunks',
    'getChunkHistory',
    'getHealth',
    'getReady',
    'getVersion',
    'getKb',
    'getKbPolicy',
    'updateKbPolicy',
  ])('exposes %s', (method) => {
    expect(typeof (api as unknown as Record<string, unknown>)[method]).toBe(
      'function',
    )
  })

  it('submits generation reindex scope in the request body', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({
      data: {
        data: {
          generation: { id: 'generation-1', status: 'staging' },
          run: { generation_id: 'generation-1', status: 'queued' },
        },
      },
    } as never)

    await api.reindexGeneration('team-1')

    expect(post.mock.calls[0][0]).toBe('/generations/reindex')
    expect(post.mock.calls[0][1]).toEqual({ team_id: 'team-1' })
    post.mockRestore()
  })

  it('passes pagination parameters and returns the page envelope', async () => {
    const get = vi.spyOn(http, 'get').mockResolvedValue({
      data: {
        data: [],
        meta: {
          next_cursor: 'next-page',
          has_more: true,
          request_id: 'req-page',
        },
      },
    } as never)

    const page = await api.listMessages('team-1', 'chat-1', 'cursor-1', 25)

    expect(get).toHaveBeenCalledWith('/chats/messages', {
      params: {
        team_id: 'team-1',
        chat_id: 'chat-1',
        limit: 25,
        cursor: 'cursor-1',
      },
    })
    expect(page.meta.next_cursor).toBe('next-page')
    expect(page.meta.has_more).toBe(true)
    get.mockRestore()
  })

  it('deletes and restores documents with identifiers in the request body', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({
      data: {
        data: {
          id: 'document-1',
          doc_status: 'deleted',
          deleted_at: '2026-10-19T12:00:00+00:00',
          purged_at: null,
        },
      },
    } as never)

    await api.deleteDocument('team-1', 'document-1')
    await api.restoreDocument('team-1', 'document-1')

    expect(post.mock.calls[0].slice(0, 2)).toEqual([
      '/docs/delete',
      { team_id: 'team-1', document_id: 'document-1' },
    ])
    expect(post.mock.calls[1].slice(0, 2)).toEqual([
      '/docs/restore',
      { team_id: 'team-1', document_id: 'document-1' },
    ])
    post.mockRestore()
  })
})
