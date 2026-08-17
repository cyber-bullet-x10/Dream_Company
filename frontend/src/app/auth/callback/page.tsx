"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { getUserRole, setRoleCookie, roleToHome } from "@/lib/auth";

export default function AuthCallbackPage() {
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "error">("loading");
  const [message, setMessage] = useState("");

  // 만료/무효 링크 재발송용
  const [email, setEmail] = useState("");
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);
  const [resendError, setResendError] = useState("");

  // 링크 재발송 후에도 진입 의도(next)를 유지
  const getNext = () => {
    const next = new URLSearchParams(window.location.search).get("next");
    return next && next.startsWith("/") && !next.startsWith("//") ? next : null;
  };

  useEffect(() => {
    const handleCallback = async () => {
      try {
        let session = (await supabase.auth.getSession()).data.session;

        if (!session) {
          const { error } = await supabase.auth.exchangeCodeForSession(window.location.search);
          if (error) throw error;
          session = (await supabase.auth.getSession()).data.session;
        }

        if (!session) throw new Error("세션을 가져올 수 없습니다.");

        const role = await getUserRole();
        setRoleCookie(role);

        // 진입 의도(next) 보존 — 콜드 게스트가 작가/스폰서 온보딩 등으로
        // 들어오던 흐름을 Magic Link 왕복 후에도 유지. 내부 경로만 허용(오픈리다이렉트 차단).
        router.replace(getNext() || roleToHome(role));
      } catch {
        // 만료/무효 링크 — 홈으로 튕기지 않고 재발송 UI를 보여줌
        setMessage("로그인 링크가 만료되었거나 이미 사용되었어요.");
        setStatus("error");
      }
    };

    handleCallback();
  }, [router]);

  const handleResend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setResending(true);
    setResendError("");
    try {
      const next = getNext();
      const callbackUrl = next
        ? `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`
        : `${window.location.origin}/auth/callback`;
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: { emailRedirectTo: callbackUrl },
      });
      if (error) throw error;
      setResent(true);
    } catch (err: unknown) {
      setResendError(err instanceof Error ? err.message : "링크 발송에 실패했습니다.");
    } finally {
      setResending(false);
    }
  };

  return (
    <div style={{ minHeight: "100dvh", background: "#F7F4EE", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", fontFamily: "'Noto Serif KR', serif", gap: "1.5rem", padding: "2rem 1.5rem", boxSizing: "border-box" }}>
      <p style={{ fontSize: "clamp(1.5rem, 5vw, 2rem)", fontWeight: 700, color: "#1A2744", letterSpacing: "0.15em" }}>꿈신문사</p>

      {status === "loading" && (
        <p style={{ color: "#555", fontFamily: "system-ui, sans-serif", fontSize: "1rem", textAlign: "center" }}>
          로그인 중...
        </p>
      )}

      {status === "error" && !resent && (
        <div style={{ maxWidth: 360, width: "100%", fontFamily: "system-ui, sans-serif" }}>
          <p style={{ color: "#c0392b", fontSize: "1rem", textAlign: "center", margin: "0 0 0.5rem" }}>{message}</p>
          <p style={{ color: "#666", fontSize: "0.85rem", textAlign: "center", lineHeight: 1.6, margin: "0 0 1.25rem" }}>
            이메일을 입력하면 새 로그인 링크를 보내드려요.<br />
            그동안 발행된 신문은 그대로 보관되어 있어요.
          </p>
          <form onSubmit={handleResend} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="이메일 주소"
              required
              autoFocus
              style={{ padding: "0.75rem 1rem", border: "1px solid #C9A84C", background: "rgba(255,255,255,0.7)", fontSize: "1rem", color: "#1A2744", outline: "none", width: "100%", boxSizing: "border-box" }}
            />
            {resendError && <p style={{ color: "#c0392b", fontSize: "0.85rem", margin: 0 }}>{resendError}</p>}
            <button
              type="submit"
              disabled={resending}
              style={{ padding: "0.85rem", background: resending ? "#aaa" : "#1A2744", color: "#F7F4EE", border: "none", fontSize: "1rem", cursor: resending ? "not-allowed" : "pointer", letterSpacing: "0.05em" }}
            >
              {resending ? "발송 중..." : "새 로그인 링크 받기"}
            </button>
          </form>
        </div>
      )}

      {status === "error" && resent && (
        <div style={{ maxWidth: 360, width: "100%", padding: "1.5rem", background: "rgba(201,168,76,0.12)", borderLeft: "4px solid #C9A84C", fontFamily: "system-ui, sans-serif" }}>
          <p style={{ margin: 0, fontSize: "1rem", color: "#1A2744", fontWeight: 600 }}>새 링크를 발송했습니다</p>
          <p style={{ margin: "0.5rem 0 0", fontSize: "0.875rem", color: "#555", lineHeight: 1.6 }}>
            <strong>{email}</strong>로 로그인 링크를 보냈어요.<br />
            링크를 클릭하면 바로 입장됩니다.
          </p>
        </div>
      )}
    </div>
  );
}
