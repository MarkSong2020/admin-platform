<script setup lang="ts">
/**
 * 菜单新增 / 编辑对话框（类型联动）。
 * menu_type M/C/F 决定显示哪些字段（用 computed 控制各 el-form-item v-if）：
 * - M 目录：name / path / icon / sort / visible
 * - C 菜单：+ component + perms（在 M 基础上加组件路径与权限标识）
 * - F 按钮：仅 name / perms / sort（无 path / component / icon / visible）
 * parent_id 用 el-tree-select 从菜单树选（可空=顶级）。
 */
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { createMenu, updateMenu, type MenuRead } from '@/api/menus'
import { buildTree, type TreeNode } from '@/composables/useTree'

const props = withDefaults(
  defineProps<{
    /** 被编辑的菜单；null = 新增模式。 */
    editing: MenuRead | null
    /** 全部菜单平铺列表，用于构建父菜单选择树。 */
    menus: MenuRead[]
    /** 新增子级时预置的父菜单 id（仅新增模式生效，null=顶级）。 */
    presetParentId?: number | null
  }>(),
  { presetParentId: null },
)

const visible = defineModel<boolean>('visible', { required: true })

const emit = defineEmits<{
  /** 提交成功，父组件据此刷新列表。 */
  (e: 'saved'): void
}>()

const isEdit = computed(() => props.editing !== null)
const formRef = ref<FormInstance>()
const submitting = ref(false)

type MenuType = 'M' | 'C' | 'F'

interface FormModel {
  name: string
  menuType: MenuType
  parentId: number | null
  path: string
  component: string
  perms: string
  icon: string
  sortOrder: number
  visible: boolean
  status: 'active' | 'disabled'
}

const form = reactive<FormModel>({
  name: '',
  menuType: 'M',
  parentId: null,
  path: '',
  component: '',
  perms: '',
  icon: '',
  sortOrder: 0,
  visible: true,
  status: 'active',
})

// 类型联动：各字段是否显示
const showPath = computed(() => form.menuType !== 'F') // M/C 有路由地址
const showComponent = computed(() => form.menuType === 'C') // 仅 C 有组件路径
const showPerms = computed(() => form.menuType !== 'M') // C/F 有权限标识
const showIcon = computed(() => form.menuType !== 'F') // M/C 有图标
const showVisible = computed(() => form.menuType !== 'F') // M/C 有显示开关

const rules = computed<FormRules<FormModel>>(() => ({
  name: [{ required: true, message: '请输入菜单名称', trigger: 'blur' }],
}))

/** el-tree-select 数据：菜单树（按 name 显示）。 */
const treeData = computed<TreeNode<MenuRead>[]>(() => buildTree(props.menus))

// 打开时按模式回填表单
watch(visible, (open) => {
  if (!open) return
  formRef.value?.clearValidate()
  const editing = props.editing
  if (editing) {
    form.name = editing.name
    form.menuType = (editing.menu_type as MenuType) ?? 'M'
    form.parentId = editing.parent_id
    form.path = editing.path ?? ''
    form.component = editing.component ?? ''
    form.perms = editing.perms ?? ''
    form.icon = editing.icon ?? ''
    form.sortOrder = editing.sort_order
    form.visible = editing.visible
    form.status = editing.status === 'disabled' ? 'disabled' : 'active'
  } else {
    form.name = ''
    form.menuType = 'M'
    form.parentId = props.presetParentId
    form.path = ''
    form.component = ''
    form.perms = ''
    form.icon = ''
    form.sortOrder = 0
    form.visible = true
    form.status = 'active'
  }
})

async function submit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (props.editing) {
      await updateMenu(props.editing.id, {
        name: form.name,
        menu_type: form.menuType,
        parent_id: form.parentId,
        path: showPath.value ? form.path : '',
        component: showComponent.value ? form.component || null : null,
        perms: showPerms.value ? form.perms || null : null,
        icon: showIcon.value ? form.icon : '',
        sort_order: form.sortOrder,
        visible: showVisible.value ? form.visible : true,
        status: form.status,
      })
    } else {
      await createMenu({
        name: form.name,
        menu_type: form.menuType,
        parent_id: form.parentId,
        path: showPath.value ? form.path : '',
        component: showComponent.value ? form.component || null : null,
        perms: showPerms.value ? form.perms || null : null,
        icon: showIcon.value ? form.icon : '',
        sort_order: form.sortOrder,
        visible: showVisible.value ? form.visible : true,
        status: form.status,
      })
    }
    ElMessage.success(isEdit.value ? '修改成功' : '新增成功')
    visible.value = false
    emit('saved')
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑菜单' : '新增菜单'"
    width="520px"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="菜单类型" prop="menuType">
        <el-radio-group v-model="form.menuType">
          <el-radio value="M">目录</el-radio>
          <el-radio value="C">菜单</el-radio>
          <el-radio value="F">按钮</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="上级菜单" prop="parentId">
        <el-tree-select
          v-model="form.parentId"
          :data="treeData"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          check-strictly
          clearable
          placeholder="不选则为顶级菜单"
          class="full-width"
        />
      </el-form-item>
      <el-form-item label="菜单名称" prop="name">
        <el-input v-model="form.name" placeholder="菜单名称" />
      </el-form-item>
      <el-form-item v-if="showIcon" label="菜单图标" prop="icon">
        <el-input v-model="form.icon" placeholder="图标标识" />
      </el-form-item>
      <el-form-item v-if="showPath" label="路由地址" prop="path">
        <el-input v-model="form.path" placeholder="路由地址" />
      </el-form-item>
      <el-form-item v-if="showComponent" label="组件路径" prop="component">
        <el-input v-model="form.component" placeholder="如 system/user/index" />
      </el-form-item>
      <el-form-item v-if="showPerms" label="权限标识" prop="perms">
        <el-input v-model="form.perms" placeholder="如 system:user:list" />
      </el-form-item>
      <el-form-item label="显示顺序" prop="sortOrder">
        <el-input-number v-model="form.sortOrder" :min="0" controls-position="right" />
      </el-form-item>
      <el-form-item v-if="showVisible" label="显示状态" prop="visible">
        <el-switch v-model="form.visible" active-text="显示" inactive-text="隐藏" />
      </el-form-item>
      <el-form-item v-if="isEdit" label="状态" prop="status">
        <el-radio-group v-model="form.status">
          <el-radio value="active">正常</el-radio>
          <el-radio value="disabled">停用</el-radio>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.full-width {
  width: 100%;
}
</style>
