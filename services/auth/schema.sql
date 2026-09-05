-- Auth service. Owns the `auth` schema only; never touches inventory or feedback.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,      -- pbkdf2_hmac(sha256), salt stored inline
    role            TEXT NOT NULL CHECK (role IN ('charity', 'recipient')),
    display_name    TEXT NOT NULL,
    -- recipients are scoped to the charity that invited them; this is the
    -- beneficiary_id their feedback is filed under
    beneficiary_id  TEXT,
    charity_id      BIGINT REFERENCES auth.users(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email ON auth.users (lower(email));
CREATE INDEX IF NOT EXISTS idx_users_role  ON auth.users (role);

-- Public request links a charity can hand out. A recipient using one of these
-- submits feedback with NO account and NO admin access whatsoever.
CREATE TABLE IF NOT EXISTS auth.request_links (
    token        TEXT PRIMARY KEY,
    charity_id   BIGINT NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    label        TEXT NOT NULL DEFAULT 'Public request link',
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    uses         INTEGER NOT NULL DEFAULT 0
);
