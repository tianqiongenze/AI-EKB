/// <reference types="vite/client" />

// 与 web/admin/src/api.ts 同名同义的环境变量契约
interface ImportMetaEnv {
  /** API 基地址（缺省 "/api"），同 web/admin 的 VITE_API_BASE */
  readonly VITE_API_BASE?: string;
  /** Bearer Token（缺省不携带），同 web/admin 的 VITE_EKB_AUTH_TOKEN */
  readonly VITE_EKB_AUTH_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
