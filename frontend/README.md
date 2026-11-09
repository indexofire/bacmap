# bacmap console（Vue 3 + Vite）

`/console/` 的暗色控制台。构建产物提交在
`src/bacmap/interfaces/web/static/console/`，由 FastAPI 直接托管；**运行期不需要
Node/Bun**（ADR-01）。Node 只用于开发与构建。

## 开发

```bash
pixi run -e web web-install     # npm ci（首次或 lockfile 变化后）
pixi run -e web web-dev         # Vite dev server（默认 5173）
pixi run -e web web-build       # vue-tsc + vite build → static/console
```

单独用系统 Node 也可以：`npm install && npm run dev|build`。

## 结构

```text
frontend/
├── index.html
├── public/favicon.svg
├── src/
│   ├── api.ts              # /api/v1 客户端（cookie + CSRF）
│   ├── router.ts           # /console/ 下的客户端路由
│   ├── types.ts
│   ├── components/         # AppShell / 状态徽章 / 图标 / 提交抽屉 / Toast
│   ├── composables/        # 轮询、Toast
│   ├── lib/                # ECharts 按需加载、格式化
│   ├── styles/             # tokens.css + app.css（全局设计系统）
│   └── views/              # Dashboard/Tasks/TaskDetail/Plans/.../Search
└── vite.config.ts          # base=/static/console/，outDir=../src/.../static/console
```

## 设计约束

- 继承根目录 `DESIGN.md`：近黑画布、亮度分层、单一靛蓝强调、六态语义徽章、等宽读数。
- 零外联：系统字体栈、内联 SVG 图标、本地 CSS/JS；无 CDN/webfont。
- 状态不只靠颜色：徽章始终带中文标签；running 的呼吸点是增强信号。
- 键盘可达：skip link、`:focus-visible`、表单 label、原生确认对话框；
  `prefers-reduced-motion` 下停用非必要动画。
- 只读展示与写操作分离：任务提交/审批/记录都走 `/api/v1` + CSRF，不直接改库。

## CI

`.github/workflows/ci.yml` 的 `web` job 会：

1. `pixi run -e web web-install`
2. `pixi run -e web web-build`
3. `git diff --exit-code -- src/bacmap/interfaces/web/static/console`

因此修改前端后必须提交重新构建的 `static/console` 产物。
