-- Idempotent patch: adds PRO columns to existing `users` and `user_events`.
--
-- Why this exists: app/main.py creates schema via Base.metadata.create_all(),
-- which creates NEW tables but never ALTERs existing ones. The PRO release adds
-- columns to `users`, so they must be added explicitly. Safe to run repeatedly.
--
-- New tables (payments, weight_entries, bp_entries, kick_sessions, recipes,
-- doctors, doctor_patients, ai_tasks, postpartum_reminders, referrals) are
-- created automatically by create_all() on app start — not handled here.

BEGIN;

-- Enum types. SQLAlchemy stores enum NAMES (uppercase), not values.
DO $$ BEGIN
    CREATE TYPE postpartumstage AS ENUM ('PREGNANT', 'POSTPARTUM', 'OGTT_6W_DONE', 'OGTT_1Y_DONE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE paymentstatus AS ENUM ('PENDING', 'PAID', 'REFUNDED', 'FAILED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE paymentprovider AS ENUM ('STARS', 'YOOKASSA', 'STRIPE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE producttype AS ENUM ('SUB_MONTHLY', 'SUB_YEARLY', 'PDF_REPORT', 'AI_PHOTO_PACK', 'COURSE', 'DOCTOR_SEAT', 'CONSULTATION');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE subscriptionstatus AS ENUM ('TRIAL', 'ACTIVE', 'EXPIRED', 'CANCELLED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Subscription
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used BOOLEAN DEFAULT FALSE;

-- Postpartum
ALTER TABLE users ADD COLUMN IF NOT EXISTS postpartum_stage postpartumstage DEFAULT 'PREGNANT';
ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_date TIMESTAMP WITHOUT TIME ZONE;

-- Reminders
ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_fasting_time VARCHAR DEFAULT '07:30';
ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_evening_time VARCHAR DEFAULT '21:00';
ALTER TABLE users ADD COLUMN IF NOT EXISTS reminders_enabled BOOLEAN DEFAULT TRUE;

-- Referral
ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id INTEGER REFERENCES users(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR;
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_referral_code ON users (referral_code);

-- Quotas
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_photos_used_month INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_photos_extra INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS pdf_reports_used_month INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_reset_at TIMESTAMP WITHOUT TIME ZONE;

-- Analytics payload
ALTER TABLE user_events ADD COLUMN IF NOT EXISTS payload VARCHAR;

-- Backfill NULLs for rows created before these defaults existed.
UPDATE users SET
    trial_used = COALESCE(trial_used, FALSE),
    postpartum_stage = COALESCE(postpartum_stage, 'PREGNANT'),
    reminder_fasting_time = COALESCE(reminder_fasting_time, '07:30'),
    reminder_evening_time = COALESCE(reminder_evening_time, '21:00'),
    reminders_enabled = COALESCE(reminders_enabled, TRUE),
    ai_photos_used_month = COALESCE(ai_photos_used_month, 0),
    ai_photos_extra = COALESCE(ai_photos_extra, 0),
    pdf_reports_used_month = COALESCE(pdf_reports_used_month, 0);

COMMIT;
