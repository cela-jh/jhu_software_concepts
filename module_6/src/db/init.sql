-- Applicant results scraped from Grad Cafe.
CREATE TABLE IF NOT EXISTS applicants (
    p_id                     INTEGER PRIMARY KEY,
    program                  TEXT    NOT NULL,
    comments                 TEXT,
    date_added               DATE    NOT NULL,
    url                      TEXT    NOT NULL UNIQUE,
    status                   TEXT    NOT NULL,
    term                     TEXT    NOT NULL,
    us_or_international      TEXT    NOT NULL,
    gpa                      FLOAT,
    gre                      FLOAT,
    gre_v                    FLOAT,
    gre_aw                   FLOAT,
    degree                   TEXT    NOT NULL,
    llm_generated_program    TEXT,
    llm_generated_university TEXT
);

-- Tracks the highest-seen identifier per data source for incremental loads.
CREATE TABLE IF NOT EXISTS ingestion_watermarks (
    source     TEXT        PRIMARY KEY,
    last_seen  TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);
