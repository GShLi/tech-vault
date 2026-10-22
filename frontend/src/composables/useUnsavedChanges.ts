import { onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { Modal } from '@arco-design/web-vue'
import { useTeamStore } from '@/stores/team'

export function confirmAction(title: string, content: string): Promise<boolean> {
  return new Promise((resolve) => Modal.confirm({
    title, content, okText: '确认', cancelText: '取消',
    onOk: () => { resolve(true) }, onCancel: () => { resolve(false) },
  }))
}

export function useUnsavedChanges(dirty: () => boolean, discard: () => void, message = '离开后未保存的修改将丢失。是否继续？') {
  const team = useTeamStore()
  async function guard() {
    if (!dirty()) return true
    if (!await confirmAction('离开当前页面', message)) return false
    discard()
    return true
  }
  function beforeUnload(event: BeforeUnloadEvent) {
    if (dirty()) { event.preventDefault(); event.returnValue = '' }
  }
  team.beforeChange = guard
  onBeforeRouteLeave(guard)
  onBeforeRouteUpdate(guard)
  window.addEventListener('beforeunload', beforeUnload)
  onBeforeUnmount(() => {
    if (team.beforeChange === guard) team.beforeChange = null
    window.removeEventListener('beforeunload', beforeUnload)
  })
  return guard
}
