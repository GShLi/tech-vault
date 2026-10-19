<script setup lang="ts">
import { computed } from 'vue'

import { statusLabel } from '@/utils/format'

const props = defineProps<{
  status: string | null | undefined
  label?: string
}>()

const tone = computed(() => {
  const value = props.status ?? ''
  if (['active', 'completed', 'ready', 'validated', 'enabled', 'local_only'].includes(value)) {
    return 'success'
  }
  if (['failed', 'disabled', 'cancelled', 'refused'].includes(value)) {
    return 'danger'
  }
  if (['building', 'queued', 'running', 'validating', 'generating', 'degraded'].includes(value)) {
    return 'warning'
  }
  return 'neutral'
})
</script>

<template>
  <span class="status-pill" :class="`status-${tone}`">
    {{ label ?? statusLabel(status) }}
  </span>
</template>
