/**
 * Supabase client for direct database access from the frontend.
 * Used for read-only queries (stocks, earnings, predictions).
 * Write operations go through the FastAPI backend (which uses service role key).
 */

import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
