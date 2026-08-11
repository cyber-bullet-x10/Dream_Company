"use client";

import { useState, useRef } from "react";
import Link from "next/link";
import { headlineApi } from "@/lib/api";

type Result = { headline: string; subhead: string; year: number };

export default function HeadlinePage() {
  const [name, setName] = useState("");
  const [dream, setDream] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || dream.trim().length < 2) {
      setError("이름과 꿈을 입력해주세요.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const r = await headlineApi.generate(name.trim(), dream.trim());
      setResult(r.data as Result);
    } catch (err: unknown) {
      const e2 = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e2.response?.data?.detail || e2.message || "잠시 후 다시 시도해주세요.");
    } finally {
      setLoading(false);
    }
  };

  const handleShare = async () => {
    if (!result) return;
    const text = `📰 ${result.year}년, 나의 미래 헤드라인\n\n"${result.headline}"\n${result.subhead}\n\n#꿈신문 에서 내 미래 헤드라인 만들기`;
    const url = typeof window !== "undefined" ? `${window.location.origin}/headline` : "";
    try {
      if (navigator.share) {
        await navigator.share({ title: "꿈신문 · 나의 미래 헤드라인", text, url });
      } else {
        await navigator.clipboard.writeText(`${text}\n${url}`);
        alert("헤드라인이 복사되었어요. 붙여넣어 공유해보세요!");
      }
    } catch {
      /* 사용자가 공유를 취소한 경우 무시 */
    }
  };

  const reset = () => {
    setResult(null);
    setError("");
  };

  return (
    <div className="min-h-dvh bg-[#F4F3EE] px-6 pt-safe-top pb-24">
      <div className="max-w-md mx-auto w-full">
        {/* 헤더 */}
        <div className="pt-10 pb-6">
          <p className="font-headline font-bold text-sm text-[#AEAAA5] mb-1">꿈신문 · 무료 미리보기</p>
          <h1 className="font-headline font-bold text-3xl text-[#1A1A1A] leading-tight">
            {result ? "당신의 미래 1면" : <>당신의 꿈이<br />신문 1면이 된다면?</>}
          </h1>
          {!result && (
            <p className="text-sm text-[#6B6869] mt-3 leading-relaxed">
              이름과 되고 싶은 미래를 적어보세요.<br />
              지금 이 순간, 그 미래를 사는 당신의 신문 헤드라인을 만들어드려요.
            </p>
          )}
        </div>

        {!result ? (
          <form onSubmit={handleGenerate} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-[#6B6869] mb-1.5">이름</label>
              <input
                className="app-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="예: 김지우"
                maxLength={20}
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-[#6B6869] mb-1.5">되고 싶은 미래</label>
              <textarea
                className="app-input resize-none"
                rows={3}
                value={dream}
                onChange={(e) => setDream(e.target.value)}
                placeholder="예: 카네기홀에서 연주하는 피아니스트가 되는 것"
                maxLength={200}
              />
            </div>

            {error && <p className="text-sm text-[#CC2200] px-1">{error}</p>}

            <button type="submit" disabled={loading} className="app-btn-primary disabled:opacity-50">
              {loading ? "편집국이 쓰는 중..." : "내 미래 헤드라인 만들기"}
            </button>
            <p className="text-center text-xs text-[#AEAAA5]">
              입력한 정보는 저장되지 않아요 · 로그인 불필요
            </p>
          </form>
        ) : (
          <div className="space-y-5">
            {/* 신문 카드 */}
            <div
              ref={cardRef}
              className="bg-[#FBFAF5] border border-[#1A1A1A] p-6 shadow-sm"
              style={{ fontFamily: "var(--font-headline, serif)" }}
            >
              <div className="flex items-center justify-between border-b-2 border-[#1A1A1A] pb-2 mb-4">
                <span className="font-headline font-bold text-[#1A1A1A] text-sm tracking-widest">꿈신문</span>
                <span className="text-[11px] text-[#6B6869]">{result.year}년</span>
              </div>
              <h2 className="font-headline font-bold text-[#1A1A1A] text-2xl leading-snug mb-3">
                {result.headline}
              </h2>
              <p className="text-sm text-[#3A3A3A] leading-relaxed border-t border-[#DDD] pt-3">
                {result.subhead}
              </p>
            </div>

            <div className="flex gap-3">
              <button onClick={handleShare} className="flex-1 app-btn-secondary">
                공유하기
              </button>
              <button onClick={reset} className="flex-1 app-btn-secondary">
                다시 만들기
              </button>
            </div>

            {/* 전환 CTA */}
            <div className="app-card p-5 text-center">
              <p className="font-headline font-bold text-[#1A1A1A] text-lg leading-snug">
                이 이야기가<br />매일 아침 배달된다면?
              </p>
              <p className="text-sm text-[#6B6869] mt-2 leading-relaxed">
                3일 동안 무료로, {name.trim()}님의 미래가<br />신문으로 매일 이어집니다.
              </p>
              <Link
                href="/order/new"
                className="app-btn-primary mt-4"
                onClick={() => {
                  // 입력한 이름·꿈을 주문폼으로 전달(로그인 왕복을 거쳐도 유지) — 재입력 마찰 제거
                  try {
                    localStorage.setItem(
                      "dream_prefill",
                      JSON.stringify({ name: name.trim(), dream: dream.trim() })
                    );
                  } catch { /* 저장 실패해도 이동은 진행 */ }
                }}
              >
                3일 무료로 시작하기 →
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
