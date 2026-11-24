-- ============================================================================
-- ApplyKit Database Schema & Row Level Security (Supabase Postgres)
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ----------------------------------------------------------------------------
-- 1. PROFILES TABLE (1-to-1 with auth.users)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    avatar_url TEXT,
    is_pro BOOLEAN NOT NULL DEFAULT FALSE,
    pro_plan TEXT DEFAULT 'free' CHECK (pro_plan IN ('free', 'monthly', 'lifetime')),
    pro_expires_at TIMESTAMPTZ,
    ai_uses_this_month INTEGER NOT NULL DEFAULT 0,
    ai_usage_reset_at TIMESTAMPTZ NOT NULL DEFAULT (date_trunc('month', NOW()) + INTERVAL '1 month'),
    bonus_generations INTEGER NOT NULL DEFAULT 0,
    referral_code TEXT UNIQUE DEFAULT encode(extensions.gen_random_bytes(4), 'hex'),
    referred_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    weekly_goal INTEGER NOT NULL DEFAULT 10,
    cv_storage_path TEXT,
    cv_text_hash TEXT,
    gdpr_consent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Auto-create profile row when user signs up via Google OAuth or Email
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, email, full_name, avatar_url)
    VALUES (
        NEW.id,
        COALESCE(NEW.email, ''),
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', ''),
        COALESCE(NEW.raw_user_meta_data->>'avatar_url', '')
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ----------------------------------------------------------------------------
-- 2. APPLICATIONS TABLE (Kanban & Extension Auto-Sync)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    job_title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT 'Unknown Client',
    platform TEXT NOT NULL DEFAULT 'Manual',
    job_url TEXT,
    salary TEXT,
    status TEXT NOT NULL DEFAULT 'Applied' CHECK (status IN ('Saved', 'Applied', 'Interview', 'Offer', 'Rejected')),
    match_score INTEGER CHECK (match_score >= 0 AND match_score <= 100),
    scam_risk TEXT CHECK (scam_risk IN ('Low', 'Medium', 'High')),
    private_notes TEXT DEFAULT '',
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    interview_at TIMESTAMPTZ,
    followup_due_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
    followup_done BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_applications_user_id ON public.applications(user_id);
CREATE INDEX IF NOT EXISTS idx_applications_status ON public.applications(user_id, status);

-- ----------------------------------------------------------------------------
-- 3. AI AUDIT & USAGE LOGS (Stores hashes only — never raw CVs)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ai_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    ip_hash TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    cached BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_user_month ON public.ai_usage_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_ip_hash ON public.ai_usage_logs(ip_hash, created_at);

-- ----------------------------------------------------------------------------
-- 4. SEARCH DISCOVERY LOGS (No PII or full CV stored)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.search_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    query_sanitized TEXT NOT NULL,
    platform_context TEXT,
    matched_tool_ids TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- 5. M-PESA TRANSACTIONS (Safaricom Daraja STK Push + Manual Till Fallback)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.mpesa_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    email TEXT,
    phone TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 750,
    plan TEXT NOT NULL DEFAULT 'monthly' CHECK (plan IN ('monthly', 'lifetime')),
    payment_method TEXT NOT NULL DEFAULT 'stk_push' CHECK (payment_method IN ('stk_push', 'manual_till')),
    merchant_request_id TEXT,
    checkout_request_id TEXT UNIQUE,
    mpesa_receipt_number TEXT UNIQUE,
    manual_till_code TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed', 'manual_review')),
    result_code INTEGER,
    result_desc TEXT,
    raw_callback JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mpesa_checkout_id ON public.mpesa_transactions(checkout_request_id);
CREATE INDEX IF NOT EXISTS idx_mpesa_user_id ON public.mpesa_transactions(user_id);

-- ----------------------------------------------------------------------------
-- 6. LEMON SQUEEZY / GLOBAL PAYMENT WEBHOOK AUDIT
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.payment_webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL DEFAULT 'lemonsqueezy',
    event_name TEXT NOT NULL,
    order_id TEXT,
    customer_email TEXT,
    user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    amount_cents INTEGER,
    currency TEXT DEFAULT 'USD',
    plan TEXT DEFAULT 'monthly',
    raw_payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- 7. REFERRAL REWARDS (+5 Free Generations per Invite)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.referrals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    referrer_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    referred_user_id UUID NOT NULL UNIQUE REFERENCES public.profiles(id) ON DELETE CASCADE,
    bonus_awarded INTEGER NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- 8. ROW LEVEL SECURITY (RLS) POLICIES
-- ----------------------------------------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.search_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mpesa_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_webhooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referrals ENABLE ROW LEVEL SECURITY;

-- Profiles: Users can read/update/delete ONLY their own profile
CREATE POLICY "profiles_select_own" ON public.profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "profiles_update_own" ON public.profiles
    FOR UPDATE USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

CREATE POLICY "profiles_delete_own" ON public.profiles
    FOR DELETE USING (auth.uid() = id);

-- Applications: Users can CRUD ONLY their own job applications
CREATE POLICY "applications_select_own" ON public.applications
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "applications_insert_own" ON public.applications
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "applications_update_own" ON public.applications
    FOR UPDATE USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "applications_delete_own" ON public.applications
    FOR DELETE USING (auth.uid() = user_id);

-- AI Usage Logs: Users can read/delete ONLY their own logs
CREATE POLICY "ai_logs_select_own" ON public.ai_usage_logs
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "ai_logs_delete_own" ON public.ai_usage_logs
    FOR DELETE USING (auth.uid() = user_id);

-- M-Pesa Transactions: Users can read their own transactions
CREATE POLICY "mpesa_select_own" ON public.mpesa_transactions
    FOR SELECT USING (auth.uid() = user_id);

-- Referrals: Users can view their own referrals
CREATE POLICY "referrals_select_own" ON public.referrals
    FOR SELECT USING (auth.uid() = referrer_id OR auth.uid() = referred_user_id);

-- ----------------------------------------------------------------------------
-- 9. SUPABASE STORAGE BUCKET FOR CVs (Max 2MB, PDF/DOCX only, private per user)
-- ----------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'cvs',
    'cvs',
    FALSE,
    2097152,
    ARRAY[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]
)
ON CONFLICT (id) DO UPDATE SET
    public = FALSE,
    file_size_limit = 2097152,
    allowed_mime_types = ARRAY[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ];

-- Storage RLS: Users can only access files under their own folder `{auth.uid()}/*`
CREATE POLICY "cvs_select_own" ON storage.objects
    FOR SELECT USING (bucket_id = 'cvs' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "cvs_insert_own" ON storage.objects
    FOR INSERT WITH CHECK (bucket_id = 'cvs' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "cvs_update_own" ON storage.objects
    FOR UPDATE USING (bucket_id = 'cvs' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "cvs_delete_own" ON storage.objects
    FOR DELETE USING (bucket_id = 'cvs' AND auth.uid()::text = (storage.foldername(name))[1]);
