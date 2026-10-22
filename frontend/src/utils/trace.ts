export interface TraceStageMeta {
  label: string
  description: string
}

const stageMetadata: Record<string, TraceStageMeta> = {
  policy_ms: {
    label: '策略校验',
    description: '解析模型路由、数据分级和可用供应商策略',
  },
  rewrite_ms: {
    label: '查询改写',
    description: '结合会话上下文补全或重写用户问题',
  },
  embedding_ms: {
    label: '查询向量化',
    description: '调用 Embedding 模型生成查询向量',
  },
  bm25_ms: {
    label: '关键词检索',
    description: '使用 BM25 从 Elasticsearch 召回关键词匹配片段',
  },
  dense_ms: {
    label: '向量检索',
    description: '使用查询向量从 Qdrant 召回语义相近片段',
  },
  retrieval_ms: {
    label: '混合检索',
    description: '执行关键词与向量召回、融合和候选筛选',
  },
  rerank_ms: {
    label: '重排序',
    description: '按问题相关性重新排序候选片段',
  },
  generation_ms: {
    label: '答案生成',
    description: '组装上下文并生成带引用的最终回答',
  },
  gateway_query_rewrite_ms: {
    label: '改写模型调用',
    description: '调用模型服务完成查询改写',
  },
  gateway_embedding_ms: {
    label: '向量化调用',
    description: '调用 Embedding 模型生成查询向量',
  },
  gateway_rerank_ms: {
    label: '重排序调用',
    description: '调用 Rerank 模型计算候选相关性',
  },
  gateway_answer_ms: {
    label: '生成模型调用',
    description: '调用答案模型生成最终回答',
  },
}

function trimFixed(value: number, digits: number): string {
  return value
    .toFixed(digits)
    .replace(/\.0+$/, '')
    .replace(/(\.\d*?)0+$/, '$1')
}

export function formatTraceDuration(value?: number | null): string {
  if (value == null || !Number.isFinite(value) || value < 0) return '—'
  if (value === 0) return '0 ms'
  if (value < 1) return '<1 ms'
  if (value < 1000) {
    return `${trimFixed(value, value < 100 ? 2 : 0)} ms`
  }
  if (value < 60_000) {
    return `${trimFixed(value / 1000, 2)} s`
  }
  if (value < 3_600_000) {
    return `${trimFixed(value / 60_000, 2)} min`
  }
  return `${trimFixed(value / 3_600_000, 2)} h`
}

export function traceStageMeta(key: string): TraceStageMeta {
  const known = stageMetadata[key]
  if (known) return known
  return {
    label: key.endsWith('_ms') ? key.slice(0, -3) : key,
    description: '自定义检索阶段耗时',
  }
}

const stageParents: Array<[string, string]> = [
  ['bm25_ms', 'retrieval_ms'],
  ['dense_ms', 'retrieval_ms'],
  ['gateway_query_rewrite_ms', 'rewrite_ms'],
  ['gateway_embedding_ms', 'embedding_ms'],
  ['gateway_rerank_ms', 'rerank_ms'],
  ['gateway_answer_ms', 'generation_ms'],
]

export function traceStageParent(
  key: string,
  latencies: Record<string, number>,
): string | null {
  const parent = stageParents.find(([child]) => child === key)?.[1]
  return parent && latencies[parent] != null ? parent : null
}

export function traceTotalDuration(latencies: Record<string, number>): number {
  return Object.entries(latencies).reduce((sum, [key, value]) => {
    if (traceStageParent(key, latencies) != null || !Number.isFinite(value))
      return sum
    return sum + Math.max(0, value)
  }, 0)
}
