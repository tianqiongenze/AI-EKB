// B-3 登录页：首次无 Token 时显示（logo + 标题 + Token 输入框 + 进入按钮）。
// 提交仅写入 sessionStorage（ekb.admin.token）并放行；后续任意 API 401 时由 api.ts 清空 Token 并回到本页。
import { useState, type FormEvent } from "react";
import { setToken } from "../api";
import { Logo } from "../components/Logo";
import { buttonStyle, inputStyle } from "../components/styles";
import { t } from "../i18n";

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [token, setTokenInput] = useState("");
  const [error, setError] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) {
      setError(t("login.tokenRequired"));
      return;
    }
    setToken(trimmed);
    onSuccess();
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit} aria-label={t("login.title")}>
        <Logo size={56} />
        <h1>{t("app.title")}</h1>
        <p className="login-sub">{t("login.subtitle")}</p>
        <div className="login-form">
          <label>
            {t("login.tokenLabel")}
            <input
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder={t("login.tokenPlaceholder")}
              style={inputStyle}
            />
          </label>
          {error ? (
            <p className="login-error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" style={buttonStyle}>
            {t("login.submit")}
          </button>
        </div>
      </form>
    </div>
  );
}
