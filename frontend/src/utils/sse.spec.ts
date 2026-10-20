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
    expect(parseSseEventBlock('event: error\ndata: queue unavailable')).toMatchObject({
      event: 'error',
      data: { content: 'queue unavailable' },
    })
  })

  it('handles event boundaries split across network chunks', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: progress\ndata: {"percent":'))
        controller.enqueue(encoder.encode('40}\n\nevent: completed\ndata: {"percent":100}\n\n'))
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
