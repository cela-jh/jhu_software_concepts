CREATE TABLE IF NOT EXISTS applicants (
    p_id INTEGER PRIMARY KEY,
    program TEXT NOT NULL,
    comments TEXT,
    date_added DATE NOT NULL,
    url TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,
    term TEXT NOT NULL,
    us_or_international TEXT NOT NULL,
    gpa FLOAT,
    gre FLOAT,
    gre_v FLOAT,
    gre_aw FLOAT,
    degree TEXT NOT NULL,
    llm_generated_program TEXT,
    llm_generated_university TEXT
);
