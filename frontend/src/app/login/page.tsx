"use client";

/**
 * Login page — email/password sign-in via Supabase.
 *
 * In dev mode (NEXT_PUBLIC_SUPABASE_URL not set) this page shows a notice
 * that auth is disabled and auto-redirects to the dashboard.
 */

import { useState, useEffect, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { isSupabaseConfigured } from "@/lib/supabase";

export default function LoginPage() {
  const { isAuthenticated, isLoading, signIn } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Already signed in → go to dashboard
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/");
    }
    // Dev mode — no Supabase → also redirect
    if (!isLoading && !isSupabaseConfigured) {
      router.replace("/");
    }
  }, [isLoading, isAuthenticated, router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const { error: authError } = await signIn(email, password);
    if (authError) {
      setError(authError);
      setSubmitting(false);
    }
    // On success, the onAuthStateChange listener updates the session → useEffect redirects
  };

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-br from-slate-900 to-blue-950 px-4">
      {/* Logo / branding */}
      <div className="mb-8 text-center">
        <div className="mb-2 text-5xl">🗺️</div>
        <h1 className="text-2xl font-bold text-white">GatiShakti Intelligence Platform</h1>
        <p className="mt-1 text-sm text-blue-300">
          Geospatial decision support for India's infrastructure
        </p>
      </div>

      {/* Card */}
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-2xl">
        <h2 className="mb-6 text-xl font-semibold text-gray-800">Sign in</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700">
              Email address
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-gray-400">
          Account management is handled by your organisation administrator.
          <br />
          Contact admin if you need access.
        </p>
      </div>

      <p className="mt-6 text-xs text-blue-400 opacity-60">
        GSIP v0.1 · Built on open-source geospatial tools
      </p>
    </div>
  );
}
