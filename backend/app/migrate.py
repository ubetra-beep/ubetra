from sqlalchemy import text

from .database import engine


def run_migrations() -> None:
  with engine.begin() as conn:
    columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
    }
    if "llm_provider" not in columns:
      conn.execute(
        text("ALTER TABLE users ADD COLUMN llm_provider VARCHAR(32) DEFAULT 'server'")
      )
    if "llm_api_key" not in columns:
      conn.execute(text("ALTER TABLE users ADD COLUMN llm_api_key VARCHAR(512) DEFAULT ''"))
    if "llm_model" not in columns:
      conn.execute(text("ALTER TABLE users ADD COLUMN llm_model VARCHAR(120) DEFAULT ''"))
    if "assistant_tone" not in columns:
      conn.execute(text("ALTER TABLE users ADD COLUMN assistant_tone VARCHAR(32) DEFAULT 'balanced'"))
    if "assistant_extra_instructions" not in columns:
      conn.execute(text("ALTER TABLE users ADD COLUMN assistant_extra_instructions TEXT DEFAULT ''"))
    if "assistant_include_tracking" not in columns:
      conn.execute(
        text("ALTER TABLE users ADD COLUMN assistant_include_tracking BOOLEAN DEFAULT 1")
      )
    if "onboarding_completed" not in columns:
      conn.execute(
        text("ALTER TABLE users ADD COLUMN onboarding_completed BOOLEAN DEFAULT 0")
      )
    if "email" not in columns:
      conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255) DEFAULT ''"))
      conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)"))

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "mfa_challenges" not in tables:
      conn.execute(
        text(
          "CREATE TABLE mfa_challenges ("
          "id VARCHAR(36) PRIMARY KEY, "
          "user_id VARCHAR(36) NOT NULL REFERENCES users(id), "
          "code_hash VARCHAR(255) NOT NULL, "
          "expires_at DATETIME NOT NULL, "
          "consumed_at DATETIME, "
          "created_at DATETIME)"
        )
      )
      conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_mfa_challenges_user_id ON mfa_challenges (user_id)")
      )

    membership_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(memberships)")).fetchall()
    }
    if "chastity_enabled" not in membership_columns:
      conn.execute(
        text("ALTER TABLE memberships ADD COLUMN chastity_enabled BOOLEAN DEFAULT 0")
      )
    if "chastity_max_lock_hours" not in membership_columns:
      conn.execute(
        text("ALTER TABLE memberships ADD COLUMN chastity_max_lock_hours INTEGER")
      )
    if "chastity_enrollment_requested" not in membership_columns:
      conn.execute(
        text("ALTER TABLE memberships ADD COLUMN chastity_enrollment_requested BOOLEAN DEFAULT 0")
      )
    # One-time: no enrollment approval — enable chastity for all submissives; clear request flags.
    try:
      done = conn.execute(
        text("SELECT 1 FROM ubetra_migrations WHERE name = 'chastity_no_enroll_v1' LIMIT 1")
      ).fetchone()
    except Exception:
      conn.execute(
        text(
          "CREATE TABLE IF NOT EXISTS ubetra_migrations ("
          "name VARCHAR(120) PRIMARY KEY, applied_at DATETIME)"
        )
      )
      done = None
    if not done:
      try:
        conn.execute(
          text(
            "UPDATE memberships SET chastity_enabled = 1 "
            "WHERE role = 'submissive'"
          )
        )
        conn.execute(
          text("UPDATE memberships SET chastity_enrollment_requested = 0")
        )
        conn.execute(
          text(
            "INSERT OR IGNORE INTO ubetra_migrations (name, applied_at) "
            "VALUES ('chastity_no_enroll_v1', CURRENT_TIMESTAMP)"
          )
        )
      except Exception:
        pass

    lockup_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(chastity_lockups)")).fetchall()
    }
    if lockup_columns:
      if "planned_end_at" not in lockup_columns:
        conn.execute(text("ALTER TABLE chastity_lockups ADD COLUMN planned_end_at DATETIME"))
      if "record_type" not in lockup_columns:
        conn.execute(
          text("ALTER TABLE chastity_lockups ADD COLUMN record_type VARCHAR(32) DEFAULT 'normal'")
        )
      if "tags" not in lockup_columns:
        conn.execute(text("ALTER TABLE chastity_lockups ADD COLUMN tags VARCHAR(500) DEFAULT ''"))
      if "ended_kind" not in lockup_columns:
        conn.execute(text("ALTER TABLE chastity_lockups ADD COLUMN ended_kind VARCHAR(32) DEFAULT ''"))
      if "timer_notified_at" not in lockup_columns:
        conn.execute(text("ALTER TABLE chastity_lockups ADD COLUMN timer_notified_at DATETIME"))
      # Backfill: ended lockups without a kind → unlocked (Released! reserved for orgasm/timer)
      conn.execute(
        text(
          "UPDATE chastity_lockups SET ended_kind = 'unlocked' "
          "WHERE status = 'ended' AND (ended_kind IS NULL OR ended_kind = '')"
        )
      )
      conn.execute(
        text(
          "UPDATE chastity_lockups SET ended_kind = 'historical' "
          "WHERE record_type = 'historical' AND (ended_kind IS NULL OR ended_kind = '' OR ended_kind = 'unlocked')"
        )
      )

    break_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(chastity_breaks)")).fetchall()
    }
    if break_columns and "tags" not in break_columns:
      conn.execute(text("ALTER TABLE chastity_breaks ADD COLUMN tags VARCHAR(500) DEFAULT ''"))

    org_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(org_tracking_entries)")).fetchall()
    }
    if org_columns and "tags" not in org_columns:
      conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN tags VARCHAR(500) DEFAULT ''"))
    if org_columns and "dominant_time_at" not in org_columns:
      conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN dominant_time_at DATETIME"))
    if org_columns and "submissive_time_at" not in org_columns:
      conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN submissive_time_at DATETIME"))
    if org_columns and "ended_at" not in org_columns:
      conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN ended_at DATETIME"))
    if org_columns and "dominant_duration_minutes" not in org_columns:
      conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN dominant_duration_minutes INTEGER"))
    if org_columns and "submissive_duration_minutes" not in org_columns:
      conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN submissive_duration_minutes INTEGER"))
    if org_columns and "duration_minutes" not in org_columns:
      conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN duration_minutes INTEGER"))
    if org_columns:
      conn.execute(
        text(
          "UPDATE org_tracking_entries SET duration_minutes = COALESCE("
          "dominant_duration_minutes, submissive_duration_minutes) "
          "WHERE duration_minutes IS NULL AND "
          "(dominant_duration_minutes IS NOT NULL OR submissive_duration_minutes IS NOT NULL)"
        )
      )

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "org_tracking_orgasms" not in tables:
      conn.execute(
        text(
          "CREATE TABLE org_tracking_orgasms ("
          "id VARCHAR(36) PRIMARY KEY, "
          "entry_id VARCHAR(36) NOT NULL REFERENCES org_tracking_entries(id), "
          "tags VARCHAR(500) DEFAULT '', "
          "position INTEGER DEFAULT 0, "
          "created_at DATETIME)"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_org_tracking_orgasms_entry_id "
          "ON org_tracking_orgasms (entry_id)"
        )
      )

    if org_columns:
      conn.execute(
        text("UPDATE org_tracking_entries SET event_type = 'no_orgasm' WHERE event_type = 'sex'")
      )
      conn.execute(
        text("UPDATE org_tracking_entries SET event_type = 'orgasm' WHERE event_type = 'both'")
      )
      legacy_orgasms = conn.execute(
        text(
          "SELECT e.id, e.tags, e.event_type FROM org_tracking_entries e "
          "LEFT JOIN org_tracking_orgasms o ON o.entry_id = e.id "
          "WHERE o.id IS NULL AND e.event_type IN ('orgasm', 'both')"
        )
      ).fetchall()
      import uuid

      for row in legacy_orgasms:
        conn.execute(
          text(
            "INSERT INTO org_tracking_orgasms (id, entry_id, tags, position, created_at) "
            "VALUES (:id, :entry_id, :tags, 0, datetime('now'))"
          ),
          {
            "id": str(uuid.uuid4()),
            "entry_id": row[0],
            "tags": row[1] or "",
          },
        )

    dynamic_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(dynamics)")).fetchall()
    }
    if dynamic_columns:
      if "tag_presets" not in dynamic_columns:
        conn.execute(
          text(
            "ALTER TABLE dynamics ADD COLUMN tag_presets TEXT DEFAULT "
            "'full orgasm,ruined orgasm,denied,milking,partial-milking,dildo,handjob,piv,"
            "finger,oral,vibrator,masturbation,cheated,anal,prostate'"
          )
        )
      if "chastity_tag_presets" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chastity_tag_presets TEXT DEFAULT ''")
        )
      if "chat_retain_history" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chat_retain_history BOOLEAN DEFAULT 0")
        )
      if "chat_e2e_enabled" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chat_e2e_enabled BOOLEAN DEFAULT 0")
        )
      if "chat_shared_key" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chat_shared_key TEXT DEFAULT ''")
        )
      # Seed shared keys from prior one-time transfer rows when possible.
      try:
        conn.execute(
          text(
            "UPDATE dynamics SET chat_shared_key = ("
            "  SELECT t.key_payload FROM chat_key_transfers t "
            "  WHERE t.dynamic_id = dynamics.id "
            "  ORDER BY COALESCE(t.redeemed_at, t.created_at) DESC LIMIT 1"
            ") "
            "WHERE chat_e2e_enabled = 1 "
            "AND (chat_shared_key IS NULL OR chat_shared_key = '') "
            "AND EXISTS (SELECT 1 FROM chat_key_transfers t2 WHERE t2.dynamic_id = dynamics.id)"
          )
        )
      except Exception:
        pass
      if "chat_expire_hours" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chat_expire_hours INTEGER DEFAULT 720")
        )
      # One-time-ish: old auto-delete default was 24h — too short for offline / multi-device.
      # Only bump rows still on that short auto-delete default (not forever-history dynamics).
      try:
        conn.execute(
          text(
            "UPDATE dynamics SET chat_expire_hours = 720 "
            "WHERE chat_expire_hours = 24 AND chat_retain_history = 0"
          )
        )
      except Exception:
        pass
      if "chat_system_events" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chat_system_events BOOLEAN DEFAULT 1")
        )
      if "chat_push_enabled" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chat_push_enabled BOOLEAN DEFAULT 1")
        )
      if "chastity_sub_can_delete_breaks" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN chastity_sub_can_delete_breaks BOOLEAN DEFAULT 1")
        )
      if "act_categories" not in dynamic_columns:
        conn.execute(text("ALTER TABLE dynamics ADD COLUMN act_categories TEXT DEFAULT ''"))

    user_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
    }
    if user_columns and "push_enabled" not in user_columns:
      conn.execute(text("ALTER TABLE users ADD COLUMN push_enabled BOOLEAN DEFAULT 1"))

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "push_subscriptions" not in tables:
      conn.execute(
        text(
          "CREATE TABLE push_subscriptions ("
          "id VARCHAR(36) PRIMARY KEY, "
          "user_id VARCHAR(36) NOT NULL REFERENCES users(id), "
          "endpoint VARCHAR(512) NOT NULL UNIQUE, "
          "p256dh VARCHAR(256) NOT NULL, "
          "auth VARCHAR(128) NOT NULL, "
          "created_at DATETIME)"
        )
      )
      conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user_id ON push_subscriptions (user_id)")
      )

    task_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(tasks)")).fetchall()
    }
    if task_columns:
      if "created_by_membership_id" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN created_by_membership_id VARCHAR(36)"))
      if "tags" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN tags VARCHAR(500) DEFAULT ''"))
      if "approval_status" not in task_columns:
        conn.execute(
          text("ALTER TABLE tasks ADD COLUMN approval_status VARCHAR(32) DEFAULT 'approved'")
        )
      if "source" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN source VARCHAR(32) DEFAULT 'dom'"))
      if "recurrence" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN recurrence VARCHAR(32) DEFAULT 'none'"))
      if "due_at" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN due_at DATETIME"))
      if "next_due_at" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN next_due_at DATETIME"))
      if "act_id" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN act_id VARCHAR(36)"))
      if "assigned_to_membership_id" not in task_columns:
        conn.execute(
          text("ALTER TABLE tasks ADD COLUMN assigned_to_membership_id VARCHAR(36)")
        )
      if "is_private" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN is_private BOOLEAN DEFAULT 0"))

    membership_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(memberships)")).fetchall()
    }
    if "inbox_acked_at" not in membership_columns:
      conn.execute(text("ALTER TABLE memberships ADD COLUMN inbox_acked_at DATETIME"))
    if "interview_completed" not in membership_columns:
      conn.execute(
        text("ALTER TABLE memberships ADD COLUMN interview_completed BOOLEAN DEFAULT 0")
      )
    if "interview_summary" not in membership_columns:
      conn.execute(text("ALTER TABLE memberships ADD COLUMN interview_summary TEXT DEFAULT ''"))
    if "spti_data" not in membership_columns:
      conn.execute(text("ALTER TABLE memberships ADD COLUMN spti_data TEXT DEFAULT ''"))
    if "spti_completed_at" not in membership_columns:
      conn.execute(text("ALTER TABLE memberships ADD COLUMN spti_completed_at DATETIME"))
    if "share_kinks" not in membership_columns:
      conn.execute(text("ALTER TABLE memberships ADD COLUMN share_kinks BOOLEAN DEFAULT 0"))
    if "survey_skipped" not in membership_columns:
      conn.execute(text("ALTER TABLE memberships ADD COLUMN survey_skipped BOOLEAN DEFAULT 0"))

    user_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
    }
    if user_columns:
      if "google_refresh_token" not in user_columns:
        conn.execute(text("ALTER TABLE users ADD COLUMN google_refresh_token TEXT DEFAULT ''"))
      if "google_tasks_list_id" not in user_columns:
        conn.execute(
          text("ALTER TABLE users ADD COLUMN google_tasks_list_id VARCHAR(128) DEFAULT '@default'")
        )

    task_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(tasks)")).fetchall()
    }
    if task_columns:
      if "public_code_word" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN public_code_word VARCHAR(200) DEFAULT ''"))
      if "google_task_id" not in task_columns:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN google_task_id VARCHAR(128) DEFAULT ''"))

    dynamic_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(dynamics)")).fetchall()
    }
    if dynamic_columns:
      if "shared_llm_provider" not in dynamic_columns:
        conn.execute(text("ALTER TABLE dynamics ADD COLUMN shared_llm_provider VARCHAR(32) DEFAULT ''"))
      if "shared_llm_api_key" not in dynamic_columns:
        conn.execute(text("ALTER TABLE dynamics ADD COLUMN shared_llm_api_key VARCHAR(512) DEFAULT ''"))
      if "shared_llm_model" not in dynamic_columns:
        conn.execute(text("ALTER TABLE dynamics ADD COLUMN shared_llm_model VARCHAR(120) DEFAULT ''"))
      if "shared_llm_set_by_membership_id" not in dynamic_columns:
        conn.execute(text("ALTER TABLE dynamics ADD COLUMN shared_llm_set_by_membership_id VARCHAR(36)"))
      if "enabled_features" not in dynamic_columns:
        conn.execute(text("ALTER TABLE dynamics ADD COLUMN enabled_features TEXT DEFAULT ''"))

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "chastity_limit_proposals" not in tables:
      conn.execute(
        text(
          "CREATE TABLE chastity_limit_proposals ("
          "id VARCHAR(36) PRIMARY KEY, "
          "dynamic_id VARCHAR(36) NOT NULL REFERENCES dynamics(id), "
          "for_membership_id VARCHAR(36) NOT NULL REFERENCES memberships(id), "
          "proposed_max_hours INTEGER NOT NULL, "
          "rationale TEXT DEFAULT '', "
          "status VARCHAR(32) DEFAULT 'pending', "
          "proposed_by_membership_id VARCHAR(36) NOT NULL REFERENCES memberships(id), "
          "reviewed_by_membership_id VARCHAR(36) REFERENCES memberships(id), "
          "created_at DATETIME, "
          "reviewed_at DATETIME)"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_chastity_limit_proposals_dynamic_id "
          "ON chastity_limit_proposals (dynamic_id)"
        )
      )

    act_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(acts_of_submission)")).fetchall()
    }
    if "knowledge_focus" not in act_columns:
      conn.execute(
        text("ALTER TABLE acts_of_submission ADD COLUMN knowledge_focus VARCHAR(255) DEFAULT ''")
      )
    if "act_type_id" not in act_columns:
      conn.execute(text("ALTER TABLE acts_of_submission ADD COLUMN act_type_id VARCHAR(80) DEFAULT ''"))
    if "act_type_title" not in act_columns:
      conn.execute(text("ALTER TABLE acts_of_submission ADD COLUMN act_type_title VARCHAR(120) DEFAULT ''"))

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "ground_rules" in tables and "agreements" in tables:
      existing = conn.execute(text("SELECT COUNT(*) FROM agreements")).scalar() or 0
      if existing == 0:
        legacy_rows = conn.execute(
          text(
            "SELECT dynamic_id, approved_content, pending_content, "
            "pending_by_membership_id, pending_at, approved_at, "
            "approved_by_membership_id, updated_at FROM ground_rules"
          )
        ).fetchall()
        for row in legacy_rows:
          approved = (row[1] or "").strip()
          pending = (row[2] or "").strip()
          if not approved and not pending:
            continue
          import uuid

          agreement_id = str(uuid.uuid4())
          created_by = row[3] or row[6]
          if not created_by:
            member = conn.execute(
              text(
                "SELECT id FROM memberships WHERE dynamic_id = :dynamic_id LIMIT 1"
              ),
              {"dynamic_id": row[0]},
            ).fetchone()
            created_by = member[0] if member else agreement_id
          conn.execute(
            text(
              "INSERT INTO agreements (id, dynamic_id, title, approved_content, "
              "pending_content, pending_by_membership_id, pending_at, approved_at, "
              "approved_by_membership_id, created_by_membership_id, position, "
              "created_at, updated_at) VALUES "
              "(:id, :dynamic_id, :title, :approved, :pending, :pending_by, "
              ":pending_at, :approved_at, :approved_by, :created_by, 1, "
              ":updated_at, :updated_at)"
            ),
            {
              "id": agreement_id,
              "dynamic_id": row[0],
              "title": "Ground rules",
              "approved": approved,
              "pending": pending,
              "pending_by": row[3],
              "pending_at": row[4],
              "approved_at": row[5],
              "approved_by": row[6],
              "created_by": created_by,
              "updated_at": row[7],
            },
          )

    # Remap retired Gemini model IDs saved on users / shared dynamics.
    deprecated_models = {
      "gemini-2.0-flash": "gemini-3.5-flash",
      "gemini-2.0-flash-001": "gemini-3.5-flash",
      "gemini-2.0-flash-lite": "gemini-3.1-flash-lite",
      "gemini-2.0-flash-lite-001": "gemini-3.1-flash-lite",
      "gemini-2.5-flash": "gemini-3.5-flash",
      "gemini-2.5-flash-lite": "gemini-3.1-flash-lite",
      "gemini-1.5-pro": "gemini-3.5-flash",
      "gemini-1.5-flash": "gemini-3.5-flash",
      "gemini-pro": "gemini-3.5-flash",
      "gemini-pro-latest": "gemini-3.5-flash",
    }
    for old, new in deprecated_models.items():
      conn.execute(
        text("UPDATE users SET llm_model = :new WHERE llm_model = :old"),
        {"old": old, "new": new},
      )
      if dynamic_columns and "shared_llm_model" in dynamic_columns:
        conn.execute(
          text("UPDATE dynamics SET shared_llm_model = :new WHERE shared_llm_model = :old"),
          {"old": old, "new": new},
        )

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "spin_game_sessions" not in tables:
      conn.execute(
        text(
          "CREATE TABLE spin_game_sessions ("
          "id VARCHAR(36) PRIMARY KEY, "
          "dynamic_id VARCHAR(36) NOT NULL REFERENCES dynamics(id), "
          "created_by_membership_id VARCHAR(36) NOT NULL REFERENCES memberships(id), "
          "status VARCHAR(32) DEFAULT 'active', "
          "started_at DATETIME, "
          "updated_at DATETIME, "
          "secret_json TEXT DEFAULT '{}', "
          "public_json TEXT DEFAULT '{}')"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_spin_game_sessions_dynamic_id "
          "ON spin_game_sessions (dynamic_id)"
        )
      )

    user_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
    if "biological_sex" not in user_columns:
      conn.execute(text("ALTER TABLE users ADD COLUMN biological_sex VARCHAR(32) DEFAULT ''"))

    dynamic_columns = {
      row[1] for row in conn.execute(text("PRAGMA table_info(dynamics)")).fetchall()
    }
    if "feelings_prompt_mode" not in dynamic_columns:
      conn.execute(
        text("ALTER TABLE dynamics ADD COLUMN feelings_prompt_mode VARCHAR(16) DEFAULT 'soft'")
      )
    if "feelings_require_end_of_day" not in dynamic_columns:
      conn.execute(
        text("ALTER TABLE dynamics ADD COLUMN feelings_require_end_of_day BOOLEAN DEFAULT 1")
      )

    chat_columns = {
      row[1] for row in conn.execute(text("PRAGMA table_info(chat_messages)")).fetchall()
    }
    if "action" not in chat_columns:
      conn.execute(text("ALTER TABLE chat_messages ADD COLUMN action VARCHAR(64) DEFAULT ''"))
    if "payload_json" not in chat_columns:
      conn.execute(text("ALTER TABLE chat_messages ADD COLUMN payload_json TEXT DEFAULT ''"))

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "feeling_checkins" not in tables:
      conn.execute(
        text(
          "CREATE TABLE feeling_checkins ("
          "id VARCHAR(36) PRIMARY KEY, "
          "dynamic_id VARCHAR(36) NOT NULL REFERENCES dynamics(id), "
          "for_membership_id VARCHAR(36) NOT NULL REFERENCES memberships(id), "
          "logged_by_membership_id VARCHAR(36) NOT NULL REFERENCES memberships(id), "
          "context VARCHAR(32) DEFAULT 'ad_hoc', "
          "selections_json TEXT DEFAULT '[]', "
          "org_entry_id VARCHAR(36), "
          "chastity_lockup_id VARCHAR(36), "
          "spin_session_id VARCHAR(36), "
          "occurred_at DATETIME, "
          "created_at DATETIME)"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_feeling_checkins_dynamic_id "
          "ON feeling_checkins (dynamic_id)"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_feeling_checkins_for_membership_id "
          "ON feeling_checkins (for_membership_id)"
        )
      )

    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "feeling_emotions" not in tables:
      conn.execute(
        text(
          "CREATE TABLE feeling_emotions ("
          "id VARCHAR(80) PRIMARY KEY, "
          "label VARCHAR(80) NOT NULL, "
          "level INTEGER DEFAULT 1, "
          "parent_id VARCHAR(80) REFERENCES feeling_emotions(id), "
          "color VARCHAR(16) DEFAULT '', "
          "description TEXT DEFAULT '', "
          "sort_order INTEGER DEFAULT 0)"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_feeling_emotions_parent_id "
          "ON feeling_emotions (parent_id)"
        )
      )
    else:
      emotion_cols = {
        row[1]
        for row in conn.execute(text("PRAGMA table_info(feeling_emotions)")).fetchall()
      }
      if "description" not in emotion_cols:
        conn.execute(
          text("ALTER TABLE feeling_emotions ADD COLUMN description TEXT DEFAULT ''")
        )
    if "feeling_checkin_selections" not in tables:
      conn.execute(
        text(
          "CREATE TABLE feeling_checkin_selections ("
          "id VARCHAR(36) PRIMARY KEY, "
          "checkin_id VARCHAR(36) NOT NULL REFERENCES feeling_checkins(id), "
          "emotion_id VARCHAR(80) NOT NULL REFERENCES feeling_emotions(id))"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_feeling_checkin_selections_checkin_id "
          "ON feeling_checkin_selections (checkin_id)"
        )
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_feeling_checkin_selections_emotion_id "
          "ON feeling_checkin_selections (emotion_id)"
        )
      )

    # Repair inverted chastity intervals that inflate % locked / hub subtitles
    chastity_tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "chastity_breaks" in chastity_tables:
      conn.execute(
        text(
          "UPDATE chastity_breaks SET ended_at = started_at "
          "WHERE ended_at IS NOT NULL AND ended_at < started_at"
        )
      )
    if "chastity_lockups" in chastity_tables:
      conn.execute(
        text(
          "UPDATE chastity_lockups SET ended_at = started_at "
          "WHERE ended_at IS NOT NULL AND ended_at < started_at"
        )
      )

    # Sex & orgasm tracking: couple fields + per-dynamic prefs
    dynamic_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(dynamics)")).fetchall()
    }
    if "org_tracking_prefs" not in dynamic_columns:
      conn.execute(text("ALTER TABLE dynamics ADD COLUMN org_tracking_prefs TEXT DEFAULT ''"))
    if "chastity_goals" not in dynamic_columns:
      conn.execute(text("ALTER TABLE dynamics ADD COLUMN chastity_goals TEXT DEFAULT ''"))

    # Self-reported punishments
    tables = {
      row[0]
      for row in conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
      ).fetchall()
    }
    if "punishment_reports" not in tables:
      conn.execute(
        text(
          """
          CREATE TABLE punishment_reports (
            id VARCHAR(36) PRIMARY KEY,
            dynamic_id VARCHAR(36) NOT NULL,
            reported_by_membership_id VARCHAR(36) NOT NULL,
            action_text TEXT DEFAULT '',
            status VARCHAR(32) DEFAULT 'pending',
            applied_changes TEXT DEFAULT '[]',
            ideas TEXT DEFAULT '[]',
            remind_at DATETIME,
            resolved_at DATETIME,
            resolved_by_membership_id VARCHAR(36),
            created_at DATETIME
          )
          """
        )
      )
      conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_punishment_reports_dynamic_id ON punishment_reports (dynamic_id)")
      )
      conn.execute(
        text(
          "CREATE INDEX IF NOT EXISTS ix_punishment_reports_reported_by "
          "ON punishment_reports (reported_by_membership_id)"
        )
      )
    else:
      punish_cols = {
        row[1]
        for row in conn.execute(text("PRAGMA table_info(punishment_reports)")).fetchall()
      }
      if "remind_at" not in punish_cols:
        conn.execute(text("ALTER TABLE punishment_reports ADD COLUMN remind_at DATETIME"))
      if "resolved_at" not in punish_cols:
        conn.execute(text("ALTER TABLE punishment_reports ADD COLUMN resolved_at DATETIME"))
      if "resolved_by_membership_id" not in punish_cols:
        conn.execute(
          text("ALTER TABLE punishment_reports ADD COLUMN resolved_by_membership_id VARCHAR(36)")
        )
      # Older rows used logged/applied — normalize open confessions to pending
      conn.execute(
        text(
          "UPDATE punishment_reports SET status='pending' "
          "WHERE status IN ('logged') AND (applied_changes IS NULL OR applied_changes='' OR applied_changes='[]')"
        )
      )

    org_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(org_tracking_entries)")).fetchall()
    }
    if org_columns:
      if "location" not in org_columns:
        conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN location VARCHAR(120) DEFAULT ''"))
      if "initiated_by_membership_id" not in org_columns:
        conn.execute(
          text("ALTER TABLE org_tracking_entries ADD COLUMN initiated_by_membership_id VARCHAR(36)")
        )
      if "protection" not in org_columns:
        conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN protection VARCHAR(32) DEFAULT ''"))
      if "satisfaction" not in org_columns:
        conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN satisfaction INTEGER"))
      if "edging_count" not in org_columns:
        conn.execute(text("ALTER TABLE org_tracking_entries ADD COLUMN edging_count INTEGER"))
      if "notes_private" not in org_columns:
        conn.execute(
          text("ALTER TABLE org_tracking_entries ADD COLUMN notes_private BOOLEAN DEFAULT 0")
        )

    # Feelings check-ins: optional horny intensity (0–10)
    checkin_cols = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(feeling_checkins)")).fetchall()
    }
    if checkin_cols and "horny_level" not in checkin_cols:
      conn.execute(text("ALTER TABLE feeling_checkins ADD COLUMN horny_level INTEGER"))

    # Chat images: Dom lock / permission unlock
    chat_msg_cols = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(chat_messages)")).fetchall()
    }
    if chat_msg_cols:
      if "image_locked" not in chat_msg_cols:
        conn.execute(
          text("ALTER TABLE chat_messages ADD COLUMN image_locked BOOLEAN DEFAULT 0")
        )
      if "image_unlock_granted" not in chat_msg_cols:
        conn.execute(
          text(
            "ALTER TABLE chat_messages ADD COLUMN image_unlock_granted BOOLEAN DEFAULT 0"
          )
        )

    dynamic_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(dynamics)")).fetchall()
    }
    if dynamic_columns:
      if "assistant_tone" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN assistant_tone VARCHAR(32) DEFAULT 'balanced'")
        )
      if "assistant_extra_instructions" not in dynamic_columns:
        conn.execute(
          text("ALTER TABLE dynamics ADD COLUMN assistant_extra_instructions TEXT DEFAULT ''")
        )

    # Context library: server files + AI subject tags
    context_cols = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(context_links)")).fetchall()
    }
    if context_cols:
      if "subject" not in context_cols:
        conn.execute(text("ALTER TABLE context_links ADD COLUMN subject VARCHAR(32) DEFAULT 'other'"))
      if "filename" not in context_cols:
        conn.execute(text("ALTER TABLE context_links ADD COLUMN filename VARCHAR(255) DEFAULT ''"))
      if "mime_type" not in context_cols:
        conn.execute(text("ALTER TABLE context_links ADD COLUMN mime_type VARCHAR(120) DEFAULT ''"))
      if "file_size" not in context_cols:
        conn.execute(text("ALTER TABLE context_links ADD COLUMN file_size INTEGER DEFAULT 0"))
      if "use_for_ai" not in context_cols:
        conn.execute(text("ALTER TABLE context_links ADD COLUMN use_for_ai BOOLEAN DEFAULT 1"))
      if "partner_visible" not in context_cols:
        conn.execute(
          text("ALTER TABLE context_links ADD COLUMN partner_visible BOOLEAN DEFAULT 1")
        )
      # One-time backfill subject from legacy category
      try:
        conn.execute(
          text(
            "CREATE TABLE IF NOT EXISTS ubetra_migrations ("
            "name VARCHAR(120) PRIMARY KEY, applied_at DATETIME)"
          )
        )
        done = conn.execute(
          text("SELECT 1 FROM ubetra_migrations WHERE name = 'context_subject_v1' LIMIT 1")
        ).fetchone()
        if not done:
          conn.execute(
            text(
              "UPDATE context_links SET subject = CASE category "
              "WHEN 'fictional_story' THEN 'stories' "
              "WHEN 'scene_inspiration' THEN 'scenes' "
              "ELSE 'other' END "
              "WHERE subject IS NULL OR subject = '' OR subject = 'other'"
            )
          )
          conn.execute(
            text(
              "INSERT OR IGNORE INTO ubetra_migrations (name, applied_at) "
              "VALUES ('context_subject_v1', CURRENT_TIMESTAMP)"
            )
          )
      except Exception:
        pass

    conn.execute(
      text(
        """
        CREATE TABLE IF NOT EXISTS journal_entries (
          id VARCHAR(36) PRIMARY KEY,
          dynamic_id VARCHAR(36) NOT NULL,
          membership_id VARCHAR(36) NOT NULL,
          title VARCHAR(200) DEFAULT '',
          body TEXT DEFAULT '',
          use_for_ai BOOLEAN DEFAULT 1,
          llm_assisted BOOLEAN DEFAULT 0,
          partner_visible BOOLEAN DEFAULT 1,
          created_at DATETIME,
          updated_at DATETIME
        )
        """
      )
    )
    conn.execute(
      text("CREATE INDEX IF NOT EXISTS ix_journal_entries_dynamic_id ON journal_entries (dynamic_id)")
    )
    conn.execute(
      text(
        "CREATE INDEX IF NOT EXISTS ix_journal_entries_membership_id ON journal_entries (membership_id)"
      )
    )

    journal_cols = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(journal_entries)")).fetchall()
    }
    if journal_cols and "partner_visible" not in journal_cols:
      conn.execute(
        text("ALTER TABLE journal_entries ADD COLUMN partner_visible BOOLEAN DEFAULT 1")
      )

    conn.execute(
      text(
        """
        CREATE TABLE IF NOT EXISTS native_push_tokens (
          id VARCHAR(36) PRIMARY KEY,
          user_id VARCHAR(36) NOT NULL,
          token VARCHAR(512) NOT NULL UNIQUE,
          platform VARCHAR(32) DEFAULT 'android',
          app_id VARCHAR(64) DEFAULT 'ubetra-android',
          created_at DATETIME,
          updated_at DATETIME
        )
        """
      )
    )
    conn.execute(
      text("CREATE INDEX IF NOT EXISTS ix_native_push_tokens_user_id ON native_push_tokens (user_id)")
    )
    conn.execute(
      text("CREATE INDEX IF NOT EXISTS ix_native_push_tokens_token ON native_push_tokens (token)")
    )

    # Core knowledge table (create_all normally creates it; ensure for older DBs)
    conn.execute(
      text(
        """
        CREATE TABLE IF NOT EXISTS core_knowledge (
          id VARCHAR(36) PRIMARY KEY,
          membership_id VARCHAR(36) NOT NULL UNIQUE,
          relationship_context TEXT DEFAULT '',
          distance TEXT DEFAULT '',
          space TEXT DEFAULT '',
          budget TEXT DEFAULT '',
          about_you TEXT DEFAULT '',
          desires TEXT DEFAULT '',
          submitted BOOLEAN DEFAULT 0,
          updated_at DATETIME
        )
        """
      )
    )
    conn.execute(
      text(
        "CREATE INDEX IF NOT EXISTS ix_core_knowledge_membership_id "
        "ON core_knowledge (membership_id)"
      )
    )

    dynamic_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(dynamics)")).fetchall()
    }
    if "task_tag_presets" not in dynamic_columns:
      conn.execute(
        text(
          "ALTER TABLE dynamics ADD COLUMN task_tag_presets TEXT DEFAULT "
          "'Domestic,Health / Hygiene,Sensual,Sexual'"
        )
      )

    task_columns = {
      row[1]
      for row in conn.execute(text("PRAGMA table_info(tasks)")).fetchall()
    }
    if "paused" not in task_columns:
      conn.execute(text("ALTER TABLE tasks ADD COLUMN paused BOOLEAN DEFAULT 0"))
    if "makeup_status" not in task_columns:
      conn.execute(
        text("ALTER TABLE tasks ADD COLUMN makeup_status VARCHAR(16) DEFAULT 'none'")
      )
    if "makeup_note" not in task_columns:
      conn.execute(text("ALTER TABLE tasks ADD COLUMN makeup_note TEXT DEFAULT ''"))
    if "makeup_requested_at" not in task_columns:
      conn.execute(text("ALTER TABLE tasks ADD COLUMN makeup_requested_at DATETIME"))
    if "makeup_granted_at" not in task_columns:
      conn.execute(text("ALTER TABLE tasks ADD COLUMN makeup_granted_at DATETIME"))
