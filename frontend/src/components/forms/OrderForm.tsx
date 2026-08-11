"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ordersApi, creditsApi, OrderCreate } from "@/lib/api";

const DURATION_OPTIONS = [
  { days: 7,  label: "7일",  credits: 7,  desc: "기본" },
  { days: 14, label: "14일", credits: 14, desc: "집중" },
  { days: 30, label: "30일", credits: 30, desc: "완성" },
] as const;

const FUTURE_YEARS = [2027, 2028, 2029, 2030];

function StepBar({ current, total }: { current: number; total: number }) {
  return (
    <div style={{ display: "flex", gap: 5, padding: "0 24px 0" }}>
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} style={{
          flex: 1, height: 3, borderRadius: 99,
          background: i < current ? "#1A1A1A" : "#E0DFD8",
          transition: "background 0.3s",
        }} />
      ))}
    </div>
  );
}

/* ── 공통 레이아웃 래퍼 ──
   ⚠️ 이 컴포넌트들은 반드시 모듈 최상위에 둔다.
   OrderForm 내부에 정의하면 매 렌더마다 새 컴포넌트 타입이 생성돼
   입력창이 언마운트/리마운트 → 타이핑 중 포커스가 튕긴다. */
function Screen({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      position: "fixed",
      inset: 0,
      background: "#F4F3EE",
      display: "flex",
      justifyContent: "center",
      overflow: "hidden",
      zIndex: 10,
    }}>
      <div style={{
        width: "100%",
        maxWidth: 430,
        height: "100%",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        {children}
      </div>
    </div>
  );
}

/* ── 공통 헤더 ── */
function Header({ step: s, title, sub }: { step: number; title: React.ReactNode; sub?: string }) {
  return (
    <div style={{ padding: "14px 24px 0" }}>
      <StepBar current={s} total={3} />
      <p style={{ margin: "12px 0 2px", fontSize: 10, fontWeight: "bold", color: "#AEAAA5", letterSpacing: "0.2em" }}>
        {s} / 3
      </p>
      <h1 style={{ margin: 0, fontSize: 22, fontWeight: "bold", color: "#1A1A1A", lineHeight: 1.25, fontFamily: "Georgia, serif" }}>
        {title}
      </h1>
      {sub && <p style={{ margin: "4px 0 0", fontSize: 12, color: "#6B6869" }}>{sub}</p>}
    </div>
  );
}

/* ── 공통 하단 버튼 영역 ── */
function Footer({ primary, primaryDisabled, onPrimary, onBack, hint, error, loading }: {
  primary: React.ReactNode;
  primaryDisabled?: boolean;
  onPrimary: () => void;
  onBack?: () => void;
  hint?: string;
  error?: string;
  loading?: boolean;
}) {
  return (
    <div style={{ padding: "10px 24px 20px", display: "flex", flexDirection: "column", gap: 8 }}>
      {error && (
        <div style={{ background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 10, padding: "8px 12px", fontSize: 12, color: "#CC2200" }}>
          {error}
        </div>
      )}
      <button
        onClick={onPrimary}
        disabled={primaryDisabled}
        style={{
          background: primaryDisabled ? "#C8C6BF" : "#1A1A1A",
          color: primaryDisabled ? "#8A8880" : "#F5F0E8",
          border: "none",
          borderRadius: 14,
          padding: "15px 0",
          fontSize: 15,
          fontWeight: "bold",
          cursor: primaryDisabled ? "not-allowed" : "pointer",
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
        }}
      >
        {loading && (
          <svg style={{ animation: "spin 1s linear infinite", width: 16, height: 16 }} viewBox="0 0 24 24" fill="none">
            <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity=".25"/>
            <path fill="currentColor" opacity=".75" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
          </svg>
        )}
        {primary}
      </button>
      {onBack && (
        <button onClick={onBack} style={{
          background: "transparent", border: "none", color: "#6B6869",
          fontSize: 13, padding: "6px 0", cursor: "pointer",
        }}>
          ← 이전
        </button>
      )}
      {hint && <p style={{ margin: 0, textAlign: "center", fontSize: 11, color: "#AEAAA5" }}>{hint}</p>}
    </div>
  );
}

