CREATE TABLE IF NOT EXISTS llm_parse_logs (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        INTEGER REFERENCES users (user_id) ON DELETE SET NULL,
    input_text     TEXT NOT NULL,
    parsed_result  JSONB NOT NULL,
    is_correct     BOOLEAN,
    user_timezone  VARCHAR(255) NOT NULL,
    model_name     VARCHAR(255) NOT NULL,
    status         VARCHAR(32) NOT NULL
        CHECK (status IN ('success', 'error', 'needs_clarification')),
    error_message  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_parse_logs_user_created
    ON llm_parse_logs (user_id, created_at);
