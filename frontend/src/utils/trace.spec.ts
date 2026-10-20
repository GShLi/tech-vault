import { formatTraceDuration, traceStageMeta, traceTotalDuration } from './trace'

describe('trace duration formatting', () => {
  it.each([
    [0.42, '<1 ms'],
    [9.126, '9.13 ms'],
    [38.6635420000232, '38.66 ms'],
    [786.4, '786 ms'],
    [1250, '1.25 s'],
    [61000, '1.02 min'],
    [3660000, '1.02 h'],
  ])('formats %s ms as %s', (value, expected) => {
    expect(formatTraceDuration(value)).toBe(expected)
  })

  it('maps technical stage keys to Chinese names and descriptions', () => {
    expect(traceStageMeta('gateway_embedding_ms')).toEqual({
      label: '向量化调用',
      description: '调用 Embedding 模型生成查询向量',
    })
    expect(traceStageMeta('retrieval_ms').label).toBe('混合检索')
    expect(traceStageMeta('bm25_ms').label).toBe('关键词检索')
    expect(traceStageMeta('dense_ms').label).toBe('向量检索')
    expect(traceStageMeta('custom_stage_ms')).toEqual({
      label: 'custom_stage',
      description: '自定义检索阶段耗时',
    })
  })

  it('avoids double counting retrieval children and gateway aliases', () => {
    expect(
      traceTotalDuration({
        bm25_ms: 10,
        dense_ms: 5,
        retrieval_ms: 20,
        rewrite_ms: 3,
        gateway_query_rewrite_ms: 3,
        gateway_embedding_ms: 7,
      }),
    ).toBe(30)
  })
})
