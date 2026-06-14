import type { Component } from 'vue'
import {
  Avatar,
  Bell,
  Collection,
  Connection,
  Cpu,
  DataLine,
  Document,
  Files,
  Grid,
  Histogram,
  List,
  Menu as MenuIcon,
  Monitor,
  OfficeBuilding,
  Postcard,
  Setting,
  SetUp,
  Timer,
  Tools,
  Upload,
  User,
  UserFilled,
} from '@element-plus/icons-vue'

/**
 * 若依 svg 图标名 → Element Plus 图标组件映射。
 * 后端 RouterMeta.icon 是 RuoYi svg 命名（与 EP 图标体系不对齐），此处做语义近似映射，
 * 未命中回退 Menu 图标（折叠侧栏靠图标，不能空）。
 */
const ICON_MAP: Record<string, Component> = {
  system: Setting,
  user: User,
  peoples: UserFilled,
  role: Avatar, // _resource_menu icon=resource → 角色菜单 icon="role"（补全：原落兜底方格）
  menu: Grid, // 菜单管理 icon="menu"（补全）
  tree: OfficeBuilding,
  'tree-table': OfficeBuilding,
  dept: OfficeBuilding,
  post: Postcard,
  dict: Collection,
  config: SetUp, // 参数管理 icon="config"（补全）
  edit: Document,
  form: Document,
  message: Bell,
  notice: Bell, // 通知公告 icon="notice"（补全）
  monitor: Monitor,
  server: Cpu,
  redis: DataLine,
  'redis-list': DataLine,
  online: Connection,
  job: Timer,
  log: List,
  logininfor: List,
  upload: Upload,
  build: Tools,
  chart: Histogram,
  file: Files,
}

export function resolveMenuIcon(name: string | undefined | null): Component {
  if (!name) return MenuIcon
  return ICON_MAP[name] ?? MenuIcon
}
