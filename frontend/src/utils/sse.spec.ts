import { parseSseEventBlock, readSseEvents } from './sse'

describe('SSE utilities', () => {
  it('parses named events and JSON payloads', () => {
    expect(
      parseSseEventBlock(
        'id: 7\nevent: progress\ndata: {"run_id":"run-1","percent":40}',
      ),
    ).toEqual({
      event: 'progress',
      id: '7',
      data: { run_id: 'run-1', percent: 40 },
      raw: '{"run_id":"run-1","percent":40}',
    })
  })

  it('retains non-JSON diagnostic data', () => {
    expect(
      parseSseEventBlock('event: error\ndata: queue unavailable'),
    ).toMatchObject({
      event: 'error',
      data: { content: 'queue unavailable' },
    })
  })

  it('handles event boundaries split across network chunks', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: progress\ndata: {"percent":'))
        controller.enqueue(
          encoder.encode('40}\n\nevent: completed\ndata: {"percent":100}\n\n'),
        )
        controller.close()
      },
    })
    const events: string[] = []

    await readSseEvents(new Response(stream), (event) => {
      events.push(`${event.event}:${String(event.data.percent)}`)
    })

    expect(events).toEqual(['progress:40', 'completed:100'])
  })
})

it.each(['\r\n', '\r', '\n'])(
  'reads byte-fragmented UTF-8 events with %j endings',
  async (ending) => {
    const bytes = new TextEncoder().encode(
      `event: token${ending}data: {"content":"中文"}${ending}${ending}event: done${ending}data: {}${ending}${ending}`,
    )
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
        controller.close()
      },
    })
    const events: unknown[] = []
    await readSseEvents(new Response(stream), (event) => {
      events.push([event.event, event.data])
    })
    expect(events).toEqual([
      ['token', { content: '中文' }],
      ['done', {}],
    ])
    expect(stream.locked).toBe(false)
  },
)

it('cancels the stream and releases its reader when the consumer fails', async () => {
  const cancel = vi.fn()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {}\n\n'))
    },
    cancel,
  })
  const failure = new Error('consumer failed')
  await expect(
    readSseEvents(new Response(stream), () => {
      throw failure
    }),
  ).rejects.toBe(failure)
  expect(cancel).toHaveBeenCalledWith(failure)
  expect(stream.locked).toBe(false)
})
