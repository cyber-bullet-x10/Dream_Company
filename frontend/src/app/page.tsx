"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePortal } from "@/components/PortalProvider";
import { writerApi, sponsorApi, ordersApi, Order, getApiBaseUrl } from "@/lib/api";
import AppBar from "@/components/AppBar";
import { getStreak, recordActivity, StreakData } from "@/hooks/useStreak";
import TypingLanding from "@/components/TypingLanding";

/* ─────────────────────────────────────────
   스플래시 로딩 화면
───────────────────────────────────────── */
// 콜드스타트(무료 서버가 잠들어 첫 요청이 오래 걸릴 때) 위트 로딩 문구.
// 브랜드 톤(편집국/기자단/윤전기). 빠른 로딩에선 안 보이도록 2.5초 후부터 순환.
const SPLASH_WITTY = [
  "편집국 기자단을 깨우는 중…",
  "밤새 취재한 기자를 깨우는 중…",
  "잠든 윤전기에 시동을 거는 중…",
  "잉크를 데우고 1면을 펴는 중…",
];

function SplashScreen() {
  const [msgIdx, setMsgIdx] = useState<number>(-1);
  useEffect(() => {
    // 2.5초 안에 뜨면(웜) 문구 없이 넘어감. 오래 걸리면 그때부터 순환 표시.
    const start = setTimeout(() => setMsgIdx(0), 2500);
    const cycle = setInterval(
      () => setMsgIdx((i) => (i < 0 ? -1 : (i + 1) % SPLASH_WITTY.length)),
      3500
    );
    return () => {
      clearTimeout(start);
      clearInterval(cycle);
    };
  }, []);

  return (
    <div className="h-dvh bg-[#1A1A1A] flex flex-col items-center justify-center gap-6">
      {/* 신문 이모지 bounce */}
      <div style={{ animation: "splashBounce 1.2s ease-in-out infinite" }} className="text-6xl select-none">
        🗞️
      </div>

      {/* 브랜드 */}
      <div className="text-center">
        <p className="font-headline font-bold text-white text-xl tracking-widest">꿈신문사</p>
        <p className="text-[#6B6869] text-xs mt-1 tracking-wider">DREAM NEWSPAPER</p>
      </div>

      {/* 점 세 개 로딩 */}
      <div className="flex gap-2">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-[#CC2200]"
            style={{ animation: `splashDot 1.2s ease-in-out ${i * 0.2}s infinite` }}
          />
        ))}
      </div>

      {/* 콜드스타트 위트 문구 (오래 걸릴 때만) */}
      <p
        className="text-[#8A8580] text-sm h-5 transition-opacity duration-500"
        style={{ opacity: msgIdx >= 0 ? 1 : 0 }}
      >
        {msgIdx >= 0 ? SPLASH_WITTY[msgIdx] : ""}
      </p>

      <style>{`
        @keyframes splashBounce {
          0%, 100% { transform: translateY(0) rotate(-3deg); }
          50% { transform: translateY(-12px) rotate(3deg); }
        }
        @keyframes splashDot {
          0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1.2); }
        }
      `}</style>
    </div>
  );
}

/* ─────────────────────────────────────────
   스켈레톤 로딩
───────────────────────────────────────── */
function SkeletonCard() {
  return (
    <div className="app-card p-4 space-y-3">
      <div className="skeleton h-4 w-3/4" />
      <div className="skeleton h-3 w-1/2" />
      <div className="skeleton h-3 w-full" />
      <div className="skeleton h-3 w-4/5" />
    </div>
  );
}

