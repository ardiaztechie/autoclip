-- =====================================================================
-- schema.sql  |  AutoClip: Sistem Auto-Clip Video Berbasis Web
-- Database    : MySQL 8 (juga jalan di MariaDB 10.6+)
-- Cara pakai  : mysql -u root -p < database/schema.sql
-- Aman dijalankan berulang kali: tidak menghapus data yang sudah ada.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS autoclip
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE autoclip;

-- ---------------------------------------------------------------------
-- 1. users: daftar akun. Akun dibuat oleh admin master (tanpa daftar sendiri).
--    Password TIDAK disimpan apa adanya, hanya hash-nya (acakan satu arah).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  email             VARCHAR(190) NOT NULL UNIQUE,
  name              VARCHAR(120) NOT NULL,
  password_hash     VARCHAR(255) NOT NULL,
  role              ENUM('admin','user') NOT NULL DEFAULT 'user',
  is_active         TINYINT(1) NOT NULL DEFAULT 1,       -- 0 = akun dinonaktifkan
  quota_projects    INT NOT NULL DEFAULT 5,              -- batas proyek aktif
  quota_storage_mb  INT NOT NULL DEFAULT 2048,           -- batas penyimpanan (MB)
  created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 2. projects: satu baris = satu video yang dikirim pengguna.
--    status/stage/progress dibaca halaman web untuk menampilkan kemajuan.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id        INT UNSIGNED NOT NULL,
  title          VARCHAR(200) NOT NULL DEFAULT '',
  source_type    ENUM('upload','link') NOT NULL,
  source_ref     VARCHAR(500) NOT NULL DEFAULT '',        -- nama file atau tautan
  language       VARCHAR(10) NOT NULL DEFAULT 'auto',     -- 'auto' = dideteksi Whisper
  ratio          ENUM('9:16','1:1','4:5') NOT NULL DEFAULT '9:16',
  n_clips        TINYINT UNSIGNED NOT NULL DEFAULT 3,
  face_tracking  TINYINT(1) NOT NULL DEFAULT 1,
  status         ENUM('queued','processing','done','failed') NOT NULL DEFAULT 'queued',
  stage          VARCHAR(60) NOT NULL DEFAULT 'Antre',    -- contoh: 'Transkripsi'
  progress       TINYINT UNSIGNED NOT NULL DEFAULT 0,     -- 0-100
  error          TEXT NULL,
  duration_sec   FLOAT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at     TIMESTAMP NULL,                          -- kapan file dibersihkan otomatis
  CONSTRAINT fk_projects_user FOREIGN KEY (user_id)
    REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_projects_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 3. transcripts: hasil Whisper untuk satu proyek.
