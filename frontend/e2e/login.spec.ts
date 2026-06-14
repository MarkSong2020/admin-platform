import { test, expect } from '@playwright/test'

/**
 * 登录闭环 E2E（对真实后端 + 真实浏览器）。
 * 覆盖单测/组件测覆盖不到的集成面：登录 → 取 token → getInfo/getRouters →
 * 动态路由装配 → 业务页对真实后端取数渲染。
 * 需后端（:8000）+ 前端 dev(:5173) 运行；超管账号 admin / Admin@123456。
 */

/** 解算术验证码题面（如 "9 + 8 = ?"）→ 答案字符串。模块级，避免 test 体内条件分支。 */
function solveCaptcha(question: string): string {
  const m = question.match(/(-?\d+)\s*([+\-*])\s*(-?\d+)/)
  if (!m) throw new Error(`验证码题面非算术式: ${question}`)
  const ops: Record<string, (x: number, y: number) => number> = {
    '+': (x, y) => x + y,
    '-': (x, y) => x - y,
    '*': (x, y) => x * y,
  }
  const op = ops[m[2]!]
  if (!op) throw new Error(`未知验证码运算符: ${m[2]}`)
  return String(op(Number(m[1]), Number(m[3])))
}

test.describe('登录闭环', () => {
  test('未登录访问根路径 → 守卫重定向登录页（带 redirect 回跳参数）', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login\?redirect=/)
    await expect(page.getByPlaceholder('用户名')).toBeVisible()
  })

  test('登录 → 进入后台 → 动态路由页（用户管理）加载真后端数据', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('用户名').fill('admin')
    await page.getByPlaceholder('密码').fill('Admin@123456')

    // 算术验证码必现（登录页 onMounted 必拉取并展示）：解答后填入
    await expect(page.locator('.login-captcha-question')).toBeVisible()
    const question = (await page.locator('.login-captcha-question').textContent()) ?? ''
    await page.getByPlaceholder('计算结果').fill(solveCaptcha(question))

    await page.locator('.login-submit').click()

    // 登录成功 → 离开登录页（动态路由装配后落 /home）
    await expect(page).not.toHaveURL(/\/login/, { timeout: 15000 })
    // 侧边栏出现"系统管理"菜单 = getRouters 动态路由装配成功
    await expect(page.getByText('系统管理').first()).toBeVisible({ timeout: 10000 })

    // 进用户管理（动态路由）→ 表格渲染出 admin（真后端 GET /users 200，#18 已修）
    await page.goto('/system/user')
    await expect(page.locator('.el-table')).toContainText('admin', { timeout: 10000 })
  })
})
