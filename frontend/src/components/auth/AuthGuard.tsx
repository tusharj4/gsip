"use client";

/**
 * AuthGuard — wraps any page/component that requires authentication.
 *
 * Behaviour:
 *  - While auth state is loading → shows a spinner (avoids flash of login page).
 *  - Not authenticated + Supabase configured → redirects to /login.
 *  - Not authenticated + no Supabase (dev mode) → renders children (backend is open).
 *  - Authenticated but insufficient role → shows a "403 Forbidden" message.
 *  - All good → renders children.
 *
 * Usage:
 *   <AuthGuard minimumRole="ministry_maker">
 *     <SensitivePage />
 *   </AuthGuard>
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { isSupabaseConfigured } from "@/lib/supabase";

const ROLE_HIERARCHY: Record<string, number> = {
  viewer: 0,
  ministry_maker: 1,
  ministry_checker: 2,
  admin: 3,
};

interface Props {
  children: React.ReactNode;
  minimumRole?: "viewer" | "ministry_maker" | "ministry_checker" | "admin";
}

export default function AuthGuard({ children, minimumRole = "viewer" }: Props) {
  const { isLoading, isAuthenticated, role } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated && isSupabaseConfigured) {
      router.push("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          <p className="text-sm text-gray-500">Loading…</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated && isSupabaseConfigured) {
    // Redirect in progress — render nothing to avoid flash
    return null;
  }

  // Role check
  const userLevel = ROLE_HIERARCHY[role] ?? 0;
  const requiredLevel = ROLE_HIERARCHY[minimumRole] ?? 0;
  if (userLevel < requiredLevel) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="max-w-md rounded-lg border border-red-200 bg-white p-8 text-center shadow">
          <div className="mb-4 text-4xl">🚫</div>
          <h2 className="mb-2 text-xl font-semibold text-gray-800">Access Denied</h2>
          <p className="text-gray-500">
            This page requires <strong>{minimumRole}</strong> access or higher.
            Your current role is <strong>{role}</strong>.
          </p>
          <p className="mt-4 text-sm text-gray-400">
            Contact your administrator to request elevated access.
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
