<template>
  <view :style="pageStyle">
    <view :style="headerStyle">
      <text :style="h1Style">容量估算</text>
      <text :style="mutedStyle">POST /capacity/estimate · 四参数</text>
    </view>

    <!-- 四参数表单 -->
    <view :style="cardStyle">
      <view v-for="f in fields" :key="f.key" :style="fieldRowStyle">
        <text :style="labelStyle">{{ f.label }}</text>
        <input
          class="ekb-input"
          :type="f.type"
          :value="form[f.key]"
          :style="inputStyle"
          @input="onInput(f.key, $event)"
        />
      </view>
      <button :style="btnStyle" :disabled="loading" @click="submit">
        {{ loading ? "估算中…" : "提交估算" }}
      </button>
      <text v-if="error" :style="dangerStyle">{{ error }}</text>
    </view>

    <!-- 结果展示 -->
    <view v-if="result" :style="cardStyle">
      <text :style="cardTitleStyle">估算结果</text>
      <text :style="codeStyle">{{ result }}</text>
    </view>

    <navigator url="/pages/index/index" class="back-link">← 返回健康页</navigator>
  </view>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { api } from "@/api/client";

type FieldKey = "online_users" | "active_ratio" | "cache_hit_ratio" | "complex_ratio";

const fields: { key: FieldKey; label: string; type: "number" | "digit" }[] = [
  { key: "online_users", label: "在线用户数 online_users", type: "number" },
  { key: "active_ratio", label: "活跃占比 active_ratio（0-1）", type: "digit" },
  { key: "cache_hit_ratio", label: "缓存命中率 cache_hit_ratio（0-1）", type: "digit" },
  { key: "complex_ratio", label: "复杂请求占比 complex_ratio（0-1）", type: "digit" },
];

// 与管理台默认基线一致（10 万在线）
const form = reactive<Record<FieldKey, string>>({
  online_users: "100000",
  active_ratio: "0.1",
  cache_hit_ratio: "0.5",
  complex_ratio: "0.3",
});

const result = ref("");
const loading = ref(false);
const error = ref("");

function onInput(key: FieldKey, e: { detail?: { value?: string } }): void {
  form[key] = e?.detail?.value ?? "";
}

async function submit(): Promise<void> {
  const payload: Record<FieldKey, number> = {
    online_users: Number(form.online_users),
    active_ratio: Number(form.active_ratio),
    cache_hit_ratio: Number(form.cache_hit_ratio),
    complex_ratio: Number(form.complex_ratio),
  };
  if (Object.values(payload).some((v) => Number.isNaN(v))) {
    error.value = "所有参数必须为数字";
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const r = await api.capacity(payload);
    result.value = JSON.stringify(r, null, 2);
  } catch (e) {
    result.value = "";
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

/* 内联样式统一引用 tokens.scss 生成的 CSS 自定义属性（与 index 页同一视觉源）。 */
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
const fieldRowStyle = { marginBottom: "var(--space-3)" };
const labelStyle = { display: "block", marginBottom: "var(--space-1)", color: "var(--color-surface-muted)" };
const inputStyle = { width: "100%", boxSizing: "border-box" };
const btnStyle = {
  marginTop: "var(--space-2)",
  padding: "var(--space-2) var(--space-4)",
  borderRadius: "var(--radius-input)",
  border: "none",
  backgroundColor: "var(--color-brand-primary)",
  color: "#ffffff",
  fontSize: "var(--typography-size-body)",
};
const dangerStyle = { display: "block", marginTop: "var(--space-2)", color: "var(--color-brand-danger)" };
const codeStyle = {
  whiteSpace: "pre-wrap",
  fontFamily: "monospace",
  fontSize: "12px",
  color: "var(--color-surface-text)",
};
</script>

<style lang="scss">
/* 输入框静态样式：直接使用 tokens.scss 的 SCSS 变量（经 uni.scss 全局注入）。 */
.ekb-input {
  height: 64rpx;
  line-height: 64rpx;
  padding: 0 $space-3;
  background-color: $color-surface-card;
  color: $color-surface-text;
  border: 1px solid $color-border;
  border-radius: $radius-input;
  font-size: $typography-size-body;
  box-sizing: border-box;
}

.back-link {
  display: block;
  margin-top: $space-6;
  text-align: center;
  color: $color-brand-primary;
  font-size: $typography-size-body;
}
</style>
