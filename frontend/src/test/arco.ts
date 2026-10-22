import { isVNode, type VNode } from 'vue'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

/** Resolve the public control, rather than an internal component sharing its root. */
export function control(
  wrapper: VueWrapper,
  selector: string,
): VueWrapper<any> {
  for (const name of [
    'Select',
    'Checkbox',
    'Switch',
    'InputPassword',
    'Input',
    'Textarea',
  ]) {
    const testId = selector.match(/data-testid="([^"]+)"/)?.[1]
    const match = wrapper
      .findAllComponents({ name })
      .find((item) =>
        testId
          ? item.vm.$attrs['data-testid'] === testId
          : item.element.matches(selector),
      )
    if (match) return match
  }
  throw new Error(`Arco control not found: ${selector}`)
}

export async function setControlValue(
  component: VueWrapper<any>,
  value: unknown,
): Promise<void> {
  const name = component.vm.$options.name
  if (name === 'Checkbox') {
    await component.get('input[type="checkbox"]').setValue(value)
  } else if (name === 'Switch') {
    if (component.props('modelValue') !== value)
      await component.trigger('click')
  } else if (name === 'Select') {
    await component.setValue(value)
    component.vm.$emit('change', value)
  } else {
    await component
      .get(name === 'Textarea' ? 'textarea' : 'input')
      .setValue(value)
  }
  await flushPromises()
}

// Arco's JSX Teleport slot is not rendered by VTU's Teleport stub. Inspect the
// declared options here; the real dropdown is also checked in the browser.
export async function selectOptions(
  select: Pick<VueWrapper, 'vm'>,
): Promise<Array<{ value: unknown; label: string }>> {
  const result: Array<{ value: unknown; label: string }> = []
  function children(node: VNode): unknown {
    return typeof node.children === 'object' &&
      node.children &&
      !Array.isArray(node.children)
      ? typeof node.children.default === 'function'
        ? node.children.default()
        : []
      : node.children
  }
  function text(value: unknown): string {
    if (Array.isArray(value)) return value.map(text).join('')
    if (isVNode(value)) return text(children(value))
    return typeof value === 'string' ? value : ''
  }
  function visit(value: unknown): void {
    if (Array.isArray(value)) return value.forEach(visit)
    if (!isVNode(value)) return
    if (
      typeof value.type === 'object' &&
      'name' in value.type &&
      value.type.name === 'Option'
    ) {
      result.push({
        value: value.props?.value,
        label: text(children(value)).trim(),
      })
    } else {
      visit(children(value))
    }
  }
  visit(select.vm.$slots.default?.())
  return result
}
