import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // v1.10.24：相对 base + HTML 内 <base> 标签（index.html 模板已加）。
  // 纯相对 './' 在 SPA 嵌套路由断裂（/console/samples/x 时 ./assets → 错误
  // 路径）；<base href> 由 DSH 代理改写为 /bacmap/console/，直连与代理均正确，
  // 且 Vite 懒加载 CSS 的 link.href 属性赋值也按 <base> 解析（DSH 下不再 404）。
  base: './',
  build: {
    outDir: '../src/bacmap/interfaces/web/static/console',
    emptyOutDir: true,
    modulePreload: { polyfill: false },
    sourcemap: false,
  },
})
