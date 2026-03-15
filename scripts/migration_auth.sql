-- ============================================
-- LEGAL AI AGENT — AUTH & MANAGEMENT MIGRATION
-- Run in Supabase SQL Editor
-- ============================================

-- Add auth integration to users table
DO $$ BEGIN
  ALTER TABLE users ADD COLUMN auth_id UUID UNIQUE REFERENCES auth.users(id);
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE users ADD COLUMN password_hash TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE users ADD COLUMN user_settings JSONB DEFAULT '{}';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE users ADD COLUMN last_login_at TIMESTAMPTZ;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT true;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Make email unique
DO $$ BEGIN
  ALTER TABLE users ADD CONSTRAINT users_email_unique UNIQUE (email);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Create company invites table
CREATE TABLE IF NOT EXISTS company_invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  inviter_id UUID REFERENCES users(id),
  email TEXT NOT NULL,
  role user_role DEFAULT 'member',
  token TEXT UNIQUE NOT NULL,
  expires_at TIMESTAMPTZ DEFAULT (now() + interval '7 days'),
  accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Add billing info to companies
DO $$ BEGIN
  ALTER TABLE companies ADD COLUMN billing_email TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE companies ADD COLUMN billing_address TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE companies ADD COLUMN payment_method TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE companies ADD COLUMN subscription_id TEXT;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE companies ADD COLUMN subscription_status TEXT DEFAULT 'active';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE companies ADD COLUMN trial_ends_at TIMESTAMPTZ;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_auth ON users(auth_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_invites_company ON company_invites(company_id);
CREATE INDEX IF NOT EXISTS idx_invites_token ON company_invites(token);
CREATE INDEX IF NOT EXISTS idx_invites_email ON company_invites(email);

-- ============================================
-- RLS POLICIES (Multi-tenant isolation)
-- ============================================

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE generated_documents ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if any
DROP POLICY IF EXISTS "companies_own_data" ON companies;
DROP POLICY IF EXISTS "users_own_company" ON users;
DROP POLICY IF EXISTS "api_keys_own_company" ON api_keys;
DROP POLICY IF EXISTS "sessions_own_company" ON chat_sessions;
DROP POLICY IF EXISTS "messages_own_company" ON messages;
DROP POLICY IF EXISTS "documents_own_company" ON documents;
DROP POLICY IF EXISTS "chunks_own_company" ON company_chunks;
DROP POLICY IF EXISTS "usage_own_company" ON usage_logs;
DROP POLICY IF EXISTS "invites_own_company" ON company_invites;
DROP POLICY IF EXISTS "generated_docs_own_company" ON generated_documents;

-- Companies: Users can only see their own company
CREATE POLICY "companies_own_data" ON companies
  FOR ALL USING (
    id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Users: Can see users in their company
CREATE POLICY "users_own_company" ON users
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- API Keys: Only company members can manage
CREATE POLICY "api_keys_own_company" ON api_keys
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Chat Sessions: Company-scoped
CREATE POLICY "sessions_own_company" ON chat_sessions
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Messages: Company-scoped
CREATE POLICY "messages_own_company" ON messages
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Documents: Company-scoped
CREATE POLICY "documents_own_company" ON documents
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Company chunks: Company-scoped
CREATE POLICY "chunks_own_company" ON company_chunks
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Usage logs: Company-scoped
CREATE POLICY "usage_own_company" ON usage_logs
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Invites: Company-scoped
CREATE POLICY "invites_own_company" ON company_invites
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- Generated documents: Company-scoped
CREATE POLICY "generated_docs_own_company" ON generated_documents
  FOR ALL USING (
    company_id IN (
      SELECT company_id FROM users WHERE auth_id = auth.uid()
    )
  );

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Get user's company ID
CREATE OR REPLACE FUNCTION get_user_company_id(user_auth_id UUID)
RETURNS UUID AS $$
  SELECT company_id FROM users WHERE auth_id = user_auth_id LIMIT 1;
$$ LANGUAGE SQL SECURITY DEFINER;

-- Check if user has permission
CREATE OR REPLACE FUNCTION user_has_role(user_auth_id UUID, required_role user_role)
RETURNS BOOLEAN AS $$
  SELECT EXISTS(
    SELECT 1 FROM users 
    WHERE auth_id = user_auth_id 
      AND (
        role = required_role 
        OR role = 'owner' 
        OR role = 'admin'
      )
  );
$$ LANGUAGE SQL SECURITY DEFINER;

-- Reset monthly quota (run via cron)
CREATE OR REPLACE FUNCTION reset_monthly_quotas()
RETURNS void AS $$
BEGIN
  UPDATE companies
  SET 
    used_quota = 0,
    quota_reset_at = date_trunc('month', now()) + interval '1 month'
  WHERE quota_reset_at <= now();
END;
$$ LANGUAGE plpgsql;

SELECT 'Auth migration completed successfully!' AS status;
