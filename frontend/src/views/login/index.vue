<script setup lang="ts">
/**
 * 登录页：用户名/密码 + 算术验证码（文本题，非图片）。
 * 成功 → runPostLoginSetup()（main.ts 注入 router 的 setupAfterLogin）→ 回跳 redirect query。
 * views 禁 import src/router：导航用 useRouter()/useRoute()，登录后装配走 stores/post-login 注入。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { getCaptcha, login, MissingRefreshTokenError, type CaptchaResponse } from '@/api/auth'
import type { ApiError } from '@/api/transport'
import { runPostLoginSetup } from '@/stores/post-login'

const router = useRouter()
const route = useRoute()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '', captchaAnswer: '' })
/** 当前算术题；503（验证码服务不可用）时为 null，提交不带验证码字段。 */
const captcha = ref<CaptchaResponse | null>(null)
/** 验证码服务不可用（getCaptcha 失败）。区分「无需验证码」与「服务故障」，避免死循环无反馈。 */
const captchaUnavailable = ref(false)
const submitting = ref(false)
/** 登录响应缺 refresh_token = 环境配置错误（fail fast，区别于常规登录失败分支）。 */
const envError = ref(false)

const rules = computed<FormRules>(() => ({
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  captchaAnswer: captcha.value
    ? [{ required: true, message: '请输入计算结果', trigger: 'blur' }]
    : [],
}))

/** 拉取算术验证码；失败（如 Redis 不可用 503）不阻断表单，登录被要求验证码时再重试。 */
async function refreshCaptcha(): Promise<void> {
  form.captchaAnswer = ''
  try {
    captcha.value = await getCaptcha()
    captchaUnavailable.value = false
  } catch {
    captcha.value = null
    captchaUnavailable.value = true
  }
}

// 首版策略：进页即拉验证码显示（简单，且兜底「失败 N 次后强制验证码」）
onMounted(() => {
  void refreshCaptcha()
})

/**
 * redirect 白名单守卫：仅采用应用内绝对路径，排除协议相对（//evil）与绝对 URL（http(s):），
 * 杜绝 open-redirect（即便 router.replace 当前把字符串当内部路径解析，也防 vue-router 行为回归）。
 */
function safeRedirect(raw: unknown): string {
  if (typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//')) return raw
  return '/'
}

/** 常规登录错误（RFC9457 归一化 ApiError）按错误码分支提示。 */
function showLoginError(err: ApiError): void {
  switch (err.code) {
    case 'auth.CAPTCHA_REQUIRED':
      ElMessage.error('登录失败次数过多，请输入验证码后重试')
      break
    case 'auth.CAPTCHA_INVALID':
      ElMessage.error('验证码错误，请重新输入')
      break
    case 'auth.LOGIN_RATE_LIMITED':
      ElMessage.error('登录尝试过于频繁，请稍后再试')
      break
    case 'auth.ACCOUNT_DISABLED':
      ElMessage.error('账号已停用，请联系管理员')
      break
    default:
      ElMessage.error(err.message || '登录失败')
  }
}

async function handleSubmit(): Promise<void> {
  if (submitting.value || !formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  envError.value = false
  try {
    await login({
      username: form.username,
      password: form.password,
      captcha_id: captcha.value?.captcha_id ?? null,
      captcha_answer: captcha.value ? form.captchaAnswer : null,
    })
    await runPostLoginSetup()
    await router.replace(safeRedirect(route.query.redirect))
  } catch (err) {
    if (err instanceof MissingRefreshTokenError) {
      envError.value = true
    } else {
      showLoginError(err as ApiError)
      // 出错后旧题可能已被消费/过期，换一题
      void refreshCaptcha()
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <h1 class="login-title">admin-platform</h1>
      <p class="login-subtitle">后台管理系统</p>
      <el-alert
        v-if="envError"
        class="login-env-alert"
        type="error"
        :closable="false"
        title="环境配置错误"
        description="登录响应缺少 refresh_token：请检查后端 APP_AUTH_REFRESH_TOKEN_PEPPER 配置"
      />
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        :validate-on-rule-change="false"
        label-position="top"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="用户名" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            show-password
            autocomplete="current-password"
          />
        </el-form-item>
        <el-alert
          v-if="captchaUnavailable"
          class="login-env-alert"
          type="warning"
          :closable="false"
          title="验证码服务暂不可用"
        >
          <template #default>
            请稍后
            <el-button text type="primary" @click="refreshCaptcha">重试</el-button>
          </template>
        </el-alert>
        <el-form-item v-if="captcha" label="验证码" prop="captchaAnswer">
          <div class="login-captcha-row">
            <span class="login-captcha-question">{{ captcha.question }}</span>
            <el-input
              v-model="form.captchaAnswer"
              class="login-captcha-input"
              placeholder="计算结果"
            />
            <el-button text type="primary" @click="refreshCaptcha">换一题</el-button>
          </div>
        </el-form-item>
        <el-button class="login-submit" type="primary" native-type="submit" :loading="submitting">
          登 录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--el-fill-color-light);
}

.login-card {
  width: 380px;
  padding: 8px 4px;
}

.login-title {
  margin: 0;
  text-align: center;
  font-size: 22px;
  color: var(--el-text-color-primary);
}

.login-subtitle {
  margin: 4px 0 20px;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.login-env-alert {
  margin-bottom: 16px;
}

.login-captcha-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.login-captcha-question {
  flex-shrink: 0;
  min-width: 90px;
  padding: 4px 8px;
  text-align: center;
  font-family: monospace;
  font-size: 15px;
  color: var(--el-text-color-primary);
  background: var(--el-fill-color);
  border-radius: 4px;
  user-select: none;
}

.login-captcha-input {
  flex: 1;
}

.login-submit {
  width: 100%;
  margin-top: 8px;
}
</style>
