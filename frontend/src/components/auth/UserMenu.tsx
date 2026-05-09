"use client";

/**
 * UserMenu — top-right corner user badge + sign-out button.
 * Shows nothing meaningful in dev mode (no Supabase).
 */

import { useAuth } from "@/contexts/AuthContext";
import { isSupabaseConfigured } from "@/lib/supabase";

const ROLE_BADGES: Record<string, { label: string; color: string }> = {
  admin: { label: "Admin", color: "bg-purple-100 text-purple-700" },
  ministry_checker: { label: "Checker", color: "bg-blue-100 text-blue-700" },
  ministry_maker: { label: "Maker", color: "bg-green-100 text-green-700" },
  viewer: { label: "Viewer", color: "bg-gray-100 text-gray-600" },
};

export default function UserMenu() {
  const { user, role, isAuthenticated, signOut } = useAuth();
  const badge = ROLE_BADGES[role] ?? ROLE_BADGES.viewer;

  if (!isSupabaseConfigured) {
    return (
      <span className="rounded-full bg-yellow-100 px-2.5 py-0.5 text-xs font-medium text-yellow-700">
        Dev mode
      </span>
    );
  }

  if (!isAuthenticated) return null;

  const displayName = user?.email?.split("@")[0] ?? "User";

  return (
    <div className="flex items-center gap-2">
      <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.color}`}>
        {badge.label}
      </span>
      <span className="text-sm text-gray-600">{displayName}</span>
      <button
        onClick={() => void signOut()}
        className="rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-100 hover:text-gray-700"
      >
        Sign out
      </button>
    </div>
  );
}
