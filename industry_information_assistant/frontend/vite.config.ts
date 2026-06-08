/**
 * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
 * 未经授权，禁止转售或仿制。
 */

import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { viteMockServe } from 'vite-plugin-mock'

function normalizePath(value: string | undefined, fallback: string) {
  const raw = value?.trim() || fallback
  if (!raw.startsWith('/')) return raw
  return raw === '/' ? raw : raw.replace(/\/+$/, '')
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd()) as {
    VITE_API_BASE: string
    VITE_API_PROXY: string
  }
  const apiBase = normalizePath(env.VITE_API_BASE, '/api')
  const apiProxy = env.VITE_API_PROXY?.trim() || 'http://localhost:8000'
  const proxy =
    apiBase.startsWith('/') && apiBase !== '/'
      ? {
          [apiBase]: {
            target: apiProxy,
            changeOrigin: true,
            secure: false,
            rewrite: (path: string) =>
              path.replace(new RegExp(`^${escapeRegExp(apiBase)}(?=/|$)`), '') || '/',
          },
        }
      : undefined

  return {
    server: {
      port: 5183,
      host: '0.0.0.0',
      strictPort: true,
      proxy,
    },
    resolve: {
      alias: [
        {
          find: /^@\//,
          replacement: '/src/',
        },
      ],
    },

    plugins: [
      react(),
      viteMockServe({
        enable: false,
      }),
    ],
  }
})
