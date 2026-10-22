import { appRoutes } from './index'

import type { RouteRecordRaw } from 'vue-router'

function flattenRoutes(routes: RouteRecordRaw[], parent = ''): RouteRecordRaw[] {
  return routes.flatMap((route) => {
    const path = route.path.startsWith('/')
      ? route.path
      : `${parent}/${route.path}`.replace(/\/+/g, '/')
    return [
      { ...route, path },
      ...(route.children ? flattenRoutes(route.children, path) : []),
    ]
  })
}

describe('P0 routes', () => {
  it.each([
    ['/chats', 'chat-history'],
    ['/knowledge-bases/:kbId', 'knowledge-base-detail'],
    ['/knowledge-bases/:kbId/settings', 'knowledge-base-policy'],
    ['/documents/:documentId/versions/:versionId', 'document-version'],
    ['/tasks', 'tasks'],
    ['/tasks/:runId', 'task-detail'],
    ['/chunks', 'chunks'],
    ['/chunks/:chunkId', 'chunk-detail'],
    ['/traces', 'traces'],
    ['/traces/:traceId', 'trace-detail'],
    ['/evaluations', 'evaluations'],
    ['/evaluations/:datasetId', 'evaluation-detail'],
    ['/evaluations/runs/:runId', 'evaluation-run'],
    ['/settings/team', 'team-settings'],
    ['/settings/model-policy', 'model-policy'],
    ['/settings/providers', 'providers'],
    ['/settings/audit', 'audit'],
    ['/settings/index-generations', 'index-generations'],
    ['/settings/members', 'members'],
    ['/invite/:token', 'invite'],
    ['/admin/model-policy', 'admin-model-policy'],
    ['/admin/model-providers', 'admin-model-providers'],
    ['/admin/audit', 'admin-audit'],
    ['/admin/audit/:auditId', 'admin-audit-detail'],
    ['/admin/system', 'admin-system'],
  ])('registers %s as %s', (path, name) => {
    const route = flattenRoutes(appRoutes).find((item) => item.path === path)
    expect(route?.name).toBe(name)
  })
})
