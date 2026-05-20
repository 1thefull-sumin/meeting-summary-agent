CREATE DATABASE IF NOT EXISTS MEETING_AGENT_DEV
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE MEETING_AGENT_DEV;

SET time_zone = '+09:00';

CREATE TABLE IF NOT EXISTS meetings (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  file_hash VARCHAR(64) NOT NULL,
  title VARCHAR(255) NOT NULL,
  meeting_date DATE NOT NULL,
  meeting_start_time CHAR(5) DEFAULT '',
  meeting_end_time CHAR(5) DEFAULT '',
  duration_seconds INT UNSIGNED NULL,
  status ENUM('uploaded','pending','done','error','skipped','deleted') NOT NULL DEFAULT 'pending',
  upload_status VARCHAR(30) DEFAULT '',
  stt_status VARCHAR(30) DEFAULT '',
  summary_status VARCHAR(30) DEFAULT '',
  db_status VARCHAR(30) DEFAULT '',
  last_error TEXT,
  retry_count INT UNSIGNED NOT NULL DEFAULT 0,
  summary MEDIUMTEXT,
  decisions MEDIUMTEXT,
  risks MEDIUMTEXT,
  next_actions MEDIUMTEXT,
  flow_message MEDIUMTEXT,
  raw_text LONGTEXT,
  markdown_path VARCHAR(500) DEFAULT '',
  audio_path VARCHAR(500) DEFAULT '',
  transcript_path VARCHAR(500) DEFAULT '',
  source_type VARCHAR(50) DEFAULT 'txt',
  uploaded_by VARCHAR(100) DEFAULT '',
  meeting_type VARCHAR(100) DEFAULT '',
  tags JSON NULL,
  error_message TEXT,
  source_filename VARCHAR(255) DEFAULT '',
  deleted_at DATETIME NULL,
  trash_until DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_meetings_file_hash (file_hash),
  KEY idx_meetings_date (meeting_date),
  KEY idx_meetings_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS meeting_action_items (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  meeting_id BIGINT UNSIGNED NOT NULL,
  owner VARCHAR(100) DEFAULT '',
  task TEXT NOT NULL,
  due_date DATE NULL,
  status VARCHAR(50) DEFAULT 'pending',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_action_items_meeting_id (meeting_id),
  CONSTRAINT fk_action_items_meeting
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS meeting_files (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  meeting_id BIGINT UNSIGNED NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  file_type VARCHAR(50) NOT NULL,
  file_path VARCHAR(500) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_files_meeting_id (meeting_id),
  CONSTRAINT fk_files_meeting
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
