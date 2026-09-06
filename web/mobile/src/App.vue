<script setup lang="ts">
import { onHide, onLaunch, onShow } from "@dcloudio/uni-app";

onLaunch(() => {
  // M2 骨架启动日志：确认 Vue3 基座生命周期可用
  console.log(
    "[EKB Mobile] onLaunch: uni-app Vue3 过渡基座启动（鸿蒙主路线 uni-app x，见 README / docs/frontend-multiclient-design.md）"
  );
});

onShow(() => {
  console.log("[EKB Mobile] onShow");
});

onHide(() => {
  console.log("[EKB Mobile] onHide");
});
</script>

<style lang="scss">
/* 全局根样式：变量来自 tokens.scss（经 uni.scss 自动注入），
 * 与 web/admin/tokens/tokens.json 单一视觉源对齐。 */
page {
  background-color: $color-surface-bg;
  color: $color-surface-text;
  font-family: $typography-family;
  font-size: $typography-size-body;
}
</style>
