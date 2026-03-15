-- ============================================
-- LEGAL AI AGENT — MIGRATION V1
-- Run in Supabase SQL Editor
-- ============================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Enums
DO $$ BEGIN
  CREATE TYPE plan_type AS ENUM ('trial', 'starter', 'pro', 'enterprise');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('owner', 'admin', 'member', 'viewer');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE law_type AS ENUM ('hien_phap', 'bo_luat', 'luat', 'nghi_dinh', 'thong_tu', 'quyet_dinh', 'nghi_quyet', 'cong_van', 'other');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE law_status AS ENUM ('active', 'expired', 'amended', 'repealed', 'pending');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE legal_domain AS ENUM ('lao_dong', 'doanh_nghiep', 'dan_su', 'thuong_mai', 'thue', 'dat_dai', 'dau_tu', 'bhxh', 'atvs_ld', 'so_huu_tri_tue', 'hinh_su', 'other');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE agent_type AS ENUM ('qa', 'review', 'compliance', 'draft', 'research', 'general', 'batch');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE doc_status AS ENUM ('uploaded', 'processing', 'analyzed', 'error');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE doc_type AS ENUM ('hop_dong_lao_dong', 'hop_dong_thuong_mai', 'hop_dong_dich_vu', 'noi_quy', 'quy_che', 'quyet_dinh', 'cong_van', 'bien_ban', 'bao_cao', 'phu_luc', 'other');
EXCEPTION WHEN duplicate_object THEN null; END $$;

-- ============================================
-- TABLES
-- ============================================

-- Companies
CREATE TABLE IF NOT EXISTS companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  plan plan_type DEFAULT 'trial',
  monthly_quota INT DEFAULT 50,
  used_quota INT DEFAULT 0,
  quota_reset_at TIMESTAMPTZ DEFAULT (date_trunc('month', now()) + interval '1 month'),
  settings JSONB DEFAULT '{}',
  industry TEXT,
  employee_count INT,
  tax_code TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- API Keys
CREATE TABLE IF NOT EXISTS api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  key_hash TEXT NOT NULL,
  key_prefix TEXT NOT NULL,
  permissions TEXT[] DEFAULT ARRAY['read', 'ask', 'review'],
  rate_limit INT DEFAULT 60,
  is_active BOOLEAN DEFAULT true,
  last_used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Users
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
  role user_role DEFAULT 'member',
  full_name TEXT,
  email TEXT,
  avatar_url TEXT,
  preferences JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Law Documents
CREATE TABLE IF NOT EXISTS law_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  law_number TEXT NOT NULL,
  law_type law_type NOT NULL,
  issuer TEXT NOT NULL,
  signer TEXT,
  issued_date DATE,
  effective_date DATE,
  expiry_date DATE,
  status law_status DEFAULT 'active',
  domains legal_domain[] NOT NULL,
  replaces UUID[],
  amended_by UUID[],
  full_text TEXT,
  summary TEXT,
  table_of_contents JSONB,
  source_url TEXT,
  source_site TEXT,
  article_count INT,
  word_count INT,
  crawled_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Law Chunks (for RAG with pgvector)
CREATE TABLE IF NOT EXISTS law_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  law_id UUID NOT NULL REFERENCES law_documents(id) ON DELETE CASCADE,
  chapter TEXT,
  section TEXT,
  article TEXT,
  clause TEXT,
  point TEXT,
  title TEXT,
  content TEXT NOT NULL,
  parent_context TEXT,
  embedding vector(1536),
  domains legal_domain[],
  keywords TEXT[],
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Law Relations
CREATE TABLE IF NOT EXISTS law_relations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_law_id UUID REFERENCES law_documents(id),
  source_article TEXT,
  target_law_id UUID REFERENCES law_documents(id),
  target_article TEXT,
  relation_type TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Chat Sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id),
  title TEXT,
  agent_type agent_type DEFAULT 'qa',
  status TEXT DEFAULT 'active',
  metadata JSONB DEFAULT '{}',
  message_count INT DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Messages
CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  company_id UUID NOT NULL,
  role message_role NOT NULL,
  content TEXT NOT NULL,
  citations JSONB DEFAULT '[]',
  confidence FLOAT,
  tokens_used INT,
  model TEXT,
  feedback TEXT,
  feedback_note TEXT,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Documents
CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  uploaded_by UUID REFERENCES users(id),
  name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  file_size INT,
  mime_type TEXT,
  doc_type doc_type,
  status doc_status DEFAULT 'uploaded',
  extracted_text TEXT,
  page_count INT,
  analysis JSONB,
  risk_score INT,
  issues_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  analyzed_at TIMESTAMPTZ
);

