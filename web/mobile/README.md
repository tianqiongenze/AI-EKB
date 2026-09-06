# EKB 移动端骨架（M2 · uni-app Vue3 过渡基座）

> 定位：M2 移动端工程骨架。按 `docs/frontend-multiclient-design.md` §1 的选型结论，**鸿蒙主路线是 uni-app x（UTS 编译为 ArkTS 原生）**；本骨架为 **uni-app（Vue3）过渡基座**，先行打通「页面路由 + API 客户端 + 设计令牌」三件事，M3 迁移 uni-app x 时页面结构、API 语义与令牌契约可直接平移。

## 页面

| 路由 | 页面 | 内容 |
|---|---|---|
| `pages/index/index` | 健康/问答 | readyz 状态（status / event_publisher_backend）+ Outbox 待发计数卡片 |
| `pages/capacity/capacity` | 容量估算 | 四参数表单（online_users / active_ratio / cache_hit_ratio / complex_ratio）→ `POST /capacity/estimate` → JSON 结果展示 |

## 用 HBuilderX 运行（推荐路径）

1. HBuilderX（3.9+，建议最新正式版）→「文件 → 导入 → 从本地目录导入」选择本目录 `web/mobile/`。
2. 「工具 → 插件安装」安装 **scss/sass 编译** 插件（`uni.scss` / `tokens.scss` 需要）。
3. 「运行」菜单选择目标：
   - 运行到浏览器（H5，Chrome 设备模拟即可看两页）；
   - 运行到手机或模拟器（Android / iOS App）；
   - 运行到小程序模拟器（微信开发者工具）；
   - 运行到手机或模拟器 → **HarmonyOS**（鸿蒙过渡路径，见下节）。
4. 「发行」菜单：网站 H5 / 原生 App 云打包 / 小程序。

## 用 CLI 构建（可选）

`package.json` 的 scripts 采用 `@dcloudio/uni` 快捷命令写法：`dev:h5` / `build:h5` / `dev:app` / `build:app` / `dev:mp-weixin` / `build:mp-weixin`。**依赖版本为占位说明，以 HBuilderX 内置编译器为准**（本文件刻意不锁定 `@dcloudio/*` 版本，避免与内置版本漂移冲突）。若走 CLI，请用官方模板锁定依赖后安装：`npx degit dcloudio/uni-preset-vue#vite-ts`（或把本目录 `src/` 并入该模板），`npm i` 后执行 `npm run dev:h5`。

## 环境变量（与 Web 管理台同名同义）

| 变量 | 缺省 | 说明 |
|---|---|---|
| `VITE_API_BASE` | `/api` | 控制面/网关地址，同 `web/admin/src/api.ts` |
| `VITE_EKB_AUTH_TOKEN` | 空 | 非空时所有请求携带 `Authorization: Bearer <token>` |

CLI 方式放 `.env` 文件（vite 约定）；变量类型见 `src/env.d.ts`。`src/api/client.ts` 与管理台语义一致：healthz / readyz / capacity / auditQuery，非 2xx 抛 `Error(detail ?? statusCode)`。

## 鸿蒙迁移路径（uni-app x / ArkTS）

1. **过渡期（本骨架）**：uni-app Vue3 通过 HBuilderX「运行到 HarmonyOS」产出鸿蒙可运行包（逻辑层跑在 JS 引擎）；`src/manifest.json` 已预留 `app-harmony` 配置节注释骨架。
2. **M3 主路线**：迁移 **uni-app x** —— `.vue → .uvue`、TS → UTS，编译为 **ArkTS 原生**，规避 WebView 性能坑（性能预算：冷启动 < 1.5s，见设计文档 §3）。页面结构、`api/client.ts` 语义、`tokens.scss` 令牌契约平移即可。
3. **验收**（设计文档 §5 M3）：鸿蒙真机过检 + 三端 Tokens 一致性自动化比对。

## 与管理台共享设计令牌

- **唯一视觉源**：`web/admin/tokens/tokens.json`（W3C DTCG 格式）。
- **产物对**：Web 侧 `web/admin/src/tokens.css`（CSS Variables）↔ 移动侧 `web/mobile/src/tokens.scss`（SCSS `$` 变量 + `page/:root` CSS 自定义属性），同名同值。
- **修改流程**：改 `tokens.json` → 同步更新两端产物 → 双端视觉走查；M3 落地脚本化生成与一致性自动比对。
- `pages.json` 的导航栏颜色（`#1a56db` / `#f7f8fa`）亦取自令牌（brand.primary / surface.bg）。

## 目录结构

```
web/mobile/
├── package.json                # scripts（uni 快捷命令）；依赖为占位说明，以 HBuilderX 内置为准
├── index.html                  # H5 入口（CLI vite 约定，HBuilderX 自动生成等效文件）
├── vite.config.ts              # CLI vite 配置（HBuilderX 不读取）
└── src/
    ├── main.ts                 # 应用入口（createSSRApp）
    ├── App.vue                 # onLaunch 日志 + 全局根样式（令牌变量）
    ├── manifest.json           # 应用配置（appid 留空；app-harmony 注释骨架）
    ├── pages.json              # 路由：index / capacity
    ├── uni.scss                # 全局变量注入入口（@import tokens.scss + uni 内置别名）
    ├── tokens.scss             # tokens.json 的 SCSS 翻译层（与 tokens.css 同源同值）
    ├── env.d.ts                # import.meta.env 类型（VITE_API_BASE / VITE_EKB_AUTH_TOKEN）
    ├── api/
    │   └── client.ts           # uni.request 封装：healthz / readyz / capacity / auditQuery
    └── pages/
        ├── index/index.vue     # 健康页（readyz 状态 + outbox 计数卡片）
        └── capacity/capacity.vue # 容量页（四参数表单 + 结果展示）
```
