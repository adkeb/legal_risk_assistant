/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

const DEFAULT_API_BASE = '/api'

function normalizeBaseURL(value: string | undefined) {
  const base = value?.trim() || DEFAULT_API_BASE
  if (base === '/') return base
  return base.replace(/\/+$/, '')
}

export const apiBaseURL = normalizeBaseURL(import.meta.env.VITE_API_BASE)
