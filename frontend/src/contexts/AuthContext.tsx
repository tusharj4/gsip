"use client";

/**
 * AuthContext — global auth state for the GSIP frontend.
 *
 * Wraps Supabase's onAuthStateChange listener and makes the session, user,
 * and helper functions (signIn, signOut) available to every component.
 *
 * Dev mode (no Supabase configured):
 *   isLoading=false, user=null, session=null.
 *   The backend accepts requests without a Bearer token (ENABLE_AUTH=false),
 *   so every feature works without logging in.
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import { supabase, isSupabaseConfigured, Session, User } from "@/lib/supabase";

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  role: string;
  isLoading: boolean;
  isAuthenticated: boolean;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
  /** Bearer token for API requests — empty string when not authenticated. */
  accessToken: string;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(isSupabaseConfigured);

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setIsLoading(false);
      return;
    }

    // Hydrate from persisted session on mount
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setIsLoading(false);
    });

    // Listen for sign-in / sign-out / token-refresh events
    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  const signIn = useCallback(
    async (email: string, password: string): Promise<{ error: string | null }> => {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      return { error: error?.message ?? null };
    },
    [],
  );

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setSession(null);
  }, []);

  const user = session?.user ?? null;
  const role: string =
    (user?.app_metadata?.role as string | undefined) ?? (isSupabaseConfigured ? "viewer" : "admin");
  const accessToken = session?.access_token ?? "";

  return (
    <AuthContext.Provider
      value={{
        session,
        user,
        role,
        isLoading,
        isAuthenticated: !!user,
        signIn,
        signOut,
        accessToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
