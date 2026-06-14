import { defineStore } from 'pinia'
import { ref } from 'vue'
import { hasRefresh } from '@/api/session'

/** 认证状态（读 session token 真值源供 UI）。spec §3.1。 */
export const useAuthStore = defineStore('auth', () => {
  const ready = ref(false)
  function isLoggedIn(): boolean {
    return hasRefresh()
  }
  return { ready, isLoggedIn }
})
