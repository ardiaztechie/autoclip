"""Tes worker (backend/worker.py, antrean.py): tanpa menjalankan core.jalankan asli. Runner palsu menulis hasil tiruan."""
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend import antrean, config, konteks, proyek, worker

TABEL = [
    """CREATE TABLE users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
      password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', is_active INTEGER NOT NULL DEFAULT 1,
      quota_projects INTEGER NOT NULL DEFAULT 5, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE projects (
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '',
      source_type TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT 'auto',
      ratio TEXT NOT NULL DEFAULT '9:16', n_clips INTEGER, clip_density TEXT NOT NULL DEFAULT 'sedang', clip_length TEXT NOT NULL DEFAULT 'otomatis',
      face_tracking INTEGER NOT NULL DEFAULT 1,
      status TEXT NOT NULL DEFAULT 'queued', stage TEXT NOT NULL DEFAULT 'Antre', progress INTEGER NOT NULL DEFAULT 0,
      error TEXT, duration_sec REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, expires_at TEXT)""",
    """CREATE TABLE job_queue (
      id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, payload TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, error TEXT, locked_at TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE clips (
      id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, start_sec REAL NOT NULL, end_sec REAL NOT NULL,
      score REAL NOT NULL DEFAULT 0, hook REAL NOT NULL DEFAULT 0, flow REAL NOT NULL DEFAULT 0,
      value_score REAL NOT NULL DEFAULT 0, trend REAL NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '', titles TEXT,
      caption TEXT NOT NULL DEFAULT '', hashtags TEXT, ratio TEXT NOT NULL DEFAULT '9:16',
      status TEXT NOT NULL DEFAULT 'queued', file_path TEXT, size_bytes INTEGER, render_seconds REAL,
      edit_count INTEGER NOT NULL DEFAULT 0, edit_settings TEXT)""",
    """CREATE TABLE job_metrics (
      id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, project_id INTEGER, stage TEXT NOT NULL,
      seconds REAL NOT NULL, peak_ram_mb REAL, video_seconds REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
]
PROSES_CFG = {"maks_durasi_detik": 1200.0}
KLIP = [
    {"mulai": 10.0, "akhir": 40.0, "durasi": 30.0, "skor": 71.5, "huruf": "B", "hook": 0.8, "flow": 0.6, "value": 0.5,
     "trend": 0.4, "teks": "satu"},
    {"mulai": 90.0, "akhir": 130.0, "durasi": 40.0, "skor": 63.2, "huruf": "C", "hook": 0.5, "flow": 0.7, "value": 0.4,
     "trend": 0.3, "teks": "dua"},
]
META = [
    {"nomor": 1, "mulai": 10.0, "akhir": 40.0, "judul": "Judul Satu", "caption": "Caption satu\n\n#a #b", "hashtag": ["#a", "#b"]},
    {"nomor": 2, "mulai": 90.0, "akhir": 130.0, "judul": "Judul Dua", "caption": "Caption dua", "hashtag": []},
]
BARIS_SUKSES = [
    "Video : x", "Hasil : y",
    "", "=== Langkah 1/4: transkripsi ===", "--- transkripsi: selesai (143.6 dtk)",
    "", "=== Langkah 2/4: pemilihan klip ===", "--- pemilihan klip: selesai (1.2 dtk)",
    "", "=== Langkah 3/4: judul, caption, hashtag ===", "--- judul, caption, hashtag: selesai (0.1 dtk)",
    "", "=== Langkah 4/4: render ===",
    "[1/2] hasil/klip_01_9x16.mp4  1080x1920  30.0 dtk  4.2 MB  (wajah 98%)",
    "[2/2] hasil/klip_02_9x16.mp4  1080x1920  40.0 dtk  5.0 MB  (wajah 100%)",
    "--- render: selesai (137.5 dtk)", "", "SELESAI dalam 290.0 dtk.",
]


class Penjalan:
    """Pengganti core.jalankan: mencatat argumen, memancarkan baris, dan (bila diminta) menulis berkas hasil."""

    def __init__(self, baris=BARIS_SUKSES, kode=0, klip=KLIP, meta=META, mp4=2, pada_baris=None, galat=None):
        self.baris, self.kode, self.klip, self.meta, self.mp4 = baris, kode, klip, meta, mp4
        self.pada_baris, self.galat = pada_baris, galat
        self.argv = self.cwd = None
        self.dipanggil = 0

    def __call__(self, argv, cwd, kirim):
        self.dipanggil += 1
        self.argv, self.cwd = argv, cwd
        folder = Path(argv[argv.index("--folder") + 1])
        for b in self.baris:
            kirim(b)
            if self.pada_baris:
                self.pada_baris(b)
        if self.galat:
            raise self.galat
        if self.klip is not None:
            (folder / "klip.json").write_text(json.dumps(self.klip), encoding="utf-8")
        if self.meta is not None:
            (folder / "metadata.json").write_text(json.dumps(self.meta), encoding="utf-8")
        for i in range(1, self.mp4 + 1):
            (folder / f"klip_{i:02d}_{argv[argv.index('--rasio') + 1].replace(':', 'x')}.mp4").write_bytes(b"x" * (1000 * i))
        return self.kode


@pytest.fixture
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with e.begin() as k:
        for t in TABEL:
            k.execute(text(t))
        k.execute(text("INSERT INTO users (email, name, password_hash) VALUES ('a@b.com', 'A', 'x')"))
    return e


@pytest.fixture
def cfg(tmp_path):
    return {"folder": tmp_path / "storage", "maks_bytes": 10**9}


def _proyek(engine, cfg, *, ratio="9:16", n=2, bahasa="auto", wajah=True, sumber=True, panjang="otomatis"):
    with engine.begin() as k:
        pid = proyek.buat(k, 1, "Judul", "a.mp4", bahasa, ratio, n, wajah, panjang=panjang)
        jid = proyek.antrekan(k, pid)
    if sumber:
        folder = cfg["folder"] / "projects" / str(pid)
        folder.mkdir(parents=True)
        (folder / "source.mp4").write_bytes(b"video")
    return pid, jid


def _ambil(engine):
    with engine.begin() as k:
        return antrean.ambil(k)


def _satu(engine, sql, **p):
    with engine.connect() as k:
        return k.execute(text(sql), p).one()


def _proyek_baris(engine, pid):
    return _satu(engine, "SELECT status, stage, progress, error, duration_sec FROM projects WHERE id = :i", i=pid)


def _kerjakan(engine, cfg, penjalan, durasi=lambda p: 180.0):
    job = _ambil(engine)
    return worker.kerjakan(engine, job, cfg, PROSES_CFG, runner=penjalan, durasi=durasi)


# ---------------------------------------------------------------- membaca keluaran
@pytest.mark.parametrize("baris,hasil", [
    ("=== Langkah 1/4: transkripsi ===", {"jenis": "mulai", "langkah": 1}),
    ("=== Langkah 4/4: render ===", {"jenis": "mulai", "langkah": 4}),
    ("=== Langkah 1/4: transkripsi dilewati (kata.json sudah ada; pakai --ulang untuk mengulang) ===",
     {"jenis": "lewati", "langkah": 1}),
    ("--- transkripsi: selesai (143.6 dtk)", {"jenis": "selesai", "detik": 143.6}),
    ("--- judul, caption, hashtag: selesai (0.1 dtk)", {"jenis": "selesai", "detik": 0.1}),
    ("[2/3] hasil/klip_02_9x16.mp4  1080x1920", {"jenis": "klip", "i": 2, "n": 3}),
    ("[GAGAL] tidak ada klip terpilih.", {"jenis": "gagal", "pesan": "tidak ada klip terpilih."}),
    ("--- render: GAGAL (3.0 dtk)", None),
    ("=== Langkah 9/4: aneh ===", None),
    ("Video : x", None), ("", None), ("[OK] sesuatu", None),
])
def test_urai_baris(baris, hasil):
    assert worker.urai_baris(baris) == hasil


def test_kemajuan_urutan_dan_tidak_pernah_turun():
    km, hasil = worker.Kemajuan(), []
    for b in BARIS_SUKSES:
        u = km.terapkan(worker.urai_baris(b))
        if u:
            hasil.append((u["stage"], u["progress"]))
    assert hasil == [("Transkripsi", 2), ("Memilih klip", 47), ("Judul dan caption", 52),
                     ("Render klip", 55), ("Render klip 1/2", 77), ("Render klip 2/2", 99)]
    assert km.metrik == [("transkripsi", 143.6), ("pemilihan_klip", 1.2), ("metadata", 0.1), ("render", 137.5)]
    assert km.terapkan(worker.urai_baris("=== Langkah 1/4: transkripsi ===")) == {"stage": "Transkripsi", "progress": 99}


def test_kemajuan_klip_di_luar_render_diabaikan():
    km = worker.Kemajuan()
    km.terapkan({"jenis": "mulai", "langkah": 2})
    assert km.terapkan({"jenis": "klip", "i": 1, "n": 3}) is None
    km.terapkan({"jenis": "mulai", "langkah": 4})
    assert km.terapkan({"jenis": "klip", "i": 5, "n": 3}) is None
    assert km.terapkan({"jenis": "klip", "i": 0, "n": 3}) is None


def test_transkripsi_dilewati_tidak_mengubah_progres_sampai_tahap_berikutnya():
    km = worker.Kemajuan()
    assert km.terapkan({"jenis": "lewati", "langkah": 1}) is None
    assert km.terapkan({"jenis": "mulai", "langkah": 2}) == {"stage": "Memilih klip", "progress": 47}


# ---------------------------------------------------------------- argumen
def test_argumen_dasar_bahasa_dan_tanpa_wajah():
    p = {"n_clips": 4, "clip_density": "sedang", "clip_length": "otomatis", "ratio": "1:1", "language": "auto",
         "face_tracking": True}
    a = worker.susun_argv("v.mp4", "hasil", p)
    assert a[1:] == ["-m", "core.jalankan", "v.mp4", "--folder", "hasil", "--rasio", "1:1", "--n", "4",
                     "--durasi", "otomatis"]
    b = worker.susun_argv("v.mp4", "hasil", {**p, "language": "id", "face_tracking": False})
    assert b[-4:] == ["--bahasa", "id", "--mode", "tengah"]


def test_argumen_jumlah_otomatis_memakai_tingkat_bukan_n():
    p = {"n_clips": None, "clip_density": "rapat", "clip_length": "pendek", "ratio": "9:16", "language": "auto",
         "face_tracking": True}
    a = worker.susun_argv("v.mp4", "hasil", p)
    assert "--n" not in a
    assert a[a.index("--tingkat") + 1] == "rapat" and a[a.index("--durasi") + 1] == "pendek"
    assert worker.susun_argv("v.mp4", "hasil", {**p, "n_clips": 7})[a.index("--rasio") + 2:][:2] == ["--n", "7"]


def test_pilihan_cocok_dengan_core():
    """Nilai yang boleh dipilih pengguna harus dikenali core.jalankan (bukan hanya diterima API)."""
    from core.pipeline import PRESET_DURASI, TINGKAT_JUMLAH
    assert set(proyek.KEPADATAN) == set(TINGKAT_JUMLAH) and set(proyek.PANJANG_KLIP) == set(PRESET_DURASI)


@pytest.mark.parametrize("n,density,length", [(None, "jarang", "pendek"), (None, "rapat", "panjang"), (5, "sedang", "sedang")])
def test_proyek_dipakai_worker_membawa_pilihan_jumlah_dan_durasi(engine, cfg, n, density, length):
    with engine.begin() as k:
        pid = proyek.buat(k, 1, "t", "v.mp4", "auto", "9:16", n, True, kepadatan=density, panjang=length)
    with engine.connect() as k:
        p = proyek.ambil_untuk_proses(k, pid)
    assert (p["n_clips"], p["clip_density"], p["clip_length"]) == (n, density, length)
    argv = worker.susun_argv("v.mp4", "h", p)
    assert ("--n" in argv) == (n is not None) and ("--tingkat" in argv) == (n is None)


# ---------------------------------------------------------------- pengambilan pekerjaan
def test_ambil_satu_per_satu_menurut_urutan_dan_tidak_ganda(engine, cfg):
    p1, j1 = _proyek(engine, cfg)
    p2, j2 = _proyek(engine, cfg)
    a = _ambil(engine)
    assert a == {"id": j1, "type": "process_project", "payload": {"project_id": p1}}
    assert _satu(engine, "SELECT status, attempts, locked_at FROM job_queue WHERE id = :i", i=j1)[:2] == ("running", 1)
    assert _ambil(engine)["id"] == j2
    assert _ambil(engine) is None


def test_ambil_kalah_balapan_dengan_worker_lain(engine, cfg):
    """Worker lain mengambil pekerjaan itu setelah kita memilihnya tetapi sebelum kita menandainya."""
    _, jid = _proyek(engine, cfg)

    class Sela:
        def __init__(self, k):
            self.k, self.sudah = k, False

        def execute(self, sql, params=None):
            hasil = self.k.execute(sql, params) if params is not None else self.k.execute(sql)
            if not self.sudah:
                self.sudah = True
                self.k.execute(text("UPDATE job_queue SET status = 'running', attempts = 1"))
            return hasil

    with engine.begin() as k:
        assert antrean.ambil(Sela(k)) is None
    assert _satu(engine, "SELECT status, attempts FROM job_queue WHERE id = :i", i=jid) == ("running", 1)


def test_ambil_hanya_jenis_yang_didukung(engine):
    with engine.begin() as k:
        k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('jenis_asing', '{\"clip_id\": 1}')"))
    assert _ambil(engine) is None
    assert _satu(engine, "SELECT status FROM job_queue")[0] == "queued"


def test_ambil_payload_rusak_dikembalikan_sebagai_none(engine):
    with engine.begin() as k:
        k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('process_project', 'bukan json')"))
    assert _ambil(engine)["payload"] is None


# ---------------------------------------------------------------- berhasil
def test_berhasil_proyek_klip_pekerjaan_dan_metrik(engine, cfg):
    pid, jid = _proyek(engine, cfg, ratio="1:1", n=2, bahasa="id", wajah=False)
    pj = Penjalan()
    assert _kerjakan(engine, cfg, pj) is True
    assert _proyek_baris(engine, pid) == ("done", "Selesai", 100, None, 180.0)
    assert _satu(engine, "SELECT status, error FROM job_queue WHERE id = :i", i=jid) == ("done", None)
    # argumen ke core.jalankan
    assert pj.argv[2:4] == ["core.jalankan", str(cfg["folder"] / "projects" / str(pid) / "source.mp4")]
    assert pj.argv[pj.argv.index("--n") + 1] == "2" and pj.argv[pj.argv.index("--rasio") + 1] == "1:1"
    assert pj.argv[-4:] == ["--bahasa", "id", "--mode", "tengah"] and pj.cwd == worker.BASE
    # klip
    with engine.connect() as k:
        baris = k.execute(text("SELECT start_sec, end_sec, score, hook, flow, value_score, trend, title, titles, caption, "
                               "hashtags, ratio, status, file_path, size_bytes FROM clips ORDER BY id")).all()
    assert len(baris) == 2
    b = baris[0]
    assert tuple(b[:8]) == (10.0, 40.0, 71.5, 0.8, 0.6, 0.5, 0.4, "Judul Satu")
    assert json.loads(b.titles) == ["Judul Satu"] and b.caption == "Caption satu\n\n#a #b"
    assert json.loads(b.hashtags) == ["#a", "#b"] and (b.ratio, b.status) == ("1:1", "done")
    assert b.file_path == f"projects/{pid}/hasil/klip_01_1x1.mp4" and b.size_bytes == 1000
    assert baris[1].file_path.endswith("klip_02_1x1.mp4") and json.loads(baris[1].hashtags) == []
    assert "\\" not in b.file_path and not b.file_path.startswith("/")
    # metrik
    with engine.connect() as k:
        metrik = k.execute(text("SELECT job_id, project_id, stage, seconds, video_seconds FROM job_metrics ORDER BY id")).all()
    assert [tuple(m) for m in metrik] == [(jid, pid, "transkripsi", 143.6, 180.0), (jid, pid, "pemilihan_klip", 1.2, 180.0),
                                          (jid, pid, "metadata", 0.1, 180.0), (jid, pid, "render", 137.5, 180.0)]
    # log proses tersimpan di server
    log = (cfg["folder"] / "projects" / str(pid) / "proses.log").read_text(encoding="utf-8")
    assert "=== Langkah 4/4: render ===" in log and "SELESAI dalam" in log


def test_progres_terlihat_di_database_selama_berjalan(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    lihat = []
    pj = Penjalan(pada_baris=lambda b: lihat.append(_proyek_baris(engine, pid)[:3]))
    _kerjakan(engine, cfg, pj)
    unik = list(dict.fromkeys(lihat))
    assert unik == [("processing", "Menyiapkan", 1), ("processing", "Transkripsi", 2), ("processing", "Memilih klip", 47),
                    ("processing", "Judul dan caption", 52), ("processing", "Render klip", 55),
                    ("processing", "Render klip 1/2", 77), ("processing", "Render klip 2/2", 99)]


def test_metadata_hilang_klip_tetap_dibuat_dengan_judul_cadangan(engine, cfg):
    _proyek(engine, cfg)
    assert _kerjakan(engine, cfg, Penjalan(meta=None)) is True
    with engine.connect() as k:
        assert [r[0] for r in k.execute(text("SELECT title FROM clips ORDER BY id")).all()] == ["Klip 1", "Klip 2"]


def test_metadata_lebih_pendek_dari_klip(engine, cfg):
    _proyek(engine, cfg)
    assert _kerjakan(engine, cfg, Penjalan(meta=META[:1])) is True
    with engine.connect() as k:
        assert [r[0] for r in k.execute(text("SELECT title FROM clips ORDER BY id")).all()] == ["Judul Satu", "Klip 2"]


def test_judul_dan_caption_terlalu_panjang_dipotong(engine, cfg):
    _proyek(engine, cfg)
    meta = [{"judul": "j" * 300, "caption": "c" * 900, "hashtag": []}, META[1]]
    _kerjakan(engine, cfg, Penjalan(meta=meta))
    with engine.connect() as k:
        t, c = k.execute(text("SELECT title, caption FROM clips ORDER BY id")).first()
    assert (len(t), len(c)) == (200, 500)


# ---------------------------------------------------------------- gagal
def test_gagal_kode_bukan_nol_memakai_pesan_gagal_dari_keluaran(engine, cfg):
    pid, jid = _proyek(engine, cfg)
    baris = ["=== Langkah 2/4: pemilihan klip ===", "[GAGAL] tidak ada klip terpilih. Coba video yang lebih panjang."]
    assert _kerjakan(engine, cfg, Penjalan(baris=baris, kode=1, klip=None, meta=None, mp4=0)) is False
    pesan = "tidak ada klip terpilih. Coba video yang lebih panjang."
    assert _proyek_baris(engine, pid)[:2] == ("failed", "Gagal") and _proyek_baris(engine, pid)[3] == pesan
    assert _satu(engine, "SELECT status, error FROM job_queue WHERE id = :i", i=jid) == ("failed", pesan)
    assert _satu(engine, "SELECT COUNT(*) FROM clips")[0] == 0 and _satu(engine, "SELECT COUNT(*) FROM job_metrics")[0] == 0


def test_gagal_tanpa_pesan_memakai_kode(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    _kerjakan(engine, cfg, Penjalan(baris=["noise"], kode=3, klip=None, meta=None, mp4=0))
    assert _proyek_baris(engine, pid)[3] == "Pemrosesan gagal (kode 3): noise"


def test_pesan_gagal_tidak_membocorkan_lokasi_server(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    baris = [f"[GAGAL] Berkas video tidak ditemukan: {cfg['folder']}/projects/1/source.mp4 di {worker.BASE}"]
    _kerjakan(engine, cfg, Penjalan(baris=baris, kode=1, klip=None, meta=None, mp4=0))
    pesan = _proyek_baris(engine, pid)[3]
    assert str(cfg["folder"]) not in pesan and str(worker.BASE) not in pesan and pesan.startswith("Berkas video")


def test_galat_tak_terduga_pesan_umum(engine, cfg):
    pid, jid = _proyek(engine, cfg)
    assert _kerjakan(engine, cfg, Penjalan(galat=RuntimeError("rahasia internal /tmp/x"))) is False
    assert _proyek_baris(engine, pid)[3] == "Terjadi kesalahan tak terduga saat memproses video"
    assert (cfg["folder"] / "projects" / str(pid) / "proses.log").is_file()      # log tetap ditulis untuk diagnosis


def test_ctrl_c_tidak_ditelan_dan_pekerjaan_tetap_running(engine, cfg):
    pid, jid = _proyek(engine, cfg)
    with pytest.raises(KeyboardInterrupt):
        _kerjakan(engine, cfg, Penjalan(galat=KeyboardInterrupt()))
    assert _satu(engine, "SELECT status FROM job_queue WHERE id = :i", i=jid)[0] == "running"
    assert _proyek_baris(engine, pid)[0] == "processing"


def test_berkas_klip_hilang_dianggap_gagal(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    assert _kerjakan(engine, cfg, Penjalan(mp4=1)) is False
    assert "Klip ke-2" in _proyek_baris(engine, pid)[3] and _satu(engine, "SELECT COUNT(*) FROM clips")[0] == 0


@pytest.mark.parametrize("klip,potongan", [(None, "tidak ditemukan"), ([], "Tidak ada klip"), ({"a": 1}, "Tidak ada klip"),
                                           ([{"mulai": "x", "akhir": 1}], "Format")])
def test_klip_json_tidak_valid(engine, cfg, klip, potongan):
    pid, _ = _proyek(engine, cfg)
    assert _kerjakan(engine, cfg, Penjalan(klip=klip, mp4=1)) is False
    assert potongan in _proyek_baris(engine, pid)[3]


def test_video_hilang_di_server(engine, cfg):
    pid, _ = _proyek(engine, cfg, sumber=False)
    pj = Penjalan()
    assert _kerjakan(engine, cfg, pj) is False and pj.dipanggil == 0
    assert "tidak ditemukan" in _proyek_baris(engine, pid)[3]


def test_durasi_melebihi_batas_ditolak_sebelum_diproses(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    pj = Penjalan()
    assert _kerjakan(engine, cfg, pj, durasi=lambda p: 25 * 60.0) is False and pj.dipanggil == 0
    baris = _proyek_baris(engine, pid)
    assert baris[0] == "failed" and "25.0 menit" in baris[3] and "20 menit" in baris[3] and baris[4] == 1500.0
    assert _kerjakan_ulang_batas(engine, cfg) is True                        # tepat di batas masih boleh


def test_video_lebih_pendek_dari_durasi_klip_pilihan_ditolak(engine, cfg):
    pid, _ = _proyek(engine, cfg, panjang="sangat_panjang")
    pj = Penjalan()
    assert _kerjakan(engine, cfg, pj, durasi=lambda p: 80.0) is False and pj.dipanggil == 0
    baris = _proyek_baris(engine, pid)
    assert baris[0] == "failed" and "80 detik" in baris[3] and "Sangat panjang" in baris[3] and "90 detik" in baris[3]
    assert "Pilih durasi klip yang lebih pendek" in baris[3]


@pytest.mark.parametrize("panjang,detik,lolos", [
    ("sangat_panjang", 90.0, True), ("sangat_panjang", 89.0, False), ("ekstra_panjang", 120.0, True),
    ("ekstra_panjang", 119.0, False), ("panjang", 59.0, False), ("panjang", 60.0, True),
    ("sedang", 29.0, False), ("pendek", 15.0, True), ("pendek", 14.0, False), ("otomatis", 29.0, False),
])
def test_batas_minimal_tiap_pilihan_durasi(engine, cfg, panjang, detik, lolos):
    _proyek(engine, cfg, panjang=panjang)
    assert _kerjakan(engine, cfg, Penjalan(), durasi=lambda p: detik) is lolos


def test_batas_minimal_sama_dengan_preset_di_core():
    from core.pipeline import PRESET_DURASI
    assert set(proyek.MIN_DETIK_PANJANG) == set(proyek.PANJANG_KLIP) == set(PRESET_DURASI)
    assert {k: v[0] for k, v in PRESET_DURASI.items()} == proyek.MIN_DETIK_PANJANG


def _kerjakan_ulang_batas(engine, cfg):
    _proyek(engine, cfg)
    return _kerjakan(engine, cfg, Penjalan(), durasi=lambda p: 20 * 60.0)


def test_durasi_tidak_terbaca_tetap_diproses(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    assert _kerjakan(engine, cfg, Penjalan(), durasi=lambda p: None) is True
    assert _proyek_baris(engine, pid)[4] is None


def test_proyek_tidak_ada_dan_isi_pekerjaan_tidak_valid(engine, cfg):
    with engine.begin() as k:
        k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('process_project', '{\"project_id\": 99}')"))
        k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('process_project', 'rusak')"))
        k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('process_project', '{\"project_id\": true}')"))
    for _ in range(3):
        assert _kerjakan(engine, cfg, Penjalan()) is False
    with engine.connect() as k:
        hasil = [r[0] for r in k.execute(text("SELECT error FROM job_queue ORDER BY id")).all()]
    assert hasil == ["Proyek tidak ditemukan", "Isi pekerjaan tidak valid", "Isi pekerjaan tidak valid"]


def test_proyek_yang_sudah_selesai_tidak_diproses_ulang(engine, cfg):
    pid, jid = _proyek(engine, cfg)
    with engine.begin() as k:
        proyek.ubah(k, pid, status="done", stage="Selesai", progress=100)
    pj = Penjalan()
    assert _kerjakan(engine, cfg, pj) is True and pj.dipanggil == 0
    assert _satu(engine, "SELECT status FROM job_queue WHERE id = :i", i=jid)[0] == "done"


# ---------------------------------------------------------------- pemulihan dan perulangan
def test_pemulihan_pekerjaan_terputus(engine, cfg):
    p1, j1 = _proyek(engine, cfg)
    p2, j2 = _proyek(engine, cfg)
    with engine.begin() as k:
        k.execute(text("UPDATE job_queue SET status = 'running', attempts = 1 WHERE id = :i"), {"i": j1})
        k.execute(text("UPDATE job_queue SET status = 'running', attempts = 3 WHERE id = :i"), {"i": j2})
        proyek.ubah(k, p1, status="processing", stage="Render klip 1/2", progress=77)
        proyek.ubah(k, p2, status="processing", stage="Transkripsi", progress=2)
    assert worker.pulihkan(engine) == [(j1, p1, True), (j2, p2, False)]
    assert _satu(engine, "SELECT status FROM job_queue WHERE id = :i", i=j1)[0] == "queued"
    assert _proyek_baris(engine, p1)[:3] == ("queued", "Antre", 0)
    assert _satu(engine, "SELECT status, error FROM job_queue WHERE id = :i", i=j2) == ("failed", "Pemrosesan terhenti berulang kali")
    assert _proyek_baris(engine, p2)[:2] == ("failed", "Gagal")


def test_perulangan_sekali_mengerjakan_semua_menurut_urutan(engine, cfg):
    p1, _ = _proyek(engine, cfg)
    p2, _ = _proyek(engine, cfg, sumber=False)                                # yang kedua gagal
    p3, _ = _proyek(engine, cfg)
    n = worker.jalankan_worker(engine, cfg, PROSES_CFG, runner=Penjalan(), durasi=lambda p: 60.0, sekali=True)
    assert n == 3
    assert [_proyek_baris(engine, p)[0] for p in (p1, p2, p3)] == ["done", "failed", "done"]
    assert worker.jalankan_worker(engine, cfg, PROSES_CFG, runner=Penjalan(), sekali=True) == 0


def test_perulangan_menunggu_saat_kosong_dan_bisa_dihentikan(engine, cfg):
    tidur, hitung = [], {"n": 0}

    def berhenti():
        hitung["n"] += 1
        return hitung["n"] > 3

    worker.jalankan_worker(engine, cfg, PROSES_CFG, runner=Penjalan(), jeda=1.5, tidur=tidur.append, berhenti=berhenti)
    assert tidur == [1.5, 1.5, 1.5]


def test_perulangan_bertahan_saat_database_putus_sebentar(engine, cfg, monkeypatch):
    from sqlalchemy.exc import OperationalError
    _proyek(engine, cfg)
    asli, panggilan, tidur = antrean.ambil, {"n": 0}, []

    def goyah(k):
        panggilan["n"] += 1
        if panggilan["n"] == 1:
            raise OperationalError("SELECT", {}, Exception("putus"))
        return asli(k)

    monkeypatch.setattr(antrean, "ambil", goyah)
    n = worker.jalankan_worker(engine, cfg, PROSES_CFG, runner=Penjalan(), durasi=lambda p: 60.0,
                               tidur=tidur.append, berhenti=lambda: panggilan["n"] >= 3)
    assert n == 1 and tidur == [10.0, 2.0]          # menunggu 5x jeda saat database putus, lalu jeda biasa


# ---------------------------------------------------------------- CLI dan pengaturan
def test_main_sekali(engine, cfg, capsys, monkeypatch):
    pid, _ = _proyek(engine, cfg)
    monkeypatch.setattr(worker, "jalankan_proses", Penjalan())
    monkeypatch.setattr(worker, "durasi_video", lambda p: 60.0)
    monkeypatch.setattr(worker, "jalankan_worker", lambda *a, **k: 7)
    ctx = konteks.Konteks(engine=engine, unggah=cfg)
    assert worker.main(["--sekali"], konteks=ctx) == 0
    assert "7 pekerjaan" in capsys.readouterr().out


def test_main_konfigurasi_salah(monkeypatch, capsys):
    monkeypatch.setenv("MAX_DURATION_MIN", "abc")
    monkeypatch.setenv("DB_PORT", "3306")
    ctx = konteks.Konteks(engine=object(), unggah={"folder": Path("x"), "maks_bytes": 1}, muat_env=lambda: None)
    assert worker.main(["--sekali"], konteks=ctx) == 1
    assert "MAX_DURATION_MIN" in capsys.readouterr().out


def test_main_database_mati(engine, cfg, capsys):
    class Mati:
        def begin(self):
            from sqlalchemy.exc import OperationalError
            raise OperationalError("x", {}, Exception("rahasia"))

    ctx = konteks.Konteks(engine=Mati(), unggah=cfg)
    assert worker.main(["--sekali"], konteks=ctx) == 1
    out = capsys.readouterr().out
    assert "XAMPP" in out and "rahasia" not in out


def test_pengaturan_proses():
    assert config.pengaturan_proses({}) == {"maks_durasi_detik": None}                       # bawaan: tanpa batas
    for kosong in ("", "  ", "0", "0.0"):
        assert config.pengaturan_proses({"MAX_DURATION_MIN": kosong}) == {"maks_durasi_detik": None}
    assert config.pengaturan_proses({"MAX_DURATION_MIN": "0.5"}) == {"maks_durasi_detik": 30.0}
    assert config.pengaturan_proses({"MAX_DURATION_MIN": "20"}) == {"maks_durasi_detik": 1200.0}
    for salah in ("abc", "-3"):
        with pytest.raises(ValueError, match="MAX_DURATION_MIN"):
            config.pengaturan_proses({"MAX_DURATION_MIN": salah})


def test_ubah_hanya_kolom_yang_diizinkan(engine):
    with engine.begin() as k:
        with pytest.raises(ValueError, match="user_id"):
            proyek.ubah(k, 1, user_id=5)
        with pytest.raises(ValueError):
            proyek.ubah(k, 1)


# ---------------------------------------------------------------- runner nyata (proses anak sungguhan)
def test_jalankan_proses_nyata_membaca_baris_dan_kode_keluar(tmp_path):
    skrip = tmp_path / "anak.py"
    skrip.write_text("import sys\nprint('baris satu')\nprint('=== Langkah 1/4: transkripsi ===', flush=True)\n"
                     "print('kesalahan', file=sys.stderr)\nsys.exit(4)\n", encoding="utf-8")
    baris = []
    kode = worker.jalankan_proses([worker.sys.executable, str(skrip)], tmp_path, baris.append)
    assert kode == 4 and baris[0] == "baris satu" and "=== Langkah 1/4: transkripsi ===" in baris and "kesalahan" in baris


# ---------------------------------------------------------------- kolom yang dipakai ada di schema.sql
def _kolom(sql, tabel):
    blok = re.search(rf"CREATE TABLE IF NOT EXISTS {tabel} \((.*?)\) ENGINE", sql, re.S).group(1)
    return set(re.findall(r"^\s{2}(\w+)\s", blok, re.M)), blok


def test_kolom_yang_dipakai_ada_di_schema_sql():
    sql = (Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
    assert {"id", "type", "payload", "status", "attempts", "error", "locked_at"} <= _kolom(sql, "job_queue")[0]
    assert {"status", "stage", "progress", "error", "duration_sec", "n_clips", "clip_density", "clip_length", "ratio",
            "language", "face_tracking"} <= _kolom(sql, "projects")[0]
    assert {"project_id", "start_sec", "end_sec", "score", "hook", "flow", "value_score", "trend", "title", "titles",
            "caption", "hashtags", "ratio", "status", "file_path", "size_bytes"} <= _kolom(sql, "clips")[0]
    assert {"job_id", "project_id", "stage", "seconds", "video_seconds"} <= _kolom(sql, "job_metrics")[0]
    _, blok_klip = _kolom(sql, "clips")
    assert "'done'" in blok_klip
    assert "'failed'" in _kolom(sql, "projects")[1] and "'process_project'" in _kolom(sql, "job_queue")[1]


# ---------------------------------------------------------------- tautan YouTube
URL = "https://www.youtube.com/watch?v=abc123XYZ_-"


class PenjalanYoutube:
    """Pengganti yt-dlp (dua pemanggilan: baca info, lalu unduh) sekaligus core.jalankan."""

    def __init__(self, info=("600\tJudul Dari YouTube",), kode_info=0, kode_unduh=0, buat_berkas=True,
                 baris_unduh=("[download]   0.0% of 10.00MiB", "[download]  50.0% of 10.00MiB", "[download] 100.0% of 10.00MiB"),
                 sisa=None, pada_baris=None):
        self.info, self.kode_info, self.kode_unduh, self.buat_berkas = info, kode_info, kode_unduh, buat_berkas
        self.baris_unduh, self.sisa, self.pada_baris = baris_unduh, sisa, pada_baris
        self.panggilan = []
        self.hilir = Penjalan()

    def __call__(self, argv, cwd, kirim):
        if "yt_dlp" not in argv:
            self.panggilan.append("jalankan")
            return self.hilir(argv, cwd, kirim)
        if "--skip-download" in argv:
            self.panggilan.append(("info", argv))
            for b in self.info:
                kirim(b)
            return self.kode_info
        self.panggilan.append(("unduh", argv))
        folder = Path(argv[argv.index("-o") + 1]).parent
        for b in self.baris_unduh:
            kirim(b)
            if self.pada_baris:
                self.pada_baris(b)
        if self.sisa:
            (folder / self.sisa).write_bytes(b"sebagian")
        if self.kode_unduh == 0 and self.buat_berkas:
            (folder / "source.mp4").write_bytes(b"video-hasil-unduh")
        return self.kode_unduh


def _proyek_link(engine, cfg, judul="", n=2):
    with engine.begin() as k:
        pid = proyek.buat(k, 1, judul, URL, "auto", "9:16", n, True, source_type="link")
        jid = proyek.antrekan(k, pid)
    (cfg["folder"] / "projects" / str(pid)).mkdir(parents=True)
    return pid, jid


def _judul(engine, pid):
    return _satu(engine, "SELECT title FROM projects WHERE id = :i", i=pid)[0]


def test_tautan_berhasil_diunduh_lalu_diproses(engine, cfg):
    pid, jid = _proyek_link(engine, cfg)
    pj = PenjalanYoutube()
    assert _kerjakan(engine, cfg, pj) is True
    assert [p if isinstance(p, str) else p[0] for p in pj.panggilan] == ["info", "unduh", "jalankan"]
    assert _proyek_baris(engine, pid) == ("done", "Selesai", 100, None, 180.0)       # durasi dari video yang terbaca
    assert _judul(engine, pid) == "Judul Dari YouTube"
    # argumen aman: tautan setelah "--", tanpa shell, ada batas ukuran dan format
    _, argv = pj.panggilan[1]
    assert argv[argv.index("--") + 1:] == [URL] and "--no-playlist" in argv and "--merge-output-format" in argv
    assert argv[argv.index("--max-filesize") + 1] == str(cfg["maks_bytes"]) and argv[argv.index("-f") + 1] == worker.FORMAT_UNDUH
    _, info = pj.panggilan[0]
    assert info[info.index("--") + 1:] == [URL] and "--skip-download" in info
    # video hasil unduh dipakai untuk core.jalankan
    assert Path(pj.hilir.argv[pj.hilir.argv.index("core.jalankan") + 1]).name == "source.mp4"
    assert _satu(engine, "SELECT COUNT(*) FROM clips")[0] == 2


def test_judul_dari_pengguna_tidak_ditimpa_judul_youtube(engine, cfg):
    pid, _ = _proyek_link(engine, cfg, judul="Judul Saya")
    _kerjakan(engine, cfg, PenjalanYoutube())
    assert _judul(engine, pid) == "Judul Saya"


def test_progres_unduhan_1_sampai_10_lalu_lanjut(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    lihat = []
    pj = PenjalanYoutube(pada_baris=lambda b: lihat.append(_proyek_baris(engine, pid)[1:3]))
    pj.hilir = Penjalan(pada_baris=lambda b: lihat.append(_proyek_baris(engine, pid)[1:3]))
    _kerjakan(engine, cfg, pj)
    unik = list(dict.fromkeys(lihat))
    assert unik[:4] == [("Mengunduh video", 1), ("Mengunduh video", 5), ("Mengunduh video", 10), ("Menyiapkan", 10)]
    assert unik[4] == ("Transkripsi", 10)                                          # tidak turun ke 2
    assert unik[-1] == ("Render klip 2/2", 99) and [p for _, p in unik] == sorted(p for _, p in unik)


def test_durasi_youtube_terlalu_panjang_ditolak_sebelum_unduh(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    pj = PenjalanYoutube(info=("1800\tVideo Panjang",))
    assert _kerjakan(engine, cfg, pj) is False
    assert [p[0] for p in pj.panggilan] == ["info"]
    baris = _proyek_baris(engine, pid)
    assert baris[0] == "failed" and "30.0 menit" in baris[3] and baris[4] == 1800.0
    assert _judul(engine, pid) == "Video Panjang"


def test_durasi_tidak_diketahui_dicek_setelah_unduh(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    pj = PenjalanYoutube(info=("NA\tSiaran Langsung",))
    assert _kerjakan(engine, cfg, pj, durasi=lambda p: 3000.0) is False
    assert [p if isinstance(p, str) else p[0] for p in pj.panggilan] == ["info", "unduh"]
    assert "50.0 menit" in _proyek_baris(engine, pid)[3]


def test_gagal_membaca_info_menampilkan_alasan_youtube(engine, cfg):
    pid, jid = _proyek_link(engine, cfg)
    pj = PenjalanYoutube(info=("WARNING: x", "ERROR: [youtube] abc: Video unavailable"), kode_info=1)
    assert _kerjakan(engine, cfg, pj) is False
    assert _proyek_baris(engine, pid)[3] == "Gagal membaca video dari YouTube: [youtube] abc: Video unavailable"
    assert [p[0] for p in pj.panggilan] == ["info"]


def test_gagal_unduh_membersihkan_sisa_dan_melapor(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    pj = PenjalanYoutube(kode_unduh=1, sisa="source.mp4.part", baris_unduh=("[download]  30.0% of 10MiB", "ERROR: unable to download"))
    assert _kerjakan(engine, cfg, pj) is False
    assert _proyek_baris(engine, pid)[3] == "Gagal mengunduh dari YouTube: unable to download"
    assert list((cfg["folder"] / "projects" / str(pid)).glob("source.*")) == []
    assert "jalankan" not in pj.panggilan


def test_unduh_berhasil_tetapi_berkas_tidak_ada(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    assert _kerjakan(engine, cfg, PenjalanYoutube(buat_berkas=False)) is False
    assert "berkas video tidak ditemukan" in _proyek_baris(engine, pid)[3]


def test_unduhan_setengah_jalan_tidak_dianggap_selesai(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    assert _kerjakan(engine, cfg, PenjalanYoutube(buat_berkas=False, sisa="source.f137.mp4.part")) is False
    assert list((cfg["folder"] / "projects" / str(pid)).glob("source.*")) == []


def test_ctrl_c_saat_unduh_membersihkan_sisa_dan_tidak_ditelan(engine, cfg):
    pid, jid = _proyek_link(engine, cfg)

    class Putus(PenjalanYoutube):
        def __call__(self, argv, cwd, kirim):
            if "--skip-download" not in argv and "yt_dlp" in argv:
                (Path(argv[argv.index("-o") + 1]).parent / "source.mp4.part").write_bytes(b"x")
                raise KeyboardInterrupt
            return super().__call__(argv, cwd, kirim)

    with pytest.raises(KeyboardInterrupt):
        _kerjakan(engine, cfg, Putus())
    assert list((cfg["folder"] / "projects" / str(pid)).glob("source.*")) == []
    assert _satu(engine, "SELECT status FROM job_queue WHERE id = :i", i=jid)[0] == "running"


def test_percobaan_ulang_memakai_video_yang_sudah_diunduh(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    (cfg["folder"] / "projects" / str(pid) / "source.mp4").write_bytes(b"sudah ada")
    pj = PenjalanYoutube()
    assert _kerjakan(engine, cfg, pj) is True
    assert pj.panggilan == ["jalankan"]                                           # tidak mengunduh lagi
    assert _proyek_baris(engine, pid)[:3] == ("done", "Selesai", 100)


def test_judul_youtube_terlalu_panjang_dipotong_dan_tab_di_judul(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    _kerjakan(engine, cfg, PenjalanYoutube(info=("600\t" + "j" * 400,)))
    assert len(_judul(engine, pid)) == 200
    pid2, _ = _proyek_link(engine, cfg)
    _kerjakan(engine, cfg, PenjalanYoutube(info=("600\tJudul\tdengan tab",)))
    assert _judul(engine, pid2) == "Judul\tdengan tab"


def test_proyek_upload_tanpa_berkas_tetap_gagal_bukan_diunduh(engine, cfg):
    pid, _ = _proyek(engine, cfg, sumber=False)
    pj = PenjalanYoutube()
    assert _kerjakan(engine, cfg, pj) is False and pj.panggilan == []


def test_urai_progres_unduhan():
    assert worker._POLA_UNDUH.match("[download]  45.3% of ~ 10.00MiB at 1.0MiB/s").group(1) == "45.3"
    assert worker._POLA_UNDUH.match("[download] 100% of 10.00MiB").group(1) == "100"
    assert worker._POLA_UNDUH.match("[download] Destination: x.mp4") is None
    assert worker._pesan_ytdlp(["a", "ERROR: satu", "ERROR: dua", "b"]) == "dua" and worker._pesan_ytdlp(["x"]) == ""


# ---------------------------------------------------------------- tanpa batas durasi
TANPA_BATAS = {"maks_durasi_detik": None}


def test_tanpa_batas_video_sangat_panjang_tetap_diproses(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    job = _ambil(engine)
    assert worker.kerjakan(engine, job, cfg, TANPA_BATAS, runner=Penjalan(), durasi=lambda p: 6 * 3600.0) is True
    assert _proyek_baris(engine, pid)[:3] == ("done", "Selesai", 100)


def test_tanpa_batas_tautan_youtube_panjang_tetap_diunduh_dan_diproses(engine, cfg):
    pid, _ = _proyek_link(engine, cfg)
    pj = PenjalanYoutube(info=("7200\tKuliah Dua Jam",))
    job = _ambil(engine)
    assert worker.kerjakan(engine, job, cfg, TANPA_BATAS, runner=pj, durasi=lambda p: 7200.0) is True
    assert [p if isinstance(p, str) else p[0] for p in pj.panggilan] == ["info", "unduh", "jalankan"]
    assert _proyek_baris(engine, pid)[:3] == ("done", "Selesai", 100)


def test_batas_tetap_berlaku_bila_diisi(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    job = _ambil(engine)
    assert worker.kerjakan(engine, job, cfg, {"maks_durasi_detik": 60.0}, runner=Penjalan(), durasi=lambda p: 61.0) is False
    assert "melebihi batas 1 menit" in _proyek_baris(engine, pid)[3]


# ---------------------------------------------------------------- pesan bila proses berhenti tanpa [GAGAL]
def test_kode_keluar_menyertakan_baris_terakhir_keluaran(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    pj = Penjalan(baris=["=== Langkah 1/4: transkripsi ===", "usage: jalankan [-h] video",
                          "jalankan: error: unrecognized arguments: --tingkat sedang", ""], kode=2, klip=None, meta=None, mp4=0)
    assert _kerjakan(engine, cfg, pj) is False
    assert _proyek_baris(engine, pid)[3] == "Pemrosesan gagal (kode 2): jalankan: error: unrecognized arguments: --tingkat sedang"


def test_kode_keluar_tanpa_keluaran_tetap_ada_pesan(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    assert _kerjakan(engine, cfg, Penjalan(baris=[], kode=3, klip=None, meta=None, mp4=0)) is False
    assert _proyek_baris(engine, pid)[3] == "Pemrosesan gagal (kode 3)"


def test_kode_keluar_membuang_lokasi_server_dan_memotong(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    lokasi = str(cfg["folder"] / "projects" / "1" / "source.mp4")
    pj = Penjalan(baris=[f"FileNotFoundError: {lokasi} " + "x" * 500], kode=1, klip=None, meta=None, mp4=0)
    _kerjakan(engine, cfg, pj)
    pesan = _proyek_baris(engine, pid)[3]
    assert str(cfg["folder"]) not in pesan and "storage" in pesan and len(pesan) <= len("Pemrosesan gagal (kode 1): ") + 300


def test_baris_gagal_tetap_didahulukan_atas_baris_terakhir(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    pj = Penjalan(baris=["[GAGAL] Tidak ada kata terdeteksi", "Traceback ... lain"], kode=1, klip=None, meta=None, mp4=0)
    _kerjakan(engine, cfg, pj)
    assert _proyek_baris(engine, pid)[3] == "Tidak ada kata terdeteksi"


# ---------------------------------------------------------------- render ulang satu klip
def _proyek_selesai_dengan_klip(engine, cfg, *, wajah=True):
    """Proyek selesai berisi satu klip jadi (file lama berisi b'lama') dan video sumber."""
    pid, _ = _proyek(engine, cfg, n=1, wajah=wajah)
    with engine.begin() as k:
        k.execute(text("DELETE FROM job_queue"))
        proyek.ubah(k, pid, status="done", stage="Selesai", progress=100)
        proyek.simpan_klip(k, pid, "9:16", [{"start": 10.0, "end": 40.0, "score": 70.0, "hook": .5, "flow": .5, "value": .5,
                                             "trend": .5, "title": "J", "caption": "C", "hashtags": [],
                                             "file_path": f"projects/{pid}/hasil/klip_01_9x16.mp4", "size_bytes": 4}])
    hasil = cfg["folder"] / "projects" / str(pid) / "hasil"
    hasil.mkdir(parents=True, exist_ok=True)
    (hasil / "klip_01_9x16.mp4").write_bytes(b"lama")
    cid = _satu(engine, "SELECT id FROM clips WHERE project_id = :p", p=pid)[0]
    return pid, cid, hasil


def _jadwalkan(engine, pid, cid, mulai=12.0, akhir=50.0):
    with engine.begin() as k:
        proyek.jadwalkan_render_ulang(k, pid, cid, mulai, akhir)


class PenjalanKlip:
    def __init__(self, kode=0, tulis=True, baris=()):
        self.kode, self.tulis, self.baris, self.argv = kode, tulis, baris, None

    def __call__(self, argv, cwd, kirim):
        self.argv = argv
        for b in self.baris:
            kirim(b)
        if self.tulis and self.kode == 0:
            folder = Path(argv[argv.index("--folder") + 1])
            (folder / "klip_01_9x16.mp4").write_bytes(b"baru-baru")
        return self.kode


def test_render_ulang_mengganti_berkas_dan_batas_klip_tanpa_menyentuh_proyek(engine, cfg):
    pid, cid, hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _jadwalkan(engine, pid, cid, 12.0, 50.0)
    assert _satu(engine, "SELECT status FROM clips WHERE id = :i", i=cid)[0] == "rendering"
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert (hasil / "klip_01_9x16.mp4").read_bytes() == b"baru-baru"
    assert _satu(engine, "SELECT status, start_sec, end_sec, size_bytes FROM clips WHERE id = :i", i=cid) == ("done", 12.0, 50.0, 9)
    assert _proyek_baris(engine, pid)[0] == "done"
    assert _satu(engine, "SELECT status FROM job_queue")[0] == "done"
    assert not list(hasil.glob("_ulang_*"))                                                   # folder sementara dibersihkan
    assert pj.argv[1:3] == ["-m", "core.render"] and "--mode" not in pj.argv
    assert not Path(pj.argv[4]).exists()                                                      # klip.json sementara sudah hilang


def test_render_ulang_tanpa_wajah_memakai_mode_tengah_dan_subtitle_bila_ada(engine, cfg):
    pid, cid, hasil = _proyek_selesai_dengan_klip(engine, cfg, wajah=False)
    (hasil / "kata.json").write_text("[]", encoding="utf-8")
    _jadwalkan(engine, pid, cid)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert pj.argv[pj.argv.index("--mode") + 1] == "tengah" and pj.argv[pj.argv.index("--kata") + 1].endswith("kata.json")


def test_render_ulang_gagal_berkas_lama_utuh_klip_failed_proyek_tetap_selesai(engine, cfg):
    pid, cid, hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _jadwalkan(engine, pid, cid)
    assert not _kerjakan(engine, cfg, PenjalanKlip(kode=1, baris=["[GAGAL] ffmpeg rusak"]))
    assert (hasil / "klip_01_9x16.mp4").read_bytes() == b"lama"
    assert _satu(engine, "SELECT status, start_sec, end_sec FROM clips WHERE id = :i", i=cid) == ("failed", 10.0, 40.0)
    assert _proyek_baris(engine, pid)[0] == "done"
    status, galat = _satu(engine, "SELECT status, error FROM job_queue")
    assert status == "failed" and "ffmpeg rusak" in galat


def test_render_ulang_video_sumber_hilang_dan_berkas_tidak_dihasilkan(engine, cfg):
    pid, cid, hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _jadwalkan(engine, pid, cid)
    assert not _kerjakan(engine, cfg, PenjalanKlip(tulis=False))
    assert "tidak menghasilkan" in _satu(engine, "SELECT error FROM job_queue ORDER BY id DESC LIMIT 1")[0]
    (cfg["folder"] / "projects" / str(pid) / "source.mp4").unlink()
    _jadwalkan(engine, pid, cid)
    assert not _kerjakan(engine, cfg, PenjalanKlip())
    assert "sumber" in _satu(engine, "SELECT error FROM job_queue WHERE status = 'failed' ORDER BY id DESC LIMIT 1")[0]


def test_render_ulang_isi_pekerjaan_tidak_valid_dan_pemulihan(engine, cfg):
    pid, cid, hasil = _proyek_selesai_dengan_klip(engine, cfg)
    with engine.begin() as k:
        k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('render_clip', :p)"),
                  {"p": json.dumps({"project_id": pid, "clip_id": cid, "mulai": 30, "akhir": 10})})
    assert not _kerjakan(engine, cfg, PenjalanKlip())
    # pemulihan: pekerjaan render_clip yang terputus diulang tanpa mengubah status proyek; setelah 3 kali, klip failed
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i"), {"i": cid})
        k.execute(text("INSERT INTO job_queue (type, payload, status, attempts) VALUES ('render_clip', :p, 'running', 3)"),
                  {"p": json.dumps({"project_id": pid, "clip_id": cid, "mulai": 1, "akhir": 20})})
    worker.pulihkan(engine)
    assert _satu(engine, "SELECT status FROM clips WHERE id = :i", i=cid)[0] == "failed"
    assert _proyek_baris(engine, pid)[0] == "done"


# ---------------------------------------------------------------- batal render ulang
def _batalkan(engine, pid, cid):
    with engine.begin() as k:
        return proyek.batalkan_render_ulang(k, pid, cid)


def test_batal_sebelum_diambil_worker_klip_kembali_done_dan_pekerjaan_tidak_dikerjakan(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _jadwalkan(engine, pid, cid)
    klip = _batalkan(engine, pid, cid)
    assert klip["status"] == "done"
    assert _ambil(engine) is None
    assert _satu(engine, "SELECT status, error FROM job_queue")[:] == ("failed", "dibatalkan")
    assert (folder_hasil / "klip_01_9x16.mp4").read_bytes() == b"lama"


def test_batal_saat_worker_sudah_mengerjakan_berkas_lama_utuh_dan_status_tetap_done(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _jadwalkan(engine, pid, cid)
    job = _ambil(engine)

    class PenjalanDibatalkan(PenjalanKlip):
        def __call__(self, argv, cwd, kirim):
            _batalkan(engine, pid, cid)           # pengguna menekan batal selagi render berjalan
            return super().__call__(argv, cwd, kirim)

    assert worker.kerjakan(engine, job, cfg, PROSES_CFG, runner=PenjalanDibatalkan()) is False
    assert (folder_hasil / "klip_01_9x16.mp4").read_bytes() == b"lama"
    assert _satu(engine, "SELECT status, start_sec FROM clips WHERE id = :i", i=cid)[0] == "done"
    assert _satu(engine, "SELECT status, error FROM job_queue")[:] == ("failed", "dibatalkan")
    assert not (cfg["folder"] / "projects" / str(pid) / "hasil" / f"_ulang_{cid}").exists()
    assert _satu(engine, "SELECT status FROM projects WHERE id = :i", i=pid)[0] == "done"


def test_batal_klip_yang_tidak_sedang_dirender_ditolak(engine, cfg):
    pid, cid, _ = _proyek_selesai_dengan_klip(engine, cfg)
    with pytest.raises(RuntimeError):
        _batalkan(engine, pid, cid)
    with pytest.raises(LookupError):
        _batalkan(engine, pid, 9999)


def test_batal_tidak_menyentuh_pekerjaan_klip_lain(engine, cfg):
    pid, cid, _ = _proyek_selesai_dengan_klip(engine, cfg)
    with engine.begin() as k:
        k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('render_clip', :p)"),
                  {"p": json.dumps({"project_id": pid, "clip_id": cid + 1, "mulai": 1.0, "akhir": 9.0})})
    _jadwalkan(engine, pid, cid)
    _batalkan(engine, pid, cid)
    assert _satu(engine, "SELECT COUNT(*) FROM job_queue WHERE status = 'queued'")[0] == 1


def test_jalankan_proses_nyata_berhenti_saat_dibatalkan(tmp_path):
    import time as waktu
    skrip = tmp_path / "lama.py"
    skrip.write_text("import time\nprint('mulai', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
    mulai = waktu.monotonic()
    kode = worker.jalankan_proses([worker.sys.executable, str(skrip)], tmp_path, lambda b: None, dibatalkan=lambda: True)
    assert kode != 0 and waktu.monotonic() - mulai < 10


def test_kemajuan_render_ulang_ditulis_ke_folder_sementara_dan_dibersihkan(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _jadwalkan(engine, pid, cid)
    terbaca = []

    class PenjalanLapor(PenjalanKlip):
        def __call__(self, argv, cwd, kirim):
            kirim("[PROGRES] 0 Menganalisis suara")
            kirim("[PROGRES] 37 Merender video")
            terbaca.append(json.loads((folder_hasil / f"_ulang_{cid}" / "progres.json").read_text(encoding="utf-8")))
            return super().__call__(argv, cwd, kirim)

    pj = PenjalanLapor(baris=("baris lain",))
    assert _kerjakan(engine, cfg, pj)
    assert terbaca[0]["persen"] == 37 and terbaca[0]["tahap"] == "Merender video" and terbaca[0]["berjalan"] >= 0
    assert not (folder_hasil / f"_ulang_{cid}").exists()


def test_baris_kemajuan_tidak_masuk_pesan_kegagalan(engine, cfg):
    pid, cid, _ = _proyek_selesai_dengan_klip(engine, cfg)
    _jadwalkan(engine, pid, cid)

    class Gagal(PenjalanKlip):
        def __call__(self, argv, cwd, kirim):
            kirim("[PROGRES] 12 Melacak wajah dan pembicara")
            kirim("Traceback: sesuatu rusak")
            return 3

    assert _kerjakan(engine, cfg, Gagal()) is False
    galat = _satu(engine, "SELECT error FROM job_queue")[0]
    assert "PROGRES" not in galat


# ---------------------------------------------------------------- batal pemrosesan proyek penuh
def _batalkan_proyek(engine, pid):
    with engine.begin() as k:
        return proyek.batalkan_proyek(k, pid, 1)


def test_batal_proyek_sebelum_diambil_worker(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    hasil = _batalkan_proyek(engine, pid)
    assert (hasil["status"], hasil["stage"]) == ("failed", "Dibatalkan")
    assert _ambil(engine) is None


def test_batal_proyek_saat_berjalan_status_tidak_ditimpa_dan_klip_tidak_disimpan(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    pj = Penjalan(pada_baris=None)
    job = _ambil(engine)

    class PenjalanDibatalkan(Penjalan):
        def __call__(self, argv, cwd, kirim):
            kirim("=== Langkah 1/4: transkripsi ===")
            _batalkan_proyek(engine, pid)                    # pengguna menekan batal di tengah jalan
            kirim("=== Langkah 2/4: pemilihan klip ===")      # pembaruan sesudahnya tidak boleh menimpa status
            return 0

    assert worker.kerjakan(engine, job, cfg, PROSES_CFG, runner=PenjalanDibatalkan(), durasi=lambda p: 180.0) is False
    baris = _proyek_baris(engine, pid)
    assert baris[0] == "failed" and baris[1] == "Dibatalkan" and baris[3] == "Dibatalkan oleh pengguna"
    assert _satu(engine, "SELECT status, error FROM job_queue")[:] == ("failed", "dibatalkan")
    assert _satu(engine, "SELECT COUNT(*) FROM clips")[0] == 0


def test_batal_proyek_proses_dimatikan_kode_nonzero_tidak_dianggap_gagal_biasa(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    job = _ambil(engine)

    class Dimatikan(Penjalan):
        def __call__(self, argv, cwd, kirim):
            _batalkan_proyek(engine, pid)
            return -9                                         # seperti proses yang di-kill

    assert worker.kerjakan(engine, job, cfg, PROSES_CFG, runner=Dimatikan(), durasi=lambda p: 180.0) is False
    assert _proyek_baris(engine, pid)[1] == "Dibatalkan"
    assert "kode" not in (_proyek_baris(engine, pid)[3] or "")


def test_batal_proyek_yang_tidak_berjalan_atau_bukan_milik(engine, cfg):
    pid, _ = _proyek(engine, cfg)
    with engine.begin() as k:
        k.execute(text("UPDATE projects SET status = 'done' WHERE id = :i"), {"i": pid})
    with pytest.raises(RuntimeError):
        _batalkan_proyek(engine, pid)
    with pytest.raises(LookupError):
        _batalkan_proyek(engine, 9999)
    with engine.begin() as k, pytest.raises(LookupError):
        proyek.batalkan_proyek(k, pid, 2)                    # pengguna lain


# ---------------------------------------------------------------- gaya subtitle dan koreksi kata saat render ulang
def _tulis_kata(folder_hasil, kata):
    (folder_hasil / "kata.json").write_text(json.dumps(kata), encoding="utf-8")


KATA = [{"w": "halo", "s": 12.0, "e": 12.4}, {"w": "dunia", "s": 12.5, "e": 13.0}, {"w": "ini", "s": 13.1, "e": 13.4}]


def test_terapkan_koreksi_hanya_mengubah_kata_yang_cocok_dan_tidak_memutasi_asli():
    asli = [dict(k) for k in KATA]
    hasil = worker.terapkan_koreksi(KATA, [{"s": 12.5, "w": "Duniaku"}, {"s": 13.1, "w": ""}, {"s": 99.0, "w": "tak ada"}])
    assert [k["w"] for k in hasil] == ["halo", "Duniaku", ""] and KATA == asli


def test_render_ulang_memakai_gaya_dan_koreksi_klip_tanpa_mengubah_kata_json(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _tulis_kata(folder_hasil, KATA)
    with engine.begin() as k:
        proyek.simpan_subtitle(k, pid, cid, {"gaya": "sorot", "posisi": "tengah", "ukuran": "besar", "aktif": True},
                               [{"s": 12.5, "w": "Duniaku"}])
    _jadwalkan(engine, pid, cid)
    diperiksa = []

    class Periksa(PenjalanKlip):
        def __call__(self, argv, cwd, kirim):
            berkas = Path(argv[argv.index("--kata") + 1])
            diperiksa.append(json.loads(berkas.read_text(encoding="utf-8")))
            return super().__call__(argv, cwd, kirim)

    pj = Periksa()
    assert _kerjakan(engine, cfg, pj)
    a = pj.argv
    assert a[a.index("--gaya-teks") + 1] == "sorot" and a[a.index("--posisi-teks") + 1] == "tengah"
    assert a[a.index("--ukuran-teks") + 1] == "besar" and "--tanpa-subtitle" not in a
    assert [k["w"] for k in diperiksa[0]] == ["halo", "Duniaku", "ini"]
    assert json.loads((folder_hasil / "kata.json").read_text(encoding="utf-8")) == KATA          # transkrip proyek utuh


def test_render_ulang_subtitle_dimatikan_dan_tanpa_kata_json(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _tulis_kata(folder_hasil, KATA)
    with engine.begin() as k:
        proyek.simpan_subtitle(k, pid, cid, {"aktif": False})
    _jadwalkan(engine, pid, cid)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert "--tanpa-subtitle" in pj.argv and "--kata" in pj.argv                                  # kata tetap dipakai pelacak
    (folder_hasil / "kata.json").unlink()
    _jadwalkan(engine, pid, cid)
    pj2 = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj2)
    assert "--kata" not in pj2.argv and "--gaya-teks" not in pj2.argv


def test_render_ulang_koreksi_dengan_kata_json_rusak_memakai_transkrip_asli(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    (folder_hasil / "kata.json").write_text("{rusak", encoding="utf-8")
    with engine.begin() as k:
        proyek.simpan_subtitle(k, pid, cid, {}, [{"s": 12.5, "w": "x"}])
    _jadwalkan(engine, pid, cid)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert Path(pj.argv[pj.argv.index("--kata") + 1]).name == "kata.json"


def test_render_ulang_mencatat_gaya_yang_dibakar_dan_animasi_diteruskan(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _tulis_kata(folder_hasil, KATA)
    with engine.begin() as k:
        proyek.simpan_subtitle(k, pid, cid, {"gaya": "kuning", "animasi": "muncul"})
        assert proyek.cari_klip(k, pid, cid)["subtitle_perlu_render"] is True
    _jadwalkan(engine, pid, cid)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert pj.argv[pj.argv.index("--animasi-teks") + 1] == "muncul"
    with engine.connect() as k:
        klip = proyek.cari_klip(k, pid, cid)
    assert klip["subtitle_perlu_render"] is False and klip["subtitle"]["gaya"] == "kuning"
    with engine.begin() as k:                                   # simpan gaya lain: catatan "terender" tidak ikut berubah
        k_baru = proyek.simpan_subtitle(k, pid, cid, {"gaya": "kotak"})
    assert k_baru["subtitle_perlu_render"] is True
    with engine.begin() as k:                                   # kembali ke gaya yang sudah ada di video
        assert proyek.simpan_subtitle(k, pid, cid, {"gaya": "kuning", "animasi": "muncul"})["subtitle_perlu_render"] is False


def test_render_ulang_dengan_potong_jeda_mengirim_selang_dan_mencatat_terender(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    _tulis_kata(folder_hasil, [{"w": "a", "s": 12.0, "e": 12.4}, {"w": "b", "s": 15.0, "e": 15.4}])
    _jadwalkan(engine, pid, cid, mulai=12.0, akhir=16.0)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert "--buang" not in pj.argv                                      # jeda mati secara bawaan
    with engine.begin() as k:
        proyek.simpan_jeda(k, pid, cid, {"aktif": True, "ambang": 1.0})
        assert proyek.cari_klip(k, pid, cid)["subtitle_perlu_render"] is True
    _jadwalkan(engine, pid, cid, mulai=12.0, akhir=16.0)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    buang = json.loads(pj.argv[pj.argv.index("--buang") + 1])
    assert buang == [[12.5, 14.9]] or buang == [[12.5, 14.9], [15.5, 16.0]]
    with engine.connect() as k:
        assert proyek.cari_klip(k, pid, cid)["subtitle_perlu_render"] is False      # sudah dirender dengan jeda dipotong
        assert proyek.cari_klip(k, pid, cid)["jeda"] == {"aktif": True, "ambang": 1.0}


def test_render_ulang_jeda_aktif_tanpa_kata_json_tetap_jalan_tanpa_potong(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    with engine.begin() as k:
        proyek.simpan_jeda(k, pid, cid, {"aktif": True})
    _jadwalkan(engine, pid, cid)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert "--buang" not in pj.argv


def test_render_ulang_potongan_manual_digabung_dengan_jeda_dan_dipotong_ke_batas_klip(engine, cfg):
    pid, cid, folder_hasil = _proyek_selesai_dengan_klip(engine, cfg)
    with engine.begin() as k:
        proyek.simpan_potong(k, pid, cid, [[13.0, 14.0], [15.5, 17.0], [60.0, 70.0]])
    _jadwalkan(engine, pid, cid, mulai=12.0, akhir=16.0)
    pj = PenjalanKlip()
    assert _kerjakan(engine, cfg, pj)
    assert json.loads(pj.argv[pj.argv.index("--buang") + 1]) == [[13.0, 14.0], [15.5, 16.0]]
    with engine.connect() as k:
        assert proyek.cari_klip(k, pid, cid)["subtitle_perlu_render"] is False
