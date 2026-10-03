ALTER TABLE fixed_asset
    ADD COLUMN IF NOT EXISTS posting_policy VARCHAR(40) NOT NULL DEFAULT 'monthly_fiscal';

ALTER TABLE fixed_asset
    DROP CONSTRAINT IF EXISTS fixed_asset_posting_policy_check;

ALTER TABLE fixed_asset
    ADD CONSTRAINT fixed_asset_posting_policy_check
    CHECK (posting_policy IN ('monthly_fiscal', 'annual_dec31'));

