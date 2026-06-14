<script setup lang="ts">
/**
 * 分配岗位对话框：打开时并发拉「全部岗位（选项）」+「该用户已绑定岗位 id」，
 * el-transfer 编辑后 setUserPosts 全量替换。
 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listPosts, type PostRead } from '@/api/posts'
import { getUserPosts, setUserPosts } from '@/api/users'

const props = defineProps<{
  /** 目标用户 id；null = 未选中（对话框不应打开）。 */
  userId: number | null
}>()

const visible = defineModel<boolean>('visible', { required: true })

interface TransferOption {
  key: number
  label: string
}

const options = ref<TransferOption[]>([])
const selected = ref<number[]>([])
const loading = ref(false)
const submitting = ref(false)

watch(visible, async (open) => {
  if (!open || props.userId === null) return
  loading.value = true
  try {
    const [postPage, binding] = await Promise.all([
      listPosts({ page: 1, size: 100 }),
      getUserPosts(props.userId),
    ])
    options.value = postPage.items.map((post: PostRead) => ({
      key: post.id,
      label: `${post.name}（${post.code}）`,
    }))
    selected.value = binding.ids
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '加载岗位失败')
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  if (props.userId === null) return
  submitting.value = true
  try {
    await setUserPosts(props.userId, selected.value)
    ElMessage.success('岗位分配成功')
    visible.value = false
  } catch (err) {
    ElMessage.error((err as { message?: string }).message ?? '分配失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="分配岗位"
    width="560px"
    append-to-body
    :close-on-click-modal="false"
  >
    <el-transfer
      v-model="selected"
      v-loading="loading"
      :data="options"
      :titles="['可选岗位', '已分配']"
      filterable
    />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
    </template>
  </el-dialog>
</template>
