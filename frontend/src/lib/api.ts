/**
 * Typed axios API client for the GSIP backend.
 * Base URL is read from NEXT_PUBLIC_API_URL (dev) or relative (prod via Next.js rewrite).
 */

import axios from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "",
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

// Log errors in development
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (process.env.NODE_ENV === "development") {
      console.error("[API Error]", err.response?.status, err.response?.data);
    }
    return Promise.reject(err);
  }
);
