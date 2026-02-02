import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 从环境变量获取 core-api 端口，默认 5173
// 优先级：VITE_CORE_API_URL > CORE_API_PORT > 默认 5173
const getCoreApiTarget = (): string => {
  // 如果设置了完整的 URL，直接使用
  if (process.env.VITE_CORE_API_URL) {
    return process.env.VITE_CORE_API_URL;
  }
  // 否则使用 CORE_API_PORT 环境变量构建 URL
  const apiPort = process.env.CORE_API_PORT || "5173";
  return `http://127.0.0.1:${apiPort}`;
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8000,
    proxy: {
      "/api": {
        target: getCoreApiTarget(),
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
    include: ["tests/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}"],
    globals: true,
  },
});
