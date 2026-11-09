import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/static/console/',
  build: {
    outDir: '../src/bacmap/interfaces/web/static/console',
    emptyOutDir: true,
    modulePreload: { polyfill: false },
    sourcemap: false,
  },
})
