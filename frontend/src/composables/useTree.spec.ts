import { describe, it, expect } from 'vitest'
import { buildTree, type TreeNodeLike } from './useTree'

interface Dept extends TreeNodeLike {
  name: string
}

describe('buildTree', () => {
  it('平铺 → 单层森林（多根，保持顺序）', () => {
    const flat: Dept[] = [
      { id: 1, parent_id: null, name: 'A' },
      { id: 2, parent_id: null, name: 'B' },
    ]
    const tree = buildTree(flat)
    expect(tree.map((n) => n.id)).toEqual([1, 2])
    expect(tree[0]!.children).toBeUndefined()
  })

  it('多级嵌套：子挂到正确父下', () => {
    const flat: Dept[] = [
      { id: 1, parent_id: null, name: '根' },
      { id: 2, parent_id: 1, name: '子' },
      { id: 3, parent_id: 2, name: '孙' },
      { id: 4, parent_id: 1, name: '子2' },
    ]
    const tree = buildTree(flat)
    expect(tree).toHaveLength(1)
    const root = tree[0]!
    expect(root.children?.map((n) => n.id)).toEqual([2, 4])
    const child = root.children!.find((n) => n.id === 2)!
    expect(child.children?.map((n) => n.id)).toEqual([3])
  })

  it('孤儿（parent_id 指向不存在的 id）作根节点不丢弃', () => {
    const flat: Dept[] = [
      { id: 1, parent_id: null, name: '根' },
      { id: 2, parent_id: 999, name: '孤儿' },
    ]
    const tree = buildTree(flat)
    expect(tree.map((n) => n.id).sort()).toEqual([1, 2])
  })

  it('空数组 → 空森林', () => {
    expect(buildTree([])).toEqual([])
  })

  it('不修改入参元素（不挂 children 到原对象）', () => {
    const flat: Dept[] = [
      { id: 1, parent_id: null, name: '根' },
      { id: 2, parent_id: 1, name: '子' },
    ]
    buildTree(flat)
    expect('children' in flat[0]!).toBe(false)
  })
})
