/**
 * EKB 移动端 API 客户端（uni.request 封装）。
 *
 * 语义与 web/admin/src/api.ts 保持一致：
 *   - 四个方法：healthz / readyz / capacity / auditQuery；
 *   - BASE 与 Bearer Token 环境变量同名同义：VITE_API_BASE / VITE_EKB_AUTH_TOKEN；
 *   - 错误约定：非 2xx 抛出 Error(body.detail ?? statusCode)。
 * 传输层差异：fetch → uni.request（跨端：H5 / App / 小程序 / 鸿蒙）。
 */

type Envelope = Record<string, unknown> & { detail?: string };

interface RequestOptions {
  method?: "GET" | "POST";
  data?: unknown;
}

function readEnv(key: "VITE_API_BASE" | "VITE_EKB_AUTH_TOKEN"): string | undefined {
  // 防御式读取：vite 产物为 import.meta.env；个别平台无该全局时回退 undefined
  const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
  return env?.[key];
}

/** API 基地址（与 web/admin 同名同义，缺省 "/api"）。 */
export const BASE_URL: string = readEnv("VITE_API_BASE") ?? "/api";

const TOKEN: string = readEnv("VITE_EKB_AUTH_TOKEN") ?? "";

function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const header: Record<string, string> = { "Content-Type": "application/json" };
  if (TOKEN) header.Authorization = `Bearer ${TOKEN}`;

  return new Promise<T>((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${path}`,
      method: options.method ?? "GET",
      data: options.data as Record<string, unknown> | undefined,
      header,
      success: (res) => {
        const body = (res.data ?? {}) as Envelope;
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(body.detail ?? String(res.statusCode)));
          return;
        }
        resolve(body as T);
      },
      fail: (err) => {
        reject(new Error(err?.errMsg ?? "network error"));
      },
    });
  });
}

/** GET /readyz 返回结构（与管理台一致）。 */
export interface ReadyzResult {
  status: string;
  event_publisher_backend: string;
  outbox: Record<string, number>;
}

export const api = {
  /** GET /healthz */
  healthz: () => request<{ status: string }>("/healthz"),
  /** GET /readyz（含事件后端类型与 outbox 各队列计数） */
  readyz: () => request<ReadyzResult>("/readyz"),
  /** POST /capacity/estimate（四参数：online_users / active_ratio / cache_hit_ratio / complex_ratio） */
  capacity: (payload: object) =>
    request<Record<string, unknown>>("/capacity/estimate", { method: "POST", data: payload }),
  /** POST /audit/query */
  auditQuery: (payload: object) =>
    request<{ count?: number; items?: unknown[] }>("/audit/query", { method: "POST", data: payload }),
};
