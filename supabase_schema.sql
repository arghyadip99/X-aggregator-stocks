-- ============================================================
-- Stock Research Aggregator — Supabase Schema
-- ============================================================
-- Run this ONCE in your Supabase project:
-- Dashboard → SQL Editor → New Query → paste + Run
-- ============================================================

-- ── digests ──────────────────────────────────────────────────
-- Stores generated HTML digests. Frontend reads this table.

CREATE TABLE IF NOT EXISTS digests (
  id              uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  category        text NOT NULL,
  label           text NOT NULL,
  digest_html     text NOT NULL,
  num_posts       integer DEFAULT 0,
  num_handles     integer DEFAULT 0,
  lookback_hours  integer DEFAULT 24,
  run_at          timestamptz DEFAULT now()
);

-- Index for fast "latest digest per category" queries
CREATE INDEX IF NOT EXISTS idx_digests_category_run_at
  ON digests (category, run_at DESC);

-- ── posts ─────────────────────────────────────────────────────
-- Stores individual categorised posts (raw feed on frontend).

CREATE TABLE IF NOT EXISTS posts (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  handle      text NOT NULL,
  content     text NOT NULL,
  category    text,
  posted_at   timestamptz,
  fetched_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_posts_category_posted_at
  ON posts (category, posted_at DESC);

CREATE INDEX IF NOT EXISTS idx_posts_handle
  ON posts (handle);

-- ── subscribers ───────────────────────────────────────────────
-- Newsletter subscribers. confirmed=false until email verified.

CREATE TABLE IF NOT EXISTS subscribers (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email       text UNIQUE NOT NULL,
  confirmed   boolean DEFAULT false,
  categories  text[] DEFAULT ARRAY['analysis','company_updates','quarterly_updates','macro'],
  created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subscribers_email
  ON subscribers (email);

-- ── Row Level Security (RLS) ──────────────────────────────────
-- Allow public SELECT on digests and posts (frontend reads without auth).
-- Restrict writes to service role only.

ALTER TABLE digests    ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts      ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscribers ENABLE ROW LEVEL SECURITY;

-- Public can read digests and posts (for the Angular frontend)
CREATE POLICY "Public read digests"
  ON digests FOR SELECT TO anon USING (true);

CREATE POLICY "Public read posts"
  ON posts FOR SELECT TO anon USING (true);

-- Service role can write everything (used by GitHub Actions)
CREATE POLICY "Service write digests"
  ON digests FOR INSERT TO service_role WITH CHECK (true);

CREATE POLICY "Service write posts"
  ON posts FOR INSERT TO service_role WITH CHECK (true);

CREATE POLICY "Service write subscribers"
  ON subscribers FOR ALL TO service_role USING (true);

-- Anon can insert subscribers (subscribe form on frontend)
CREATE POLICY "Public subscribe"
  ON subscribers FOR INSERT TO anon
  WITH CHECK (email IS NOT NULL AND email LIKE '%@%');

-- ── Helper view: latest digest per category ───────────────────

CREATE OR REPLACE VIEW latest_digests AS
SELECT DISTINCT ON (category)
  id, category, label, digest_html, num_posts, num_handles, run_at
FROM digests
ORDER BY category, run_at DESC;

GRANT SELECT ON latest_digests TO anon;