/* ─────────────────────────────────────────
   유저: 홈 피드
───────────────────────────────────────── */
/* ─────────────────────────────────────────
   "서비스 어떻게 되나요?" 3단계 미리보기
───────────────────────────────────────── */
function HowItWorks() {
  const steps = [
    { step: "01", title: "꿈을 의뢰해요", desc: "되고 싶은 모습을 자유롭게 적어주세요", icon: "✍️" },
    { step: "02", title: "기자단이 써요", desc: "전담 기자단이 당신의 꿈을 신문 기사로 만들어요", icon: "📰" },
    { step: "03", title: "매일 아침 도착해요", desc: "오전 8시, 미래의 당신 이야기가 신문으로 와요", icon: "☀️" },
  ];
  return (
    <div className="space-y-2">
      {steps.map((s) => (
        <div key={s.step} className="flex items-center gap-4 app-card p-4">
          <div className="text-2xl w-10 text-center flex-shrink-0">{s.icon}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-[10px] font-bold text-[#AEAAA5] tracking-widest">{s.step}</span>
              <p className="font-bold text-[#1A1A1A] text-sm">{s.title}</p>
            </div>
            <p className="text-xs text-[#6B6869]">{s.desc}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function UserHome() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [streak, setStreak] = useState<StreakData>({ days: 0, lastActive: null, bestStreak: 0, isActiveToday: false });
  const [companionCount, setCompanionCount] = useState<number | null>(null);
  const [companionRole, setCompanionRole] = useState<string>("");

  useEffect(() => {
    const s = recordActivity();
    setStreak(s);

    // 꿈 동료 배너 요청을 별도 함수로 분리 — 주문 로딩과 독립적으로(병렬로) 실행한다.
    const ROLE_CACHE_KEY = "dream_companion_role";
    const DATA_CACHE_KEY = "dream_companion_data";

    // 지난 방문의 배너 값(count+role)을 첫 렌더에 즉시 표시 — 네트워크(~0.6초)를 기다리지
    // 않고 다른 섹션과 '한 번에' 뜬다. 실제 값은 아래 fetch로 백그라운드 갱신.
    try {
      const cached =
        typeof window !== "undefined" ? localStorage.getItem(DATA_CACHE_KEY) : null;
      if (cached) {
        const d = JSON.parse(cached);
        if (typeof d.count === "number") setCompanionCount(d.count);
        if (d.role) setCompanionRole(d.role);
      }
    } catch {}

    const fetchCompanions = (role: string) =>
      fetch(`${getApiBaseUrl()}/api/v1/orders/dream-companions?role=${encodeURIComponent(role)}`)
        .then((res) => res.json())
        .then((d) => {
          if (typeof d.count === "number") {
            setCompanionCount(d.count);
            if (role) setCompanionRole(role);
            if (typeof window !== "undefined")
              localStorage.setItem(
                DATA_CACHE_KEY,
                JSON.stringify({ count: d.count, role })
              );
          }
        })
        .catch(() => {});

    // 재방문 유저: 캐시된 role로 배너를 즉시(병렬) 띄운다 — 주문 왕복을 기다리지 않음.
    const cachedRole =
      typeof window !== "undefined" ? localStorage.getItem(ROLE_CACHE_KEY) || "" : "";
    if (cachedRole) fetchCompanions(cachedRole);

    // 주문 목록은 병렬로 로드하고, 최신 role을 확보하면 캐시 갱신 + 필요 시에만 재요청.
    ordersApi
      .list()
      .then((r) => {
        const list: Order[] = r.data || [];
        setOrders(list);
        const role = list[0]?.target_role || "";
        // 아직 배너 요청을 안 했거나(캐시 없음) role이 바뀐 경우에만 (재)요청.
        if (!cachedRole || role !== cachedRole) {
          if (typeof window !== "undefined") localStorage.setItem(ROLE_CACHE_KEY, role);
          fetchCompanions(role);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const activeOrders = orders.filter((o) => o.status === "active");

  return (
    <div className="min-h-screen bg-[#F4F3EE]">
      <AppBar
        right={
          <button className="w-8 h-8 flex items-center justify-center text-[#1A1A1A]" aria-label="알림">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M18 8C18 6.4087 17.3679 4.88258 16.2426 3.75736C15.1174 2.63214 13.5913 2 12 2C10.4087 2 8.88258 2.63214 7.75736 3.75736C6.63214 4.88258 6 6.4087 6 8C6 15 3 17 3 17H21C21 17 18 15 18 8Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M13.73 21C13.5542 21.3031 13.3019 21.5547 12.9982 21.7295C12.6946 21.9044 12.3504 21.9965 12 21.9965C11.6496 21.9965 11.3054 21.9044 11.0018 21.7295C10.6982 21.5547 10.4458 21.3031 10.27 21" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        }
      />

      <div className="pt-safe-header pb-safe-nav px-4 space-y-6 max-w-lg mx-auto">

        {/* 꿈 동료 — 카드 틀과 라벨은 첫 프레임에 즉시 노출(정적), 숫자만 채워진다.
            캐시가 있으면 숫자까지 즉시. 없으면 둘째 줄만 잠깐 은은한 안내 문구 → 값 도착 시 교체.
            (레이아웃이 밀리거나 카드가 나중에 '팝인'하는 느낌 없음.) */}
        <Link href="/companions" className="block pt-4">
          <div className="app-card app-card-tap px-4 py-3.5 flex items-center justify-between">
            <div className="min-w-0">
              <p className="text-[11px] text-[#A89F8C] tracking-[0.14em]">같은 미래를 향한 사람들</p>
              <p className="text-[15px] text-[#1A1A1A] font-headline mt-1 truncate">
                {companionCount === null
                  ? <span className="text-[#A89F8C]">함께 꿈꾸는 사람들을 세는 중…</span>
                  : companionCount <= 1
                    ? <>당신은 <span className="font-bold">{companionRole || "이 꿈"}</span>의 첫 주인공</>
                    : <>나와 같은 꿈 <span className="font-bold">{companionCount.toLocaleString()}명</span>이 함께</>}
              </p>
            </div>
            <span className="text-[#A89F8C] text-lg shrink-0 ml-2">→</span>
          </div>
        </Link>


        {/* 스트릭 배너 */}
        {streak.days > 0 && (
          <div className="pt-4">
            <div className="app-card px-4 py-3 flex items-center gap-3">
              <span className="text-2xl">{streak.days >= 7 ? "🔥" : streak.days >= 3 ? "⚡" : "✨"}</span>
              <div className="flex-1">
                <p className="font-bold text-[#1A1A1A] text-sm">
                  {streak.days}일 연속으로 읽고 있어요!
                </p>
                <p className="text-xs text-[#AEAAA5]">
                  최고 기록 {streak.bestStreak}일
                  {streak.days >= 7 && " · 대단해요 🎉"}
                </p>
              </div>
              {/* 7일 진행 도트 */}
              <div className="flex gap-1">
                {Array.from({ length: 7 }).map((_, i) => (
                  <div
                    key={i}
                    className="w-2 h-2 rounded-full"
                    style={{ background: i < streak.days % 7 || (streak.days >= 7 && i < 7) ? "#1A1A1A" : "#E0DFD8" }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 연재 중인 시리즈 */}
        <section className={streak.days > 0 ? "" : "pt-4"}>
          <div className="flex items-center justify-between mb-3">
            <p className="app-section-label">연재 중인 시리즈</p>
            {/* 데스크탑에서만 표시 — 모바일은 하단 FAB 사용 */}
            <Link
              href="/order/new"
              className="hidden md:flex items-center gap-1 text-xs font-bold text-[#CC2200] border border-[#CC2200] px-3 py-1.5 rounded-full hover:bg-[#CC2200] hover:text-white transition-colors"
            >
              + 새 의뢰
            </Link>
          </div>

          {loading ? (
            <SkeletonCard />
          ) : activeOrders.length === 0 ? (
            <div className="space-y-4">
              {/* CTA 카드 */}
              <div className="app-card p-6 flex flex-col items-center text-center gap-4">
                <div className="w-16 h-16 rounded-full bg-[#1A1A1A] flex items-center justify-center text-3xl">
                  🗞️
                </div>
                <div>
                  <p className="font-headline font-bold text-[#1A1A1A] text-lg leading-snug">
                    첫 번째 꿈신문을<br/>시작해볼까요?
                  </p>
                  <p className="text-sm text-[#6B6869] mt-2 leading-relaxed">
                    꿈을 입력하면 내일 아침 8시에<br/>미래의 내 이야기가 신문으로 도착해요
                  </p>
                </div>
                <Link href="/order/new" className="app-btn-primary" style={{ maxWidth: 240 }}>
                  무료로 시작하기 →
                </Link>
              </div>
              {/* 작동 방식 */}
              <div>
                <p className="app-section-label mb-3">이렇게 진행돼요</p>
                <HowItWorks />
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {activeOrders.map((order) => {
                const progress = Math.round((order.published_newspapers / order.duration_days) * 100);
                return (
                  <div key={order.id} className="app-card p-5">
                    <div className="flex items-start justify-between mb-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="badge-active">연재 중</span>
                          <span className="text-xs text-[#AEAAA5]">{order.duration_days}일 시리즈</span>
                        </div>
                        <h3 className="font-headline font-bold text-[#1A1A1A] text-base leading-snug truncate">
                          {order.protagonist_name}의 꿈
                        </h3>
                        <p className="text-xs text-[#6B6869] mt-0.5 truncate">{order.target_role}</p>
                      </div>
                      <span className="text-[#CC2200] text-xs font-bold flex-shrink-0 ml-2">
                        D-{order.duration_days - order.published_newspapers}
                      </span>
                    </div>
                    {/* 진행률 바 */}
                    <div className="mb-3">
                      <div className="flex justify-between text-[10px] text-[#AEAAA5] mb-1.5">
                        <span>{order.published_newspapers}편 발행</span>
                        <span>{progress}%</span>
                      </div>
                      <div className="h-1.5 bg-[#F2F1EB] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full bg-[#1A1A1A] transition-all"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    </div>
                    <Link
                      href={`/newspapers/${order.id}`}
                      className="app-btn-primary"
                      style={{ minHeight: 44, fontSize: 14 }}
                    >
                      신문 보기
                    </Link>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* 연재 완료 시리즈 — 신문이 있는 유저에게만 안내 */}
        {!loading && activeOrders.length > 0 && (
          <section>
            <p className="app-section-label mb-3">이렇게 진행돼요</p>
            <div className="app-card p-4 flex items-center gap-3 text-sm text-[#6B6869]">
              <span className="text-xl">☀️</span>
              <p>매일 오전 8시, 새 편이 자동 발행됩니다</p>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────
   작가: 집무실
───────────────────────────────────────── */
function WriterHome() {
  const [assigned, setAssigned] = useState<Order[]>([]);
  const [available, setAvailable] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      writerApi.getAssignedOrders().then((r) => setAssigned(r.data)).catch(() => {}),
      writerApi.getAvailableOrders().then((r) => setAvailable(r.data)).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-[#F4F3EE]">
      <AppBar title="집무실" />

      <div className="pt-safe-header pb-safe-nav px-4 space-y-6 max-w-lg mx-auto">
        {/* 내 의뢰 */}
        <section className="pt-4">
          <p className="app-section-label mb-3">배정된 의뢰</p>
          {loading ? (
            <SkeletonCard />
          ) : assigned.length === 0 ? (
            <div className="app-card p-6 text-center text-sm text-[#AEAAA5]">
              배정된 의뢰가 없어요
            </div>
          ) : (
            <div className="space-y-3">
              {assigned.map((order) => (
                <div key={order.id} className="app-card p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="badge-active">진행 중</span>
                  </div>
                  <h3 className="font-headline font-bold text-[#1A1A1A] text-sm">{order.protagonist_name}의 꿈</h3>
                  <p className="text-xs text-[#6B6869] mt-0.5">{order.target_role}</p>
                  <p className="text-xs text-[#AEAAA5] mt-2">
                    {order.published_newspapers}/{order.duration_days}편 발행
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 수락 대기 */}
        <section>
          <p className="app-section-label mb-3">수락 대기 의뢰</p>
          {loading ? (
            <SkeletonCard />
          ) : available.length === 0 ? (
            <div className="app-card p-6 text-center text-sm text-[#AEAAA5]">
              대기 중인 의뢰가 없어요
            </div>
          ) : (
            <div className="space-y-3">
              {available.map((order) => (
                <div key={order.id} className="app-card p-4">
                  <span className="badge-draft mb-2 inline-block">대기 중</span>
                  <h3 className="font-headline font-bold text-[#1A1A1A] text-sm">{order.protagonist_name}의 꿈</h3>
                  <p className="text-xs text-[#6B6869] mt-0.5">{order.target_role} · {order.duration_days}일</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────
   스폰서: 센터
───────────────────────────────────────── */
function SponsorHome() {
  const [analytics, setAnalytics] = useState<{
    total_slots?: number;
    active_slots?: number;
    total_exposures?: number;
    newspapers_featured?: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    sponsorApi.getAnalytics().then((r) => setAnalytics(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const stats = [
    { label: "총 슬롯", value: analytics?.total_slots ?? 0 },
    { label: "활성 슬롯", value: analytics?.active_slots ?? 0 },
    { label: "총 노출", value: analytics?.total_exposures ?? 0 },
    { label: "등장 신문", value: analytics?.newspapers_featured ?? 0 },
  ];

  return (
    <div className="min-h-screen bg-[#F4F3EE]">
      <AppBar title="스폰서 센터" />

      <div className="pt-safe-header pb-safe-nav px-4 space-y-6 max-w-lg mx-auto">
        {/* 현황 숫자 */}
        <section className="pt-4">
          <p className="app-section-label mb-3">현황</p>
          <div className="grid grid-cols-2 gap-3">
            {stats.map((stat) => (
              <div key={stat.label} className="app-card p-4 text-center">
                {loading ? (
                  <div className="skeleton h-6 w-12 mx-auto mb-2" />
                ) : (
                  <p className="font-headline font-bold text-[#1A1A1A] text-2xl">{stat.value.toLocaleString()}</p>
                )}
                <p className="text-xs text-[#6B6869] mt-1">{stat.label}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 온보딩 단계 */}
        <section>
          <p className="app-section-label mb-3">시작하기</p>
          <div className="space-y-2">
            {[
              { step: 1, label: "스폰서 등록", href: "/sponsor/register", desc: "기업 정보 등록" },
              { step: 2, label: "슬롯 구매", href: "/sponsor/slots", desc: "기사 삽입 슬롯 선택" },
              { step: 3, label: "결과 확인", href: "/sponsor/dashboard", desc: "노출 현황 분석" },
            ].map((item) => (
              <Link key={item.step} href={item.href} className="app-card p-4 flex items-center gap-4 active:bg-[#F2F1EB]">
                <div className="w-8 h-8 rounded-full bg-[#1A1A1A] text-white text-xs font-bold flex items-center justify-center flex-shrink-0">
                  {item.step}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-bold text-[#1A1A1A] text-sm">{item.label}</p>
                  <p className="text-xs text-[#6B6869]">{item.desc}</p>
                </div>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M6 4L10 8L6 12" stroke="#AEAAA5" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────
   메인 라우터
───────────────────────────────────────── */
export default function HomePage() {
  const { portalType, isLoading } = usePortal();

  if (isLoading) {
    return <SplashScreen />;
  }

  if (portalType === "writer") return <WriterHome />;
  if (portalType === "sponsor") return <SponsorHome />;
  if (portalType === "user") return <UserHome />;
  if (portalType === "guest") return <TypingLanding />;
  return <TypingLanding />;
}
