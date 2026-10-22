/** Map domain statuses to Arco tag colors; labels live in utils/format. */
export function statusColor(
  status: string | null | undefined,
): string | undefined {
  if (
    [
      'active',
      'completed',
      'ready',
      'validated',
      'enabled',
      'local_only',
    ].includes(status ?? '')
  ) {
    return 'green'
  }
  if (['failed', 'upload_failed', 'disabled', 'cancelled', 'refused'].includes(status ?? '')) {
    return 'red'
  }
  if (
    [
      'building',
      'uploading',
      'processing',
      'prepared',
      'partial_failed',
      'queued',
      'running',
      'validating',
      'generating',
      'degraded',
    ].includes(status ?? '')
  ) {
    return 'orange'
  }
  return undefined
}
