const BASE = import.meta.env.VITE_API_BASE ?? "/api";
const TOKEN_STORAGE_KEY = "ekb.admin.token";

// 内存兜底：sessionStorage 不可用（隐私模式/测试环境）时登录流程仍可用。
let memoryToken: string | null = null;

function envToken(): string {
  return import.meta.env.VITE_EKB_AUTH_TOKEN ?? "";
}

/** 管理台 Token：登录页写入 sessionStorage（ekb.admin.token），环境变量仅作 CI/脚本兜底。 */
export function getToken(): string {
  if (memoryToken !== null) return memoryToken;
  try {
    const stored = window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored !== null) return stored;
  } catch {
    // sessionStorage 不可用时退回环境变量
  }
  return envToken();
}

export function setToken(token: string): void {
  memoryToken = token;
  try {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // 仅内存态
  }
}

export function clearToken(): void {
  memoryToken = null;
  try {
    window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // 仅内存态
  }
}

export function hasToken(): boolean {
  return getToken() !== "";
}

// 401 处理：清空 Token 并通知 UI 回到登录页（B-3）。
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export interface CapacityEstimate {
  estimated_qps: number;
  estimated_llm_qps: number;
  estimated_heavy_llm_qps: number;
  recommended_a100_80g: number;
  estimated_cross_region_qps: number;
  estimated_failover_peak_qps: number;
  recommended_gateway_vcpu: number;
  recommended_control_plane_vcpu: number;
}

export interface AuditRecord {
  id?: number;
  created_at?: string;
  tenant_id?: string;
  region_id?: string;
  plant_id?: string;
  user_or_agent_id?: string;
  skill?: string;
  tool?: string;
  decision_reason?: string;
  accepted?: boolean;
  [key: string]: unknown;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init?.headers as any) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (resp.status === 401) {
    clearToken();
    unauthorizedHandler?.();
    throw new Error("401 Unauthorized");
  }
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body?.detail ?? `${resp.status}`);
  return body as T;
}

export const api = {
  healthz: () => call<{ status: string }>("/healthz"),
  readyz: () => call<{ status: string; event_publisher_backend: string; outbox: Record<string, number> }>("/readyz"),
  capacity: (payload: object) => call<CapacityEstimate>("/capacity/estimate", { method: "POST", body: JSON.stringify(payload) }),
  skillsRegister: (payload: object) => call<{ status: string }>("/skills/register", { method: "POST", body: JSON.stringify(payload) }),
  skillsPromote: (payload: object) => call<Record<string, unknown>>("/skills/promote", { method: "POST", body: JSON.stringify(payload) }),
  auditQuery: (payload: object) => call<{ count?: number; items?: AuditRecord[] }>("/audit/query", { method: "POST", body: JSON.stringify(payload) }),
  metrics: async (): Promise<string> => {
    const resp = await fetch(`${BASE}/metrics`);
    return resp.text();
  },
};
