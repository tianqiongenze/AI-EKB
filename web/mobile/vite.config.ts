import { defineConfig } from "vite";
import uni from "@dcloudio/vite-plugin-uni";

// CLI 构建入口；HBuilderX 不读取本文件（其内置编译器等效处理）。
// 插件 @dcloudio/vite-plugin-uni 由官方模板安装（版本以 HBuilderX 内置为准，见 package.json 注释）。
export default defineConfig({
  plugins: [uni()],
});
