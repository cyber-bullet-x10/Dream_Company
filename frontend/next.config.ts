import type { NextConfig } from "next";

// BUILD_MODE=standalone  → Vercel 배포용 standalone 빌드
// BUILD_MODE=            → Docker 로컬 빌드 (next start, 빠른 빌드)
//
// 정적 export 모드(BUILD_MODE=export)는 Capacitor 앱 껍데기를 위한 것이었다.
// 모바일은 Flutter 네이티브 앱으로 옮겨갔으므로 함께 걷어냈다.
const isStandalone = process.env.BUILD_MODE === "standalone";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3003";

const nextConfig: NextConfig = {
  output: isStandalone ? "standalone" : undefined,

  reactStrictMode: true,

  env: {
    NEXT_PUBLIC_API_URL: apiUrl,
  },
};

export default nextConfig;
