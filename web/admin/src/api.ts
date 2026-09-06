const BASE = import.meta.env.VITE_API_BASE ?? "/api";
const TOKEN = import.meta.env.VITE_EKB_AUTH_TOKEN ?? "";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init?.headers as any) };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;
  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body?.detail ?? `${resp.status}`);
  return body as T;
}

export const api = {
  healthz: () => call<{ status: string }>("/healthz"),
  readyz: () => call<{ status: string; event_publisher_backend: string; outbox: Record<string, number> }>("/readyz"),
  capacity: (payload: object) => call<Record<string, unknown>>("/capacity/estimate", { method: "POST", body: JSON.stringify(payload) }),
  skillsRegister: (payload: object) => call<{ status: string }>("/skills/register", { method: "POST", body: JSON.stringify(payload) }),
  skillsPromote: (payload: object) => call<Record<string, unknown>>("/skills/promote", { method: "POST", body: JSON.stringify(payload) }),
  auditQuery: (payload: object) => call<{ count?: number; items?: unknown[] }>("/audit/query", { method: "POST", body: JSON.stringify(payload) }),
  metrics: async (): Promise<string> => {
    const resp = await fetch(`${BASE}/metrics`);
    return resp.text();
  },
};
