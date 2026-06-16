-- Pure PostgreSQL schema for 5-minute odds polling

CREATE TABLE IF NOT EXISTS fixtures (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT '500',
    external_id     TEXT NOT NULL,
    home_team       TEXT NOT NULL DEFAULT '',
    away_team       TEXT NOT NULL DEFAULT '',
    match_name      TEXT NOT NULL DEFAULT '',
    kickoff_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS odds_ticks (
    id              BIGSERIAL PRIMARY KEY,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fixture_id      BIGINT NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
    source          TEXT NOT NULL DEFAULT '500',
    tick_hash       TEXT NOT NULL,
    -- Asian handicap (close)
    ah_line         NUMERIC,
    ah_home_water   NUMERIC,
    ah_away_water   NUMERIC,
    ah_open_line    NUMERIC,
    ah_open_home    NUMERIC,
    ah_open_away    NUMERIC,
    -- European 1X2 (close)
    eu_home         NUMERIC,
    eu_draw         NUMERIC,
    eu_away         NUMERIC,
    eu_open_home    NUMERIC,
    eu_open_draw    NUMERIC,
    eu_open_away    NUMERIC,
    bookmaker       TEXT NOT NULL DEFAULT 'pinnacle',
    raw_meta        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_odds_ticks_fixture_time
    ON odds_ticks (fixture_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_odds_ticks_hash
    ON odds_ticks (fixture_id, tick_hash);

CREATE TABLE IF NOT EXISTS odds_latest (
    fixture_id      BIGINT PRIMARY KEY REFERENCES fixtures(id) ON DELETE CASCADE,
    captured_at     TIMESTAMPTZ NOT NULL,
    tick_hash       TEXT NOT NULL,
    ah_line         NUMERIC,
    ah_home_water   NUMERIC,
    ah_away_water   NUMERIC,
    ah_open_line    NUMERIC,
    ah_open_home    NUMERIC,
    ah_open_away    NUMERIC,
    eu_home         NUMERIC,
    eu_draw         NUMERIC,
    eu_away         NUMERIC,
    eu_open_home    NUMERIC,
    eu_open_draw    NUMERIC,
    eu_open_away    NUMERIC,
    bookmaker       TEXT NOT NULL DEFAULT 'pinnacle'
);

CREATE TABLE IF NOT EXISTS scraper_state (
    key             TEXT PRIMARY KEY,
    value           JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS predictions (
    id              BIGSERIAL PRIMARY KEY,
    fixture_id      BIGINT NOT NULL REFERENCES fixtures(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id          TEXT,
    result_1x2_cn   TEXT,
    asian_handicap_cn TEXT,
    confidence_cn   TEXT,
    recommendation_source TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_predictions_fixture_time
    ON predictions (fixture_id, created_at DESC);

CREATE TABLE IF NOT EXISTS match_results (
    fixture_id              BIGINT PRIMARY KEY REFERENCES fixtures(id) ON DELETE CASCADE,
    status                  TEXT NOT NULL DEFAULT 'finished',
    home_score              INT,
    away_score              INT,
    score_text              TEXT,
    result_1x2              TEXT,
    result_1x2_cn           TEXT,
    closing_captured_at     TIMESTAMPTZ,
    closing_ah_line         NUMERIC,
    closing_ah_home_water   NUMERIC,
    closing_ah_away_water   NUMERIC,
    closing_eu_home         NUMERIC,
    closing_eu_draw         NUMERIC,
    closing_eu_away         NUMERIC,
    closing_eu_open_home    NUMERIC,
    closing_eu_open_draw    NUMERIC,
    closing_eu_open_away    NUMERIC,
    pick_1x2_cn             TEXT,
    pick_jingcai_cn         TEXT,
    recommended_scores      TEXT,
    hit_1x2                 BOOLEAN,
    hit_score               BOOLEAN,
    payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    settled_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                  TEXT NOT NULL DEFAULT '500'
);

CREATE INDEX IF NOT EXISTS idx_match_results_settled
    ON match_results (settled_at DESC);
