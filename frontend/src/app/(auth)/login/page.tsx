"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { setRoleCookie, getUserRole, roleToHome } from "@/lib/auth";
import { getApiBaseUrl } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [oauthLoading, setOauthLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  // 페이지 로드 시 백엔드 워밍업 (Render 콜드 스타트 방지)
  useEffect(() => {
    fetch(`${getApiBaseUrl()}/api/ping`).catch(() => {});
  }, []);

  // Kakao/Google OAuth 후 세션이 이미 있으면 바로 이동
  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (session?.user) {
        const role = await getUserRole();
        setRoleCookie(role);
        const nextPath = searchParams.get("next");
        router.replace(nextPath || roleToHome(role));
      }
    });
  }, [router, searchParams]);

  const handleOAuth = async (provider: "kakao" | "google") => {
    setOauthLoading(provider);
    setError("");
    try {
      // 진입 의도(next)를 OAuth 왕복 후에도 유지 — 헤드라인 생성기→3일무료(/order/new)
      // 흐름이 카카오/구글 로그인에서 끊기던 문제 수정. (매직링크와 동일 처리)
      const nextPath = searchParams.get("next");
      const redirectTo = nextPath
        ? `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`
        : `${window.location.origin}/auth/callback`;
      const { data, error } = await supabase.auth.signInWithOAuth({
        provider,
        options: {
          redirectTo,
          skipBrowserRedirect: true,
        },
      });
      if (error) throw error;
      if (data?.url) window.location.href = data.url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "소셜 로그인에 실패했습니다.");
      setOauthLoading(null);
    }
  };

  const handleMagicLink = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    setError("");
    try {
      // 진입 의도(next)를 Magic Link 왕복 후에도 유지하기 위해 callback에 전달
      const nextPath = searchParams.get("next");
      const callbackUrl = nextPath
        ? `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`
        : `${window.location.origin}/auth/callback`;
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: {
          emailRedirectTo: callbackUrl,
        },
      });
      if (error) throw error;
      setSent(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "링크 발송에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-dvh bg-[#F4F3EE] flex flex-col px-6 pt-safe-top pb-safe-bottom overflow-hidden">
      {/* 뒤로가기 */}
      <div className="flex items-center pt-4 pb-2 flex-shrink-0">
        <Link
          href="/"
          className="w-9 h-9 flex items-center justify-center -ml-1 text-[#1A1A1A]"
          aria-label="홈으로"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M12 4L6 10L12 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </Link>
      </div>

      {/* 본문 */}
      <div className="flex-1 flex flex-col max-w-sm mx-auto w-full justify-between py-4">
        {/* 상단: 타이틀 + 폼 */}
        <div>
          {/* 로고 + 타이틀 */}
          <div className="mb-6">
            <p className="font-headline font-bold text-sm text-[#AEAAA5] mb-1">꿈신문사</p>
            <h1 className="font-headline font-bold text-3xl text-[#1A1A1A] leading-tight">
              다시 만나요
            </h1>
          </div>

          {sent ? (
            /* 발송 완료 상태 */
            <div className="p-5 bg-[rgba(201,168,76,0.12)] border-l-4 border-[#C9A84C] rounded-r-lg space-y-2">
              <p className="font-bold text-[#1A1A1A]">링크를 발송했습니다</p>
              <p className="text-sm text-[#6B6869] leading-relaxed">
                <strong>{email}</strong>로 로그인 링크를 보냈습니다.<br />
                링크를 클릭하면 바로 입장됩니다.
              </p>
              <button
                className="text-sm text-[#AEAAA5] underline mt-2"
                onClick={() => setSent(false)}
              >
                다른 이메일로 다시 보내기
              </button>
            </div>
          ) : (
            /* Magic Link 폼 */
            <form onSubmit={handleMagicLink} className="space-y-3">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="이메일"
                required
                autoFocus
                className="app-input"
              />

              {error && (
                <p className="text-sm text-[#CC2200] px-1">{error}</p>
              )}

              <div className="pt-1">
                <button
                  type="submit"
                  disabled={loading}
                  className="app-btn-primary disabled:opacity-50"
                >
                  {loading ? (
                    <span className="flex items-center gap-2">
                      <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                      </svg>
                      발송 중
                    </span>
                  ) : (
                    "로그인 링크 받기"
                  )}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* 하단: 소셜 로그인 + 처음 방문 */}
        <div>
          {/* 구분선 */}
          <div className="flex items-center gap-3 mb-4">
            <div className="flex-1 h-px bg-[#E0DFD8]" />
            <span className="text-xs font-bold text-[#AEAAA5]">또는</span>
            <div className="flex-1 h-px bg-[#E0DFD8]" />
          </div>

          {/* 소셜 로그인 */}
          <div className="space-y-3">
            <button
              type="button"
              onClick={() => handleOAuth("kakao")}
              disabled={!!oauthLoading}
              className="w-full font-bold text-base rounded-2xl py-4 flex items-center justify-center gap-2 disabled:opacity-50"
              style={{ minHeight: 52, background: "#FEE500", color: "#191919" }}
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 3C6.477 3 2 6.477 2 10.75c0 2.763 1.847 5.19 4.621 6.498L5.43 21.64c-.067.248.167.46.388.312l4.985-3.324c.394.04.795.062 1.197.062 5.523 0 10-3.477 10-7.75C22 6.477 17.523 3 12 3z" />
              </svg>
              {oauthLoading === "kakao" ? "연결 중..." : "카카오로 계속하기"}
            </button>

            <button
              type="button"
              onClick={() => handleOAuth("google")}
              disabled={!!oauthLoading}
              className="app-btn-secondary gap-2 disabled:opacity-50"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
              </svg>
              {oauthLoading === "google" ? "연결 중..." : "구글로 계속하기"}
            </button>
          </div>

          {/* 하단 링크 */}
          <p className="text-center text-sm text-[#6B6869] mt-5">
            처음이신가요?{" "}
            <Link href="/" className="font-bold text-[#1A1A1A] hover:underline">
              꿈신문 받기 →
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#F4F3EE] flex items-center justify-center">
          <div className="skeleton h-8 w-32" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