-- Company Chunks
CREATE TABLE IF NOT EXISTS company_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  embedding vector(1536),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Document Templates
CREATE TABLE IF NOT EXISTS document_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  description TEXT,
  version TEXT DEFAULT '1.0',
  legal_basis TEXT[],
  variables JSONB NOT NULL DEFAULT '[]',
  sections JSONB NOT NULL DEFAULT '[]',
  compliance_rules JSONB DEFAULT '[]',
  sample_output TEXT,
  is_active BOOLEAN DEFAULT true,
  usage_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Generated Documents (tracking)
CREATE TABLE IF NOT EXISTS generated_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  template_id TEXT REFERENCES document_templates(template_id),
  user_id UUID REFERENCES users(id),
  name TEXT NOT NULL,
  variables JSONB DEFAULT '{}',
  content TEXT,
  file_path TEXT,
  format TEXT DEFAULT 'docx',
  status TEXT DEFAULT 'generated',
  batch_id UUID,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Usage Logs
CREATE TABLE IF NOT EXISTS usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES companies(id),
  user_id UUID REFERENCES users(id),
  api_key_id UUID REFERENCES api_keys(id),
  endpoint TEXT NOT NULL,
  agent_type agent_type,
  input_tokens INT DEFAULT 0,
  output_tokens INT DEFAULT 0,
  embedding_tokens INT DEFAULT 0,
  total_cost_usd NUMERIC(10,6) DEFAULT 0,
  latency_ms INT,
  status_code INT,
  request_metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- INDEXES
-- ============================================

CREATE INDEX IF NOT EXISTS idx_law_chunks_embedding ON law_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_law_chunks_law ON law_chunks(law_id);
CREATE INDEX IF NOT EXISTS idx_law_chunks_article ON law_chunks(article);
CREATE INDEX IF NOT EXISTS idx_law_chunks_domains ON law_chunks USING gin(domains);
CREATE INDEX IF NOT EXISTS idx_law_docs_number ON law_documents(law_number);
CREATE INDEX IF NOT EXISTS idx_law_docs_status ON law_documents(status);
CREATE INDEX IF NOT EXISTS idx_law_docs_domains ON law_documents USING gin(domains);
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_company ON api_keys(company_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_sessions_company ON chat_sessions(company_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_company ON messages(company_id);
CREATE INDEX IF NOT EXISTS idx_documents_company ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_company_chunks_company ON company_chunks(company_id);
CREATE INDEX IF NOT EXISTS idx_company_chunks_embedding ON company_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_usage_company_date ON usage_logs(company_id, created_at);
CREATE INDEX IF NOT EXISTS idx_generated_docs_company ON generated_documents(company_id);
CREATE INDEX IF NOT EXISTS idx_generated_docs_batch ON generated_documents(batch_id);

-- ============================================
-- RLS
-- ============================================

ALTER TABLE law_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE law_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE law_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_templates ENABLE ROW LEVEL SECURITY;

CREATE POLICY "law_public_read" ON law_documents FOR SELECT USING (true);
CREATE POLICY "law_chunks_public_read" ON law_chunks FOR SELECT USING (true);
CREATE POLICY "law_relations_public_read" ON law_relations FOR SELECT USING (true);
CREATE POLICY "templates_public_read" ON document_templates FOR SELECT USING (true);

-- ============================================
-- FUNCTIONS
-- ============================================

-- Hybrid search function
CREATE OR REPLACE FUNCTION search_law_chunks(
  query_embedding vector(1536),
  filter_domains legal_domain[] DEFAULT NULL,
  match_count INT DEFAULT 10
)
RETURNS TABLE (
  id UUID,
  law_id UUID,
  article TEXT,
  clause TEXT,
  content TEXT,
  title TEXT,
  parent_context TEXT,
  domains legal_domain[],
  similarity FLOAT
) AS $$
BEGIN
  RETURN QUERY
  SELECT 
    lc.id,
    lc.law_id,
    lc.article,
    lc.clause,
    lc.content,
    lc.title,
    lc.parent_context,
    lc.domains,
    1 - (lc.embedding <=> query_embedding) AS similarity
  FROM law_chunks lc
  WHERE (filter_domains IS NULL OR lc.domains && filter_domains)
    AND lc.embedding IS NOT NULL
  ORDER BY lc.embedding <=> query_embedding
  LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Verify
SELECT 'Migration V1 completed successfully!' AS status;
