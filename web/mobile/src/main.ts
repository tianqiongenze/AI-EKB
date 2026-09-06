import { createSSRApp } from "vue";
import App from "./App.vue";

// uni-app Vue3 入口约定：导出 createApp（HBuilderX 与 CLI 均以此装配）
export function createApp() {
  const app = createSSRApp(App);
  return {
    app,
  };
}
