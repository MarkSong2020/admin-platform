import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchUserInfo, type UserInfoUser } from '@/api/auth'
import { usePermissionStore } from './permission'

/** 当前用户身份 + 角色 code（getInfo）；permissions 写入 permission store。spec §5/§6。 */
export const useUserInfoStore = defineStore('user-info', () => {
  const user = ref<UserInfoUser | null>(null)
  const roles = ref<string[]>([])

  async function loadUserInfo(): Promise<void> {
    const info = await fetchUserInfo()
    user.value = info.user
    roles.value = info.roles
    usePermissionStore().setPermissions(info.permissions)
  }

  function reset(): void {
    user.value = null
    roles.value = []
  }

  return { user, roles, loadUserInfo, reset }
})
