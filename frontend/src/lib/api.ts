import axios from "axios";
import { supabase } from "./supabase";

const getBaseUrl = () => {
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    // 프로덕션/배포 도메인은 빌드 시 env 사용
    const isProd =
      hostname.includes("dreamnewspaper.com") ||
      hostname.includes("vercel.app") ||
      hostname.includes("railway.app");
    if (!isProd && hostname !== "localhost") {
      // 로컬 WiFi IP로 모바일 접속 시 → 같은 호스트의 3003 포트 자동 사용
      // (IP가 바뀌어도 재빌드 불필요)
      return `http://${hostname}:3003`;
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:3003";
};

// login/page.tsx 등에서 직접 fetch할 때 동일한 URL 로직 재사용
export const getApiBaseUrl = getBaseUrl;

const API_URL = getBaseUrl();

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
  // Render 무료 티어는 15분 유휴 후 슬립 → 첫 요청 콜드스타트에 30~60초 소요.
  // 타임아웃이 짧으면 그 첫 요청이 끊겨 "에러"로 보임. 콜드스타트를 견디도록 60초로.
  timeout: 60000,
});

// 요청 인터셉터: Supabase 세션 토큰 자동 삽입
api.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`;
  }
  return config;
});

// 응답 인터셉터: 401 및 타임아웃 처리
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return Promise.reject(new Error('서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.'));
    }
    if (!error.response) {
      return Promise.reject(new Error('서버에 연결할 수 없습니다. 네트워크를 확인해주세요.'));
    }
    if (error.response?.status === 401) {
      await supabase.auth.signOut();
      document.cookie = "dream_role=; path=/; max-age=0";
      localStorage.removeItem("dream_portal_role");
      // 보호 경로에서만 /login으로 이동 — 공개 페이지(/)에서는 PortalProvider가 처리
      const AUTH_REQUIRED = ["/dashboard", "/order", "/writer", "/sponsor"];
      const isProtected = AUTH_REQUIRED.some((p) => window.location.pathname.startsWith(p));
      if (typeof window !== "undefined" && isProtected) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// ============================
// API 함수들
// ============================

// 인증
export const authApi = {
  register: (data: { email: string; password: string; full_name: string; role?: string }) =>
    api.post("/auth/register", data),
  login: (data: { email: string; password: string }) =>
    api.post("/auth/login", data),
  me: () => api.get("/auth/me"),
  updateMe: (data: { full_name?: string; role?: string }) => api.patch("/auth/me", data),
  /** 활성 role 전환 — 보유한 역할 중 하나로만 가능 */
  setActiveRole: (role: string) => api.patch("/auth/active-role", { role }),
};

// 의뢰
export const ordersApi = {
  create: (data: OrderCreate) => api.post("/orders", data),
  list: () => api.get("/orders"),
  get: (id: string) => api.get(`/orders/${id}`),
  start: (id: string) => api.post(`/orders/${id}/start`),
  getNewspapers: (orderId: string) => api.get(`/newspapers/orders/${orderId}`),
};

// 결제
export const paymentApi = {
  /** Stripe Checkout 세션 생성 → {checkout_url} 반환 */
  createCheckoutSession: (order_id: string) =>
    api.post<{ checkout_url: string; session_id: string }>(
      "/payment/checkout-session",
      null,
      { params: { order_id } }
    ),
  /** session_id로 주문 상태 조회 (결제 성공 페이지) */
  getSession: (session_id: string) =>
    api.get<{ order_id: string; payment_status: string; status: string; duration_days: number }>(
      `/payment/session/${session_id}`
    ),
  /** 스폰서 슬롯 Stripe Checkout 세션 생성 */
  createSponsorCheckout: (params: {
    native_qty: number;
    native_text: string;
    sidebar_qty: number;
    sidebar_text: string;
  }) =>
    api.post<{ checkout_url: string; session_id: string }>(
      "/payment/sponsor/checkout",
      null,
      { params }
    ),
};

// 크레딧
export const creditsApi = {
  /** 크레딧 팩 목록 조회 */
  listPackages: () =>
    api.get<CreditPackage[]>("/payment/credits/packages"),
  /** 크레딧 팩 구매 Stripe Checkout 세션 생성 */
  createCheckout: (package_id: string) =>
    api.post<{ checkout_url: string; session_id: string }>(
      "/payment/credits/checkout",
      null,
      { params: { package_id } }
    ),
  /** 크레딧 잔액 + 거래 내역 조회 */
  getBalance: () =>
    api.get<{ credits: number; transactions: CreditTransaction[] }>("/payment/credits/balance"),
};

export interface CreditPackage {
  id: string;
  credits: number;
  price_krw: number;
  label: string;
  per_credit: number;
}

export interface CreditTransaction {
  id: string;
  type: "purchase" | "consume" | "bonus" | "refund";
  amount: number;
  credits_before: number;
  credits_after: number;
  description: string;
  created_at: string;
}

// 작가
export const writerApi = {
  /** 작가 지원 — 프로필 생성 + 서버가 role을 writer로 승격 */
  apply: (data: { pen_name: string; specialties: string[]; bio?: string; portfolio_url?: string }) =>
    api.post("/writer/apply", data),
  getProfile: () => api.get("/writer/me"),
  getAssignedOrders: () => api.get("/writer/orders"),
  getAvailableOrders: () => api.get("/writer/available-orders"),
  claimOrder: (orderId: string) => api.post(`/writer/orders/${orderId}/claim`),
  updateNewspaperDraft: (id: string, content: any) =>
    api.put(`/writer/newspapers/${id}`, content),
};

// 템플릿 마켓플레이스
export const templateApi = {
  // 마켓 (독자)
  listMarket: (genre?: string) =>
    api.get("/templates/market", { params: genre ? { genre } : {} }),
  getMarket: (id: string) => api.get(`/templates/market/${id}`),
  purchase: (id: string, slotValues: Record<string, string>) =>
    api.post(`/templates/market/${id}/purchase`, { slot_values: slotValues }),
  myPurchases: () => api.get("/templates/my-purchases"),
  // 작가
  create: (data: any) => api.post("/templates", data),
  myTemplates: () => api.get("/templates/my"),
  getDetail: (id: string) => api.get(`/templates/${id}/detail`),
  updateEpisode: (templateId: string, episodeId: string, data: any) =>
    api.put(`/templates/${templateId}/episodes/${episodeId}`, data),
  publish: (id: string) => api.put(`/templates/${id}/publish`),
};

// 신문
export const newspapersApi = {
  list: () => api.get("/newspapers"),
  get: (id: string) => api.get(`/newspapers/${id}`),
  publicFeed: (limit = 12) => api.get(`/newspapers/public?limit=${limit}`),
};

// 스폰서
export const sponsorApi = {
  getProfile: () => api.get("/sponsor/me"),
  getSlots: () => api.get("/sponsor/slots"),
  getMatches: () => api.get("/sponsor/matches"),
  getAnalytics: () => api.get("/sponsor/analytics"),
  register: (data: SponsorCreate) => api.post("/sponsor/register", data),
  purchaseSlot: (data: SlotCreate) => api.post("/sponsor/slots", data),
};

// 제휴 문의 (인증 불필요)
export const partnershipApi = {
  inquire: (data: PartnershipInquiry) => api.post("/partnership/inquiry", data),
};

// 미래 헤드라인 생성기 (공개 — 홍보 후크)
export const headlineApi = {
  generate: (name: string, dream: string) =>
    api.post("/headline/generate", { name, dream }),
};

// 관리자 (admin role 전용)
export const adminApi = {
  overview: () => api.get("/admin/overview"),
  inquiries: (status?: string) => api.get("/admin/inquiries", { params: status ? { status } : {} }),
  updateInquiryStatus: (id: string, status: string) => api.patch(`/admin/inquiries/${id}`, { status }),
  scheduleHealth: () => api.get("/admin/schedule-health"),
  searchUsers: (q: string) => api.get("/admin/users", { params: { q } }),
  searchOrders: (q: string) => api.get("/admin/orders", { params: { q } }),
  finance: () => api.get("/admin/finance"),
  infraCosts: () => api.get("/admin/infra-costs"),
  updateInfraCost: (service: string, monthly_cost_krw: number, note?: string) =>
    api.patch(`/admin/infra-costs/${service}`, { monthly_cost_krw, note }),
};

export interface PartnershipInquiry {
  company_name: string;
  contact_name: string;
  email: string;
  phone?: string;
  message?: string;
}

export interface SponsorCreate {
  company_name: string;
  industry?: string;
  description?: string;
  website_url?: string;
  contact_email?: string;
  target_roles: string[];
  target_companies: string[];
  target_keywords: string[];
}

export interface SlotCreate {
  slot_type: "company_name" | "brand_name" | "banner" | "sidebar";
  variable_value: string;
  purchased_quantity: number;
}

export interface SponsorAnalytics {
  company_name: string;
  total_slots: number;
  active_slots: number;
  total_exposures: number;
  newspapers_featured: number;
  remaining_impressions: number;
}

// ============================
// 타입
// ============================
export interface OrderCreate {
  dream_description: string;
  protagonist_name: string;
  target_role: string;
  target_company?: string;
  duration_days: 3 | 7 | 14 | 30;
  future_year?: number;
  payment_type: "subscription" | "one_time" | "free" | "credits";
}

export interface Order {
  id: string;
  protagonist_name: string;
  dream_description: string;
  target_role: string;
  target_company?: string;
  duration_days: number;
  future_year: number;
  payment_type: string;
  payment_status: string;
  merchant_uid?: string;
  imp_uid?: string;
  status: string;
  created_at: string;
  starts_at?: string;
  total_newspapers: number;
  published_newspapers: number;
}

export interface Newspaper {
  id: string;
  order_id: string;
  episode_number: number;
  future_date: string;
  future_date_label?: string;
  headline?: string;
  subhead?: string;
  lead_paragraph?: string;
  body_content?: string;
  sidebar_content: {
    quote?: string;
    stats?: Array<{ label: string; value: string }>;
    episode_summary?: string;
  };
  variables_used: Record<string, string>;
  status: string;
  published_at?: string;
  view_count: number;
  visual_prompt?: string;
  sns_copy?: any;
  ai_model?: string;
}
