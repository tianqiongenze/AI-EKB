<template>
  <view :style="pageStyle">
    <view :style="headerStyle">
      <text :style="h1Style">运行健康</text>
      <text :style="mutedStyle">readyz · outbox · uni-app Vue3 骨架</text>
    </view>

    <!-- readyz 状态卡片 -->
    <view :style="cardStyle">
      <text :style="cardTitleStyle">readyz 状态</text>
      <view v-if="error" :style="rowStyle">
        <text :style="dangerStyle">{{ error }}</text>
      </view>
      <view v-else-if="!ready" :style="rowStyle">
        <text :style="mutedStyle">加载中…</text>
      </view>
      <template v-else>
        <view :style="rowStyle">
          <text :style="mutedStyle">status</text>
          <text :style="ready.status === 'ready' ? okStyle : warnStyle">{{ ready.status }}</text>
        </view>
        <view :style="rowStyle">
          <text :style="mutedStyle">event_publisher_backend</text>
          <text :style="bodyStyle">{{ ready.event_publisher_backend }}</text>
        </view>
      </template>
      <button :style="btnStyle" :disabled="loading" @click="refresh">
        {{ loading ? "刷新中…" : "刷新" }}
      </button>
    </view>

    <!-- outbox 待发计数卡片 -->
    <view :style="cardStyle">
      <text :style="cardTitleStyle">Outbox 待发计数</text>
      <view v-for="(count, key) in outboxMap" :key="key" :style="rowStyle">
        <text :style="bodyStyle">{{ key }}</text>
        <text :style="count > 0 ? warnStyle : okStyle">{{ count }}</text>
      </view>
      <view v-if="outboxEmpty" :style="rowStyle">
        <text :style="mutedStyle">（空）</text>
      </view>
    </view>

    <navigator url="/pages/capacity/capacity">
      <button :style="btnGhostStyle">进入容量估算 →</button>
    </navigator>

    <view class="foot-note">
      <text>M2 骨架 · 与管理台共享 tokens.json 视觉源 · 鸿蒙主路线 uni-app x</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, type ReadyzResult } from "@/api/client";

const ready = ref<ReadyzResult | null>(null);
const loading = ref(false);
const error = ref("");

const outboxMap = computed<Record<string, number>>(() => ready.value?.outbox ?? {});
const outboxEmpty = computed(() => Object.keys(outboxMap.value).length === 0);

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    ready.value = await api.readyz();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);

/* 内联样式统一引用 tokens.scss 生成的 CSS 自定义属性（--color-* / --space-* / --radius-*），
 * 与 <style lang="scss"> 中的 SCSS $ 变量同源（web/admin/tokens/tokens.json），
 * 保证与管理台同一视觉源。 */
const pageStyle = {
  minHeight: "100vh",
  padding: "var(--space-4)",
  backgroundColor: "var(--color-surface-bg)",
  color: "var(--color-surface-text)",
  fontFamily: "var(--typography-family)",
  fontSize: "var(--typography-size-body)",
};
const headerStyle = { marginBottom: "var(--space-4)" };
const h1Style = { display: "block", fontSize: "var(--typography-size-h1)", fontWeight: "600" };
const mutedStyle = { display: "block", marginTop: "var(--space-1)", color: "var(--color-surface-muted)" };
const cardStyle = {
  backgroundColor: "var(--color-surface-card)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-card)",
  padding: "var(--space-4)",
  marginBottom: "var(--space-4)",
};
const cardTitleStyle = { display: "block", fontWeight: "600", marginBottom: "var(--space-3)" };
const rowStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "var(--space-2) 0",
  borderBottom: "1px solid var(--color-border)",
};
const bodyStyle = { color: "var(--color-surface-text)" };
const okStyle = { color: "var(--color-surface-ok)", fontWeight: "600" };
const warnStyle = { color: "var(--color-surface-warn)", fontWeight: "600" };
const dangerStyle = { color: "var(--color-brand-danger)" };
const btnStyle = {
  marginTop: "var(--space-3)",
  padding: "var(--space-2) var(--space-4)",
  borderRadius: "var(--radius-input)",
  border: "none",
  backgroundColor: "var(--color-brand-primary)",
  color: "#ffffff",
  fontSize: "var(--typography-size-body)",
};
const btnGhostStyle = {
  width: "100%",
  padding: "var(--space-2) var(--space-4)",
  borderRadius: "var(--radius-input)",
  border: "1px solid var(--color-border)",
  backgroundColor: "var(--color-surface-card)",
  color: "var(--color-brand-primary)",
  fontSize: "var(--typography-size-body)",
};
</script>

<style lang="scss">
/* 静态样式示例：直接使用 tokens.scss 的 SCSS 变量（经 uni.scss 全局注入）。 */
.foot-note {
  margin-top: $space-6;
  text-align: center;
  color: $color-surface-muted;
  font-size: $typography-size-body;
}
</style>
