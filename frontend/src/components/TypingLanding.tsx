"use client";

import { useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";

type Phase =
  | "masthead"
  | "typing-prefix"
  | "name-input"
  | "typing-suffix"
  | "email"
  | "sent";

const PREFIX = "2027년 봄, ";
const SUFFIX =
  "씨의 이름이 처음으로 뉴스 첫 면에 실렸다. " +
  "꿈신문사 기자단의 단독 취재로 밝혀진 이 소식에 수십만 명이 뜨겁게 반응했다. " +
  "수년간의 조용한 준비 끝에 세상 앞에 선 그의 모습은, 오늘 이 시대를 살아가는 많은 이들에게 " +
  "새로운 가능성을 보여주고 있다.";
const TYPING_MS = 50;

export default function TypingLanding() {
  const [phase, setPhase] = useState<Phase>("masthead");
  const [prefix, setPrefix] = useState("");
  const [name, setName] = useState("");
  const [suffix, setSuffix] = useState("");
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState("");
  const [sending, setSending] = useState(false);

  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (phase !== "masthead") return;
    const t = setTimeout(() => setPhase("typing-prefix"), 700);
    return () => clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase !== "typing-prefix") return;
    let i = 0;
    const id = setInterval(() => {
      i++;
      setPrefix(PREFIX.slice(0, i));
      if (i >= PREFIX.length) { clearInterval(id); setPhase("name-input"); }
    }, TYPING_MS);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    if (phase === "name-input") {
      const t = setTimeout(() => nameRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [phase]);

  useEffect(() => {
    if (phase !== "typing-suffix") return;
    let i = 0;
    const id = setInterval(() => {
      i++;
      setSuffix(SUFFIX.slice(0, i));
      if (i >= SUFFIX.length) { clearInterval(id); setTimeout(() => setPhase("email"), 500); }
    }, TYPING_MS);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    if (phase === "email") {
      const t = setTimeout(() => emailRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [phase]);

  const handleNameKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && name.trim()) {
      e.preventDefault();
      setPhase("typing-suffix");
    }
  };

  const handleEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setSending(true);
    setEmailError("");
    try {
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        options: {
          data: { name: name.trim() },
          emailRedirectTo: `${window.location.origin}/auth/callback`,
        },
      });
      if (error) throw error;
      setPhase("sent");
    } catch (err: unknown) {
      setEmailError(err instanceof Error ? err.message : "오류가 발생했습니다.");
    } finally {
      setSending(false);
    }
  };

  const showNameText = !["masthead", "typing-prefix", "name-input"].includes(phase);
  const showSuffix = ["typing-suffix", "email", "sent"].includes(phase);

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700&display=swap');
        .tl-name-input::placeholder { color: #C9A84C; opacity: 0.8; }
        .tl-name-input { caret-color: #1A2744; }
      `}</style>

      <div style={{ minHeight: "100dvh", background: "#F7F4EE", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", fontFamily: "'Noto Serif KR', serif", padding: "2rem 1.5rem", boxSizing: "border-box" }}>

        <div style={{ opacity: phase === "masthead" ? 0 : 1, transition: "opacity 0.5s ease", fontSize: "clamp(1.6rem, 5vw, 2.5rem)", fontWeight: 700, color: "#1A2744", letterSpacing: "0.2em", borderBottom: "3px double #1A2744", paddingBottom: "0.4em", marginBottom: "3rem", textAlign: "center", userSelect: "none" }}>
          꿈신문사
        </div>

        {phase !== "masthead" && (
          <div style={{ maxWidth: "620px", width: "100%" }}>
            <p style={{ fontSize: "clamp(1.1rem, 3.2vw, 1.45rem)", lineHeight: 2, color: "#2C2C2C", margin: "0 0 0.5rem", wordBreak: "keep-all" }}>
              {prefix}
              {phase === "name-input" && (
                <input
                  ref={nameRef}
                  className="tl-name-input"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={handleNameKey}
                  placeholder="이름"
                  maxLength={20}
                  style={{ display: "inline", width: `${Math.max(name.length || 1, 4) + 1}ch`, minWidth: "4ch", background: "transparent", border: "none", borderBottom: "2px solid #C9A84C", outline: "none", fontSize: "inherit", fontFamily: "inherit", fontWeight: 700, color: "#1A2744", lineHeight: "inherit", padding: "0 2px", verticalAlign: "baseline" }}
                />
              )}
              {showNameText && <span style={{ color: "#1A2744", fontWeight: 700 }}>{name}</span>}
              {showSuffix && suffix}
            </p>

            {phase === "name-input" && name.trim() && (
              <p style={{ fontSize: "0.8rem", color: "#888", fontFamily: "sans-serif" }}>Enter 키를 눌러 계속하세요</p>
            )}

            {phase === "email" && (
              <div style={{ marginTop: "2.5rem" }}>
                <p style={{ fontSize: "clamp(0.95rem, 2.5vw, 1.1rem)", color: "#444", marginBottom: "1.2rem", fontFamily: "system-ui, sans-serif" }}>
                  이 기사 전체를 받아보시겠어요?
                </p>
                <form onSubmit={handleEmailSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                  <input
                    ref={emailRef}
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="이메일 주소"
                    required
                    style={{ padding: "0.75rem 1rem", border: "1px solid #C9A84C", background: "rgba(255,255,255,0.7)", fontSize: "1rem", fontFamily: "system-ui, sans-serif", color: "#1A2744", outline: "none", width: "100%", boxSizing: "border-box" }}
                  />
                  <p style={{ fontSize: "0.72rem", color: "#999", margin: 0, fontFamily: "system-ui, sans-serif", lineHeight: 1.5 }}>
                    이름과 이메일은 신문 배달 목적으로만 사용되며 안전하게 보관됩니다.
                  </p>
                  {emailError && <p style={{ color: "#c0392b", fontSize: "0.85rem", margin: 0, fontFamily: "system-ui, sans-serif" }}>{emailError}</p>}
                  <button type="submit" disabled={sending} style={{ padding: "0.85rem", background: sending ? "#aaa" : "#1A2744", color: "#F7F4EE", border: "none", fontSize: "1rem", fontFamily: "system-ui, sans-serif", cursor: sending ? "not-allowed" : "pointer", letterSpacing: "0.05em", transition: "background 0.2s" }}>
                    {sending ? "발송 중..." : "꿈신문 받기"}
                  </button>
                </form>
              </div>
            )}

            {phase === "sent" && (
              <div style={{ marginTop: "2.5rem", padding: "1.5rem", background: "rgba(201,168,76,0.12)", borderLeft: "4px solid #C9A84C", fontFamily: "system-ui, sans-serif" }}>
                <p style={{ margin: 0, fontSize: "1rem", color: "#1A2744", fontWeight: 600 }}>링크를 발송했습니다</p>
                <p style={{ margin: "0.5rem 0 0", fontSize: "0.875rem", color: "#555", lineHeight: 1.6 }}>
                  <strong>{email}</strong>로 로그인 링크를 보냈습니다.<br />
                  링크를 클릭하면 {name}씨의 신문이 시작됩니다.
                </p>
              </div>
            )}
          </div>
        )}

        {/* 하단 진입점 — 재방문 유저 + 공급측(기자단/스폰서) */}
        {phase !== "masthead" && (
          <div style={{ marginTop: "3rem", textAlign: "center", fontFamily: "system-ui, sans-serif", display: "flex", flexDirection: "column", alignItems: "center", gap: "1.1rem" }}>
            {phase !== "sent" && (
              <a href="/login" style={{ fontSize: "0.8rem", color: "#888", textDecoration: "none", borderBottom: "1px solid #ccc", paddingBottom: "1px" }}>
                이미 구독 중이에요 →
              </a>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: "0.85rem", fontSize: "0.75rem", color: "#A89F8C" }}>
              <a href="/writer/apply" style={{ color: "#A89F8C", textDecoration: "none" }}>기자단 지원</a>
              <span style={{ opacity: 0.5 }}>·</span>
              <a href="/for-sponsors" style={{ color: "#A89F8C", textDecoration: "none" }}>스폰서 문의</a>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
