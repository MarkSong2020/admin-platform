import { describe, it, expect } from 'vitest'
import seedPages from '../../../tests/contracts/seed_page_components.json'
import { pageComponentKeys } from './dynamic-routes'

describe('seed 页面组件覆盖契约', () => {
  it('seed_page_components.json ⊆ import.meta.glob 页面 key 集合（大小写精确）', () => {
    const globKeys = new Set(pageComponentKeys())
    const missing = (seedPages as string[]).filter((c) => !globKeys.has(c))
    expect(missing, `缺少页面组件: ${missing.join(', ')}`).toEqual([])
  })
})
