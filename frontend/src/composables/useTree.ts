/**
 * 平铺列表 → 树工具。后端 dept/menu 等 list 返回分页平铺（无独立树端点），
 * 前端按 parent_id 自组树供 el-table 树形 / el-tree-select 使用。
 * 纯函数无副作用，dept / menu 页共用。
 */

/** 可组树的最小形状：自带主键 id 与父指针 parent_id（null=根）。 */
export interface TreeNodeLike {
  id: number
  parent_id: number | null
}

/** 组树结果：在原节点上挂 children（仅有子节点时存在）。 */
export type TreeNode<T> = T & { children?: TreeNode<T>[] }

/**
 * 把平铺数组按 parent_id 组成森林（多根）。
 * - 保持输入顺序（同一父下子节点按原顺序排列）。
 * - 孤儿（parent_id 指向不存在的 id）视为根节点，不丢弃。
 * - 不修改入参元素（浅拷贝挂 children），入参保持只读。
 */
export function buildTree<T extends TreeNodeLike>(items: T[]): TreeNode<T>[] {
  const nodeById = new Map<number, TreeNode<T>>()
  for (const item of items) {
    nodeById.set(item.id, { ...item })
  }

  const roots: TreeNode<T>[] = []
  for (const item of items) {
    const node = nodeById.get(item.id)!
    const parent = item.parent_id !== null ? nodeById.get(item.parent_id) : undefined
    if (parent) {
      ;(parent.children ??= []).push(node)
    } else {
      // parent_id 为 null，或指向不存在的父（孤儿）→ 作根节点
      roots.push(node)
    }
  }
  return roots
}