/* ── STEP 2 입력 필드 ── */
function Input({ label, value, onChange, placeholder, autoFocus }: {
  label: string; value: string; onChange: (v: string) => void; placeholder: string; autoFocus?: boolean;
}) {
  return (
    <div>
      <p style={{ margin: "0 0 5px", fontSize: 10, fontWeight: "bold", color: "#AEAAA5", letterSpacing: "0.2em", textTransform: "uppercase" }}>{label}</p>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        style={{
          width: "100%", border: "1.5px solid #E0DFD8", borderRadius: 12,
          padding: "11px 14px", fontSize: 14, color: "#1A1A1A",
          background: "#fff", outline: "none", boxSizing: "border-box",
        }}
      />
    </div>
  );
}

/* ── STEP 3 체크마크 ── */
function Checkmark({ on }: { on: boolean }) {
  return (
    <div style={{
      width: 20, height: 20, borderRadius: "50%", flexShrink: 0,
      border: on ? "none" : "1.5px solid #E0DFD8",
      background: on ? "#1A1A1A" : "transparent",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {on && <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5L4 7L8 3" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
    </div>
  );
}

export default function OrderForm() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [creditBalance, setCreditBalance] = useState<number | null>(null);
  const [form, setForm] = useState<OrderCreate>({
    dream_description: "",
    protagonist_name: "",
    target_role: "",
    target_company: "",
    duration_days: 3,
    future_year: 2030,
    payment_type: "free",
  });

  useEffect(() => {
    creditsApi.getBalance().then((r) => setCreditBalance(r.data.credits)).catch(() => {});

    // 헤드라인 생성기(/headline)에서 넘어온 이름·꿈을 자동 채움 — 로그인 왕복을 거쳐도
    // localStorage에 남아 있어 콜드 방문자가 다시 입력할 필요 없이 바로 시작할 수 있다.
    try {
      const raw = typeof window !== "undefined" ? localStorage.getItem("dream_prefill") : null;
      if (raw) {
        const p = JSON.parse(raw);
        setForm((f) => ({
          ...f,
          dream_description: p.dream ? String(p.dream).slice(0, 500) : f.dream_description,
          protagonist_name: p.name ? String(p.name).slice(0, 20) : f.protagonist_name,
        }));
        localStorage.removeItem("dream_prefill");
      }
    } catch { /* prefill 없거나 손상 시 무시 */ }
  }, []);

  const isFree = form.payment_type === "free";
  const isCredits = form.payment_type === "credits";
  const selectedOption = DURATION_OPTIONS.find((o) => o.days === form.duration_days)!;
  const hasEnoughCredits = creditBalance !== null && creditBalance >= (isCredits ? selectedOption.credits : 0);

  const canNext1 = form.dream_description.trim().length >= 10;
  const canNext2 = form.protagonist_name.trim().length >= 1 && form.target_role.trim().length >= 1;

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    try {
      const createRes = await ordersApi.create(form);
      const orderId = createRes.data.id;
      const name = encodeURIComponent(form.protagonist_name || "");
      const role = encodeURIComponent(form.target_role || "");

      if (isFree || isCredits) {
        await ordersApi.start(orderId);
        router.push(`/order/generating?orderId=${orderId}&name=${name}&role=${role}`);
        return;
      }

      const { paymentApi } = await import("@/lib/api");
      const sessionRes = await paymentApi.createCheckoutSession(orderId);
      window.location.href = sessionRes.data.checkout_url;
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e.response?.data?.detail || e.message || "의뢰 생성에 실패했습니다.");
      setLoading(false);
    }
  };

  /* ─────────── STEP 1 ─────────── */
  if (step === 1) {
    return (
      <Screen>
        <Header step={1} title={<>당신의 꿈을<br />들려주세요</>} sub="기자단이 당신의 이야기를 신문으로 만듭니다" />
        <div style={{ flex: 1, padding: "12px 24px 0", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <textarea
            value={form.dream_description}
            onChange={(e) => setForm({ ...form, dream_description: e.target.value })}
            placeholder="예: 구글 코리아의 AI 연구소장이 되어 세계적인 논문을 발표하고, 후배들을 이끄는 리더가 되고 싶습니다..."
            autoFocus
            style={{
              flex: 1,
              width: "100%",
              resize: "none",
              border: "1.5px solid #E0DFD8",
              borderRadius: 14,
              padding: "14px",
              fontSize: 14,
              lineHeight: 1.7,
              color: "#1A1A1A",
              background: "#fff",
              fontFamily: "inherit",
              outline: "none",
              boxSizing: "border-box",
              minHeight: 0,
            }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 2px 0", fontSize: 11, color: "#AEAAA5" }}>
            <span>최소 10자 이상</span>
            <span style={{ fontWeight: "bold", color: form.dream_description.length >= 10 ? "#1A1A1A" : "#AEAAA5" }}>
              {form.dream_description.length}자
            </span>
          </div>
        </div>
        <Footer
          primary="다음 →"
          primaryDisabled={!canNext1}
          onPrimary={() => setStep(2)}
          error={error}
          loading={loading}
        />
      </Screen>
    );
  }

  /* ─────────── STEP 2 ─────────── */
  if (step === 2) {
    return (
      <Screen>
        <Header step={2} title={<>신문의 주인공은<br />누구인가요?</>} sub="기사에 실명으로 등장합니다" />
        <div style={{ flex: 1, padding: "12px 24px 0", display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>
          <Input label="이름 *" value={form.protagonist_name}
            onChange={(v) => setForm({ ...form, protagonist_name: v })}
            placeholder="홍길동" autoFocus />
          <Input label="목표 역할 *" value={form.target_role}
            onChange={(v) => setForm({ ...form, target_role: v })}
            placeholder="예: AI 연구소장, 스타트업 대표" />
          <Input label="목표 회사 (선택)" value={form.target_company || ""}
            onChange={(v) => setForm({ ...form, target_company: v })}
            placeholder="예: 삼성전자, Google" />
          <div>
            <p style={{ margin: "0 0 6px", fontSize: 10, fontWeight: "bold", color: "#AEAAA5", letterSpacing: "0.2em", textTransform: "uppercase" }}>꿈이 이루어지는 해</p>
            <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 2 }}>
              {FUTURE_YEARS.map((year) => (
                <button key={year} type="button"
                  onClick={() => setForm({ ...form, future_year: year })}
                  style={{
                    flexShrink: 0,
                    padding: "7px 14px",
                    borderRadius: 99,
                    fontSize: 13,
                    fontWeight: "bold",
                    border: form.future_year === year ? "none" : "1.5px solid #E0DFD8",
                    background: form.future_year === year ? "#1A1A1A" : "#fff",
                    color: form.future_year === year ? "#fff" : "#6B6869",
                    cursor: "pointer",
                  }}
                >
                  {year}년
                </button>
              ))}
            </div>
          </div>
        </div>
        <Footer
          primary="다음 →"
          primaryDisabled={!canNext2}
          onPrimary={() => setStep(3)}
          onBack={() => setStep(1)}
          error={error}
          loading={loading}
        />
      </Screen>
    );
  }

  /* ─────────── STEP 3 ─────────── */
  const submitLabel = () => {
    if (loading) return "준비 중...";
    if (isFree) return "무료로 시작하기 🗞";
    if (isCredits) return `${selectedOption.credits}크레딧으로 시작하기`;
    return "결제하고 시작하기";
  };

  return (
    <Screen>
      <Header step={3} title={<>어떻게<br />시작할까요?</>} />

      {/* 크레딧 잔액 */}
      {creditBalance !== null && (
        <div style={{ padding: "4px 24px 0", display: "flex", gap: 4, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "#6B6869" }}>
            보유 <strong style={{ color: "#1A1A1A" }}>{creditBalance}크레딧</strong>
          </span>
          <span style={{ fontSize: 11, color: "#AEAAA5" }}>·</span>
          <Link href="/credits" style={{ fontSize: 12, color: "#CC2200", textDecoration: "underline" }}>충전하기</Link>
        </div>
      )}

      <div style={{ flex: 1, padding: "10px 24px 0", display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>

        {/* 무료 카드 */}
        <button type="button"
          onClick={() => setForm({ ...form, payment_type: "free", duration_days: 3 })}
          style={{
            background: "#fff", border: isFree ? "2px solid #1A1A1A" : "1.5px solid #E0DFD8",
            borderRadius: 14, padding: "14px 16px", textAlign: "left", cursor: "pointer", width: "100%",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
          <div>
            <span style={{ display: "inline-block", background: "#D4F1DE", color: "#1A6B35", fontSize: 10, fontWeight: "bold", padding: "2px 8px", borderRadius: 99, marginBottom: 4 }}>무료</span>
            <p style={{ margin: 0, fontSize: 14, fontWeight: "bold", color: "#1A1A1A" }}>3일 체험 시리즈</p>
            <p style={{ margin: "2px 0 0", fontSize: 12, color: "#6B6869" }}>결제 없이 즉시 시작</p>
          </div>
          <Checkmark on={isFree} />
        </button>

        {/* 크레딧 카드 */}
        <button type="button"
          onClick={() => setForm({ ...form, payment_type: "credits", duration_days: form.duration_days < 7 ? 7 : form.duration_days })}
          style={{
            background: "#fff", border: isCredits ? "2px solid #1A1A1A" : "1.5px solid #E0DFD8",
            borderRadius: 14, padding: "14px 16px", textAlign: "left", cursor: "pointer", width: "100%",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
          <div>
            <span style={{ display: "inline-block", background: "#1A1A1A", color: "#fff", fontSize: 10, fontWeight: "bold", padding: "2px 8px", borderRadius: 99, marginBottom: 4 }}>크레딧</span>
            <p style={{ margin: 0, fontSize: 14, fontWeight: "bold", color: "#1A1A1A" }}>보유 크레딧으로 시작</p>
            <p style={{ margin: "2px 0 0", fontSize: 12, color: creditBalance === 0 ? "#CC2200" : "#6B6869" }}>
              {creditBalance === null ? "로딩 중..." : creditBalance > 0 ? `${creditBalance}크레딧 보유 · 즉시 시작` : "크레딧 없음 — 충전 필요"}
            </p>
          </div>
          <Checkmark on={isCredits} />
        </button>

        {/* 기간 선택 (크레딧 선택 시만) */}
        {isCredits && (
          <div style={{ background: "#fff", border: "1.5px solid #E0DFD8", borderRadius: 14, padding: "12px 14px" }}>
            <p style={{ margin: "0 0 8px", fontSize: 10, fontWeight: "bold", color: "#AEAAA5", letterSpacing: "0.2em", textTransform: "uppercase" }}>시리즈 기간</p>
            <div style={{ display: "flex", gap: 6 }}>
              {DURATION_OPTIONS.map((opt) => {
                const insufficient = creditBalance !== null && creditBalance < opt.credits;
                const isSelected = form.duration_days === opt.days;
                return (
                  <button key={opt.days} type="button"
                    onClick={() => !insufficient && setForm({ ...form, duration_days: opt.days })}
                    style={{
                      flex: 1, padding: "10px 4px", borderRadius: 10, textAlign: "center", cursor: insufficient ? "not-allowed" : "pointer",
                      border: isSelected ? "none" : "1.5px solid #E0DFD8",
                      background: isSelected ? "#1A1A1A" : insufficient ? "#F4F3EE" : "#fff",
                      color: isSelected ? "#fff" : insufficient ? "#AEAAA5" : "#1A1A1A",
                    }}>
                    <div style={{ fontSize: 13, fontWeight: "bold" }}>{opt.label}</div>
                    <div style={{ fontSize: 11, marginTop: 1, opacity: 0.7 }}>{opt.credits}크레딧</div>
                  </button>
                );
              })}
            </div>
            {isCredits && !hasEnoughCredits && (
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, alignItems: "center" }}>
                <p style={{ margin: 0, fontSize: 11, color: "#CC2200" }}>
                  {selectedOption.credits - (creditBalance ?? 0)}크레딧 부족
                </p>
                <Link href="/credits" style={{ fontSize: 11, fontWeight: "bold", color: "#CC2200" }}>충전하기 →</Link>
              </div>
            )}
          </div>
        )}

      </div>

      <Footer
        primary={submitLabel()}
        primaryDisabled={loading || (isCredits && !hasEnoughCredits)}
        onPrimary={handleSubmit}
        onBack={() => setStep(2)}
        hint="제출 후 첫 신문이 곧 발행됩니다"
        error={error}
        loading={loading}
      />
    </Screen>
  );
}
