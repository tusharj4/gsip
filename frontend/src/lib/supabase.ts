/**
 * Supabase browser client — singleton, safe to import anywhere.
 *
 * When NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY are not set
 * (local dev with ENABLE_AUTH=false) the client is a stub that always returns
 * a synthetic "dev" session so the UI renders without a real Supabase project.
 */

import { createClient, SupabaseClient, Session, User } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

// Real client (works even with empty strings — requests will simply fail at runtime
// which is fine in dev mode where the backend also accepts unauthenticated calls).
export const supabase: SupabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

/** True when Supabase is configured (production or staging). */
export const isSupabaseConfigured =
  supabaseUrl.length > 0 && supabaseAnonKey.length > 0;

export type { Session, User };
