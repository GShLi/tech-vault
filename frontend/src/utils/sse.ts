export interface ParsedSseEvent {
  event: string
  id: string
  data: Record<string, unknown>
  raw: string
}

export function parseSseEventBlock(block: string): ParsedSseEvent | null {
  let event = 'message'
  let id = ''
  const dataLines: string[] = []

  for (const line of block.replace(/\r\n|\r/g, '\n').split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon >= 0 ? line.slice(0, colon) : line
    let value = colon >= 0 ? line.slice(colon + 1) : ''
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    if (field === 'id') id = value
    if (field === 'data') dataLines.push(value)
  }

  const raw = dataLines.join('\n')
  if (!raw) return null

  let data: Record<string, unknown> = { content: raw }
  try {
    const parsed = JSON.parse(raw) as unknown
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      data = parsed as Record<string, unknown>
    } else if (parsed !== undefined && parsed !== null) {
      data = { content: String(parsed) }
    }
  } catch {
    // Non-JSON data is retained verbatim so diagnostics stay visible.
  }

  return { event, id, data, raw }
}

export async function readSseEvents(
  response: Response,
  onEvent: (event: ParsedSseEvent) => void | Promise<void>,
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('浏览器不支持事件流读取。')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = async (block: string): Promise<void> => {
    const event = parseSseEventBlock(block)
    if (event) await onEvent(event)
  }

  // Normalize line endings across reads: CR and LF may arrive in different chunks.
  let previousWasCr = false
  const append = (text: string): void => {
    for (const char of text) {
      if (char === '\n' && previousWasCr) {
        previousWasCr = false
        continue
      }
      buffer += char === '\r' ? '\n' : char
      previousWasCr = char === '\r'
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      append(done ? decoder.decode() : decoder.decode(value, { stream: true }))
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        if (block.trim()) await dispatch(block)
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
    if (buffer.trim()) await dispatch(buffer)
  } catch (error) {
    // Stop the transport if the consumer fails, without masking its original error.
    await reader.cancel(error).catch(() => undefined)
    throw error
  } finally {
    reader.releaseLock()
  }
}
