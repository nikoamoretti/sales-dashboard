
-- ============================================
-- SALES OUTBOUND SYSTEM — SUPABASE SCHEMA
-- ============================================

-- Companies: central entity linking all channels
CREATE TABLE IF NOT EXISTS companies (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    hubspot_id TEXT UNIQUE,
    industry TEXT,
    status TEXT DEFAULT 'prospect'
        CHECK (status IN ('prospect', 'contacted', 'interested', 'meeting_booked', 'opportunity', 'closed', 'disqualified')),
    channels_touched TEXT[] DEFAULT '{}',
    total_touches INT DEFAULT 0,
    last_touch_at TIMESTAMPTZ,
    first_touch_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_hubspot_id ON companies(hubspot_id);

-- Contacts: people at companies
CREATE TABLE IF NOT EXISTS contacts (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    company_id BIGINT REFERENCES companies(id),
    hubspot_id TEXT,
    title TEXT,
    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);

-- Calls: from HubSpot
CREATE TABLE IF NOT EXISTS calls (
    id BIGSERIAL PRIMARY KEY,
    hubspot_call_id TEXT UNIQUE,
    company_id BIGINT REFERENCES companies(id),
    contact_name TEXT,
    category TEXT,
    duration_s INT DEFAULT 0,
    notes TEXT,
    summary TEXT,
    recording_url TEXT,
    has_transcript BOOLEAN DEFAULT FALSE,
    called_at TIMESTAMPTZ,
    week_num INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calls_company ON calls(company_id);
CREATE INDEX IF NOT EXISTS idx_calls_category ON calls(category);
CREATE INDEX IF NOT EXISTS idx_calls_called_at ON calls(called_at);
CREATE INDEX IF NOT EXISTS idx_calls_week_num ON calls(week_num);

-- Call intelligence: AI-extracted from call summaries
CREATE TABLE IF NOT EXISTS call_intel (
    id BIGSERIAL PRIMARY KEY,
    call_id BIGINT REFERENCES calls(id),
    company_id BIGINT REFERENCES companies(id),
    interest_level TEXT CHECK (interest_level IN ('high', 'medium', 'low', 'none')),
    qualified BOOLEAN,
    next_action TEXT,
    objection TEXT,
    competitor TEXT,
    commodities TEXT,
    referral_name TEXT,
    referral_role TEXT,
    key_quote TEXT,
    extracted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_intel_company ON call_intel(company_id);
CREATE INDEX IF NOT EXISTS idx_call_intel_interest ON call_intel(interest_level);

-- Email sequences: from Apollo
CREATE TABLE IF NOT EXISTS email_sequences (
    id BIGSERIAL PRIMARY KEY,
    sequence_name TEXT NOT NULL,
    apollo_id TEXT,
    status TEXT DEFAULT 'active',
    sent INT DEFAULT 0,
    delivered INT DEFAULT 0,
    opened INT DEFAULT 0,
    replied INT DEFAULT 0,
    clicked INT DEFAULT 0,
    open_rate REAL DEFAULT 0,
    reply_rate REAL DEFAULT 0,
    click_rate REAL DEFAULT 0,
    snapshot_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- InMails: from Google Sheets
CREATE TABLE IF NOT EXISTS inmails (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT REFERENCES companies(id),
    contact_name TEXT,
    contact_title TEXT,
    company_name TEXT,
    sent_date DATE,
    replied BOOLEAN DEFAULT FALSE,
    reply_sentiment TEXT CHECK (reply_sentiment IN ('interested', 'not_interested', 'neutral', 'ooo', NULL)),
    reply_text TEXT,
    week_num INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inmails_company ON inmails(company_id);
CREATE INDEX IF NOT EXISTS idx_inmails_sentiment ON inmails(reply_sentiment);

-- Weekly snapshots: aggregated metrics per channel per week
CREATE TABLE IF NOT EXISTS weekly_snapshots (
    id BIGSERIAL PRIMARY KEY,
    week_num INT NOT NULL,
    monday DATE NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('calls', 'email', 'linkedin')),
    -- Call metrics
    dials INT,
    human_contacts INT,
    human_contact_rate REAL,
    meetings_booked INT,
    categories JSONB,
    -- Email metrics
    emails_sent INT,
    emails_opened INT,
    email_open_rate REAL,
    emails_replied INT,
    email_reply_rate REAL,
    -- LinkedIn metrics
    inmails_sent INT,
    inmails_replied INT,
    inmail_reply_rate REAL,
    interested_count INT,
    --
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(week_num, channel)
);

CREATE INDEX IF NOT EXISTS idx_weekly_channel ON weekly_snapshots(channel);

-- Insights: AI-generated daily advisor
CREATE TABLE IF NOT EXISTS insights (
    id BIGSERIAL PRIMARY KEY,
    insight_date DATE DEFAULT CURRENT_DATE,
    type TEXT NOT NULL
        CHECK (type IN ('action_required', 'alert', 'win', 'experiment', 'coaching', 'strategic')),
    severity TEXT DEFAULT 'medium'
        CHECK (severity IN ('high', 'medium', 'low')),
    title TEXT NOT NULL,
    body TEXT,
    related_company_id BIGINT REFERENCES companies(id),
    related_call_id BIGINT REFERENCES calls(id),
    channel TEXT,
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insights_date ON insights(insight_date);
CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(type);
CREATE INDEX IF NOT EXISTS idx_insights_severity ON insights(severity);

-- Experiments: track what we're testing
CREATE TABLE IF NOT EXISTS experiments (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    hypothesis TEXT,
    channel TEXT,
    start_date DATE DEFAULT CURRENT_DATE,
    end_date DATE,
    status TEXT DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
    metric TEXT,
    result_summary TEXT,
    auto_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to companies
DROP TRIGGER IF EXISTS companies_updated_at ON companies;
CREATE TRIGGER companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
