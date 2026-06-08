# 法律风控 DeepResearch - 前端

## 快速开始

### 环境要求
- Node.js >= 18
- npm >= 9

### 安装与运行

```bash
# 1. 安装依赖
npm install --legacy-peer-deps

# 2. 启动开发服务器
npm run dev
```

启动成功后访问 http://localhost:5183/

### 后端对接

前端默认通过同源 API 网关访问后端：

```env
VITE_API_BASE=/api
VITE_API_PROXY=http://localhost:8000
```

开发环境下，Vite 会把 `/api/*` 代理到 `VITE_API_PROXY`，并自动去掉 `/api` 前缀后转发给 FastAPI。生产构建下，前端继续请求 `/api/*`，可由后端同源托管和转发。

### 常见问题

#### macOS/Linux 权限问题

如果遇到 `Permission denied` 错误，运行：

```bash
chmod +x node_modules/.bin/*
```

然后重新执行 `npm run dev`

#### Windows 用户

如遇权限问题，请以管理员身份运行终端。

---

## 技术栈

- React 19
- TypeScript
- Vite
- Ant Design 5
- React Router 6

## 可用命令

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 构建生产版本 |
| `npm run preview` | 预览生产版本 |
| `npm run lint` | 运行代码检查 |