--    words    = tiap kata + waktu mulai/akhir (JSON)
--    segments = potongan kalimat (JSON)
--    full_text= teks utuh, dipakai untuk fitur pencarian (FULLTEXT)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transcripts (
  project_id  INT UNSIGNED PRIMARY KEY,
  language    VARCHAR(10) NOT NULL,
  model       VARCHAR(30) NOT NULL,                        -- tiny / base / small
  words       JSON NOT NULL,
  segments    JSON NOT NULL,
  full_text   MEDIUMTEXT NULL,
  CONSTRAINT fk_transcripts_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE,
  FULLTEXT KEY ft_transcript (full_text)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 4. clips: potongan video terpilih. Skor 0-1 per komponen, score 0-100.
--    Nama start_sec/end_sec dipakai karena 'start' dan 'end' rawan bentrok
--    dengan kata khusus SQL.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clips (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  project_id      INT UNSIGNED NOT NULL,
  start_sec       FLOAT NOT NULL,
  end_sec         FLOAT NOT NULL,
  score           FLOAT NOT NULL DEFAULT 0,                -- skor akhir 0-100
  hook            FLOAT NOT NULL DEFAULT 0,
  flow            FLOAT NOT NULL DEFAULT 0,
  value_score     FLOAT NOT NULL DEFAULT 0,                -- 'value' dihindari agar tidak rancu
  trend           FLOAT NOT NULL DEFAULT 0,
  title           VARCHAR(200) NOT NULL DEFAULT '',        -- judul yang dipilih
  titles          JSON NULL,                               -- 3 opsi judul
  caption         VARCHAR(500) NOT NULL DEFAULT '',
  hashtags        JSON NULL,
  ratio           ENUM('9:16','1:1','4:5') NOT NULL DEFAULT '9:16',
  status          ENUM('queued','rendering','done','failed') NOT NULL DEFAULT 'queued',
  file_path       VARCHAR(500) NULL,
  size_bytes      BIGINT UNSIGNED NULL,
  render_seconds  FLOAT NULL,
  edit_count      INT UNSIGNED NOT NULL DEFAULT 0,         -- berapa kali diedit pengguna
  edit_settings   JSON NULL,                               -- pengaturan editor: crop, preset caption, dll.
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_clips_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE CASCADE,
  INDEX idx_clips_project (project_id),
  FULLTEXT KEY ft_clips (title, caption)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 5. clip_subtitles: baris subtitle per clip (bisa diedit pengguna).
--    is_edited = 1 bila teksnya dikoreksi, bahan hitung % koreksi di Bab 4.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clip_subtitles (
  id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  clip_id    INT UNSIGNED NOT NULL,
  start_sec  FLOAT NOT NULL,
  end_sec    FLOAT NOT NULL,
  text       VARCHAR(300) NOT NULL,
  position   ENUM('top','middle','bottom') NOT NULL DEFAULT 'bottom',
  is_edited  TINYINT(1) NOT NULL DEFAULT 0,
  CONSTRAINT fk_subtitles_clip FOREIGN KEY (clip_id)
    REFERENCES clips(id) ON DELETE CASCADE,
  INDEX idx_subtitles_clip (clip_id, start_sec)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 6. clip_elements: elemen tambahan yang menempel di clip, selaras dengan
--    isi video (contoh: ikon koin muncul saat kata "uang" diucapkan).
--    source = 'auto'   -> disarankan sistem dari kata kunci
--    source = 'manual' -> ditambahkan pengguna
--    is_enabled = 0    -> saran otomatis yang dimatikan pengguna
--    Dua kolom itu juga bahan Bab 4: berapa persen saran otomatis dipakai.
--    Posisi pos_x/pos_y berupa angka 0-1 (0 = kiri/atas, 1 = kanan/bawah).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clip_elements (
  id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  clip_id     INT UNSIGNED NOT NULL,
  type        ENUM('keyword_highlight','icon','title_text','speaker_name','progress_bar') NOT NULL,
  content     VARCHAR(300) NOT NULL DEFAULT '',            -- teks, atau nama ikon
  start_sec   FLOAT NOT NULL DEFAULT 0,
  end_sec     FLOAT NOT NULL DEFAULT 0,
  pos_x       FLOAT NULL,
  pos_y       FLOAT NULL,
  size        FLOAT NULL,
  style       JSON NULL,                                   -- warna, font, dll.
  source      ENUM('auto','manual') NOT NULL DEFAULT 'auto',
  is_enabled  TINYINT(1) NOT NULL DEFAULT 1,
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_elements_clip FOREIGN KEY (clip_id)
    REFERENCES clips(id) ON DELETE CASCADE,
  INDEX idx_elements_clip (clip_id, start_sec)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 7. job_queue: antrean pekerjaan di MySQL (pengganti Redis/Celery).
--    Web menulis baris 'queued'; worker Python mengambilnya satu per satu.
--    Karena tersimpan di database, antrean tidak hilang saat aplikasi restart.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_queue (
  id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  type        ENUM('process_project','render_clip') NOT NULL,
  payload     JSON NOT NULL,                               -- contoh: {"project_id": 7}
  status      ENUM('queued','running','done','failed') NOT NULL DEFAULT 'queued',
  attempts    TINYINT UNSIGNED NOT NULL DEFAULT 0,
  error       TEXT NULL,
  locked_at   TIMESTAMP NULL,                              -- kapan worker mulai mengerjakan
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_queue_pick (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 8. job_metrics: catatan waktu dan RAM tiap tahap, bahan tabel Bab 4.
--    Sengaja TIDAK ikut terhapus saat proyek dibersihkan (SET NULL),
--    supaya data pengujianmu tidak hilang. video_seconds dicatat agar
--    "waktu proses per menit video" bisa dihitung kapan saja.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_metrics (
  id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  job_id         INT UNSIGNED NULL,
  project_id     INT UNSIGNED NULL,
  stage          VARCHAR(60) NOT NULL,
  seconds        FLOAT NOT NULL,
  peak_ram_mb    FLOAT NULL,
  video_seconds  FLOAT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_metrics_project FOREIGN KEY (project_id)
    REFERENCES projects(id) ON DELETE SET NULL,
  INDEX idx_metrics_stage (stage)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 9. landing_sections: isi landing page yang bisa diedit admin (CMS).
--    'key' adalah kata khusus SQL, jadi namanya section_key.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS landing_sections (
  section_key  VARCHAR(60) PRIMARY KEY,                    -- hero, fitur, cara_kerja, faq, footer
  content      JSON NOT NULL,
  sort_order   INT NOT NULL DEFAULT 0,
  is_visible   TINYINT(1) NOT NULL DEFAULT 1,
  updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 10. media_assets: gambar kecil untuk landing page.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_assets (
  id        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  path      VARCHAR(300) NOT NULL,
  alt_text  VARCHAR(200) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Isi awal landing page (INSERT IGNORE: tidak menimpa yang sudah diedit admin)
-- Akun admin TIDAK dibuat di sini karena butuh hash password; nanti lewat skrip.
-- ---------------------------------------------------------------------
INSERT IGNORE INTO landing_sections (section_key, content, sort_order) VALUES
 ('hero',
  '{"title":"Ubah video panjang menjadi clip pendek","subtitle":"Otomatis, lengkap dengan subtitle, judul, dan caption.","cta_text":"Masuk"}', 1),
 ('fitur',
  '{"items":[{"title":"Clip otomatis","text":"Bagian menarik dipilih dan dipotong untuk kamu."},{"title":"Fokus ke wajah","text":"Bingkai mengikuti pembicara dan zoom secara halus."},{"title":"Siap diedit","text":"Koreksi subtitle, geser awal dan akhir, ganti judul."}]}', 2),
 ('cara_kerja',
  '{"steps":["Unggah video atau tempel tautan","Tunggu proses selesai","Edit seperlunya lalu unduh"]}', 3),
 ('faq',
  '{"items":[{"q":"Berapa lama video maksimal?","a":"Maksimal 20 menit."}]}', 4),
 ('footer',
  '{"text":"Proyek skripsi Teknik Informatika"}', 5);
