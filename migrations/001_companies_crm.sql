-- Migration: Add CRM fields to companies table
-- Run in Supabase SQL Editor: https://supabase.com/dashboard/project/giptkpwwhwhtrrrmdfqt/sql/new

ALTER TABLE companies ADD COLUMN IF NOT EXISTS current_provider TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS commodities TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS contract_renewal_date DATE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS next_action TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS next_action_date DATE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS contact_name TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS contact_role TEXT;

CREATE INDEX IF NOT EXISTS idx_companies_renewal ON companies(contract_renewal_date)
    WHERE contract_renewal_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companies_next_action ON companies(next_action_date)
    WHERE next_action_date IS NOT NULL;
