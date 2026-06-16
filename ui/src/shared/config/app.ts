export const AppCfg = {
  env: import.meta.env.VITE_ENV ?? "development",
  isProd: import.meta.env.VITE_ENV === "production",
  apiUrl: import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8080",
} as const;
