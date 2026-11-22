"""Tes unggah video dan daftar proyek (backend/api_proyek.py). SQLite di memori + folder sementara."""
import json
import re
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

pytest.importorskip("httpx")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient  # noqa: E402

from backend import api_proyek, config, keamanan, konteks, main, pengguna, proyek  # noqa: E402

RAHASIA = "r" * 32
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"isi-video-palsu" * 50
TABEL = [
    """CREATE TABLE users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
      password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', is_active INTEGER NOT NULL DEFAULT 1,
      quota_projects INTEGER NOT NULL DEFAULT 5, quota_storage_mb INTEGER NOT NULL DEFAULT 2048,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
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
]


@pytest.fixture(autouse=True)
def hasher_cepat(monkeypatch):
    monkeypatch.setattr(keamanan, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    monkeypatch.setattr(keamanan, "_hash_palsu", None)


@pytest.fixture
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with e.begin() as k:
        for t in TABEL:
            k.execute(text(t))
    return e


@pytest.fixture
def simpan(tmp_path):
    return tmp_path / "storage"


@pytest.fixture
def app(engine, simpan):
    ctx = konteks.Konteks(engine=engine, sekarang=lambda: 1_000_000.0,
                          sesi={"rahasia": RAHASIA, "acak": False, "umur": 3600, "cookie_aman": False},
                          unggah={"folder": simpan, "maks_bytes": 1024 * 1024})
    return main.buat_app(lambda: {"ok": True}, konteks=ctx)


def _klien_masuk(app, engine, email, role="user", kuota=5):
    with engine.begin() as k:
        uid = pengguna.buat(k, email, "Nama", keamanan.hash_password("password123"), role)
        k.execute(text("UPDATE users SET quota_projects = :q WHERE id = :i"), {"q": kuota, "i": uid})
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": email, "password": "password123"}).status_code == 200
    return c, uid


@pytest.fixture
def ani(app, engine):
    return _klien_masuk(app, engine, "ani@contoh.com")


def _unggah(klien, nama="video.mp4", isi=VIDEO, **data):
    return klien.post("/projects", files={"file": (nama, isi, "video/mp4")}, data=data)


def _berkas_di(simpan):
    return sorted(str(p.relative_to(simpan)).replace("\\", "/") for p in simpan.rglob("*") if p.is_file())


def _hitung(engine, tabel):
    with engine.connect() as k:
        return k.execute(text(f"SELECT COUNT(*) FROM {tabel}")).scalar()


# ---------------------------------------------------------------- unggah berhasil
def test_unggah_berhasil_baris_antrean_dan_berkas(ani, engine, simpan):
    klien, uid = ani
    r = _unggah(klien, "Podcast Keuangan.mp4", n_clips="4", ratio="1:1", language="id", face_tracking="false")
    assert r.status_code == 201
    p = r.json()
    assert p["id"] == 1 and p["title"] == "Podcast Keuangan" and p["source_ref"] == "Podcast Keuangan.mp4"
    assert (p["status"], p["stage"], p["progress"], p["n_clips"], p["ratio"], p["language"], p["face_tracking"]) == \
           ("queued", "Antre", 0, 4, "1:1", "id", False)
    assert str(simpan) not in r.text                                # lokasi di server tidak bocor
    assert (simpan / "projects" / "1" / "source.mp4").read_bytes() == VIDEO
    assert _berkas_di(simpan) == ["projects/1/source.mp4"]          # tidak ada sisa berkas sementara
    with engine.connect() as k:
        baris = k.execute(text("SELECT user_id, source_type FROM projects")).one()
        job = k.execute(text("SELECT type, payload, status FROM job_queue")).one()
    assert tuple(baris) == (uid, "upload")
    assert (job[0], json.loads(job[1]), job[2]) == ("process_project", {"project_id": 1}, "queued")


def test_nilai_bawaan_dan_judul_manual(ani):
    klien, _ = ani
    p = _unggah(klien, "a.mov").json()
    assert (p["n_clips"], p["clip_density"], p["clip_length"], p["ratio"], p["language"], p["face_tracking"]) == \
           (None, "sedang", "otomatis", "9:16", "auto", True)
    assert _unggah(klien, "b.mkv", title="  Judul Saya  ").json()["title"] == "Judul Saya"


@pytest.mark.parametrize("nama", ["a.mp4", "a.MOV", "a.mkv", "a.webm", "a.avi"])
def test_ekstensi_yang_didukung(ani, nama):
    assert _unggah(ani[0], nama).status_code == 201


def test_nama_berkas_berbahaya_tidak_keluar_dari_folder_proyek(ani, simpan, tmp_path):
    klien, _ = ani
    for nama in ("../../../luar.mp4", "..\\..\\luar.mp4", "/etc/passwd.mp4"):
        r = _unggah(klien, nama)
        assert r.status_code == 201 and "/" not in r.json()["source_ref"] and "\\" not in r.json()["source_ref"]
    assert not (tmp_path / "luar.mp4").exists()
    assert all(re.fullmatch(r"projects/\d+/source\.mp4", b) for b in _berkas_di(simpan))


# ---------------------------------------------------------------- penolakan
def test_tanpa_login_ditolak_dan_tidak_ada_jejak(app, engine, simpan):
    r = _unggah(TestClient(app))
    assert r.status_code == 401 and not simpan.exists() and _hitung(engine, "projects") == 0


@pytest.mark.parametrize("nama", ["virus.exe", "catatan.txt", "tanpa_ekstensi", "video.mp4.exe", ".mp4"])
def test_format_tidak_didukung(ani, engine, simpan, nama):
    r = _unggah(ani[0], nama)
    assert r.status_code == 422 and "Format" in r.json()["detail"]
    assert _hitung(engine, "projects") == 0 and not simpan.exists()


def test_berkas_kosong(ani, engine, simpan):
    r = _unggah(ani[0], isi=b"")
    assert r.status_code == 422 and _hitung(engine, "projects") == 0 and _berkas_di(simpan) == []


def test_terlalu_besar(ani, engine, simpan):
    r = _unggah(ani[0], isi=b"x" * (1024 * 1024 + 1))
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    assert _hitung(engine, "projects") == 0 and _berkas_di(simpan) == []
    assert _unggah(ani[0], isi=b"x" * (1024 * 1024)).status_code == 201          # tepat di batas masih boleh


@pytest.mark.parametrize("data", [{"ratio": "16:9"}, {"n_clips": "0"}, {"n_clips": "51"}, {"clip_density": "padat"}, {"clip_length": "super"}, {"n_clips": "abc"},
                                  {"language": "indonesia"}, {"language": "I D"}, {"title": "x" * 201}])
def test_opsi_tidak_valid(ani, engine, simpan, data):
    assert _unggah(ani[0], **data).status_code == 422
    assert _hitung(engine, "projects") == 0 and _berkas_di(simpan) == []


def test_kuota_proyek_pengguna_biasa(app, engine, simpan):
    klien, _ = _klien_masuk(app, engine, "kecil@contoh.com", kuota=2)
    assert _unggah(klien).status_code == 201 and _unggah(klien).status_code == 201
    r = _unggah(klien)
    assert r.status_code == 403 and "Kuota" in r.json()["detail"]
    assert _hitung(engine, "projects") == 2 and len(_berkas_di(simpan)) == 2


def test_admin_tidak_dibatasi_kuota(app, engine):
    klien, _ = _klien_masuk(app, engine, "admin@contoh.com", role="admin", kuota=1)
    assert _unggah(klien).status_code == 201 and _unggah(klien).status_code == 201


def test_kuota_dihitung_per_pengguna(app, engine):
    a, _ = _klien_masuk(app, engine, "a@contoh.com", kuota=1)
    b, _ = _klien_masuk(app, engine, "b@contoh.com", kuota=1)
    assert _unggah(a).status_code == 201 and _unggah(b).status_code == 201


# ---------------------------------------------------------------- kegagalan di tengah jalan
def test_gagal_menyimpan_dibatalkan_dan_dibersihkan(ani, engine, simpan, monkeypatch):
    def rusak(*a, **k):
        raise RuntimeError("antrean macet")

    monkeypatch.setattr(proyek, "antrekan", rusak)
    r = _unggah(ani[0])
    assert r.status_code == 500 and r.json() == {"detail": "Gagal menyimpan proyek"}
    assert _hitung(engine, "projects") == 0                       # baris proyek ikut dibatalkan
    assert _berkas_di(simpan) == [] and not (simpan / "projects" / "1").exists()


def test_gagal_memindahkan_berkas_dibersihkan(ani, engine, simpan, monkeypatch):
    monkeypatch.setattr(api_proyek.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk penuh")))
    r = _unggah(ani[0])
    assert r.status_code == 500 and _hitung(engine, "projects") == 0 and _berkas_di(simpan) == []


def test_gagal_tulis_ke_disk(ani, engine, monkeypatch):
    monkeypatch.setattr(api_proyek.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("tidak bisa")))
    r = _unggah(ani[0])
    assert r.status_code == 500 and "disk" in r.json()["detail"] and _hitung(engine, "projects") == 0


# ---------------------------------------------------------------- daftar dan detail
def test_daftar_hanya_milik_sendiri_terbaru_dulu(app, engine):
    a, _ = _klien_masuk(app, engine, "a@contoh.com")
    b, _ = _klien_masuk(app, engine, "b@contoh.com")
    _unggah(a, "satu.mp4")
    _unggah(b, "milik-b.mp4")
    _unggah(a, "dua.mp4")
    assert [p["title"] for p in a.get("/projects").json()] == ["dua", "satu"]
    assert [p["title"] for p in b.get("/projects").json()] == ["milik-b"]


def test_detail_milik_sendiri_dan_milik_orang_lain(app, engine):
    a, _ = _klien_masuk(app, engine, "a@contoh.com")
    b, _ = _klien_masuk(app, engine, "b@contoh.com")
    pid = _unggah(a, "rahasia-a.mp4").json()["id"]
    assert a.get(f"/projects/{pid}").json()["title"] == "rahasia-a"
    assert b.get(f"/projects/{pid}").status_code == 404           # bukan 403: keberadaannya tidak dibocorkan
    assert a.get("/projects/999").status_code == 404
    assert a.get("/projects/abc").status_code == 422


def test_admin_hanya_melihat_proyeknya_sendiri(app, engine):
    a, _ = _klien_masuk(app, engine, "a@contoh.com")
    adm, _ = _klien_masuk(app, engine, "admin@contoh.com", role="admin")
    pid = _unggah(a).json()["id"]
    assert adm.get("/projects").json() == [] and adm.get(f"/projects/{pid}").status_code == 404


def test_daftar_dan_detail_butuh_login(app):
    k = TestClient(app)
    assert k.get("/projects").status_code == 401 and k.get("/projects/1").status_code == 401


# ---------------------------------------------------------------- pengaturan
def test_pengaturan_unggah_bawaan_dan_relatif_ke_folder_proyek(tmp_path):
    p = config.pengaturan_unggah({}, base=tmp_path)
    assert p == {"folder": tmp_path / "storage", "maks_bytes": 2048 * 1024 * 1024}
    p = config.pengaturan_unggah({"STORAGE_DIR": str(tmp_path / "lain"), "MAX_UPLOAD_MB": "0.5"}, base=Path("/x"))
    assert p == {"folder": tmp_path / "lain", "maks_bytes": 524288}


@pytest.mark.parametrize("mb", ["abc", "0", "-5"])
def test_pengaturan_unggah_tidak_valid(mb):
    with pytest.raises(ValueError, match="MAX_UPLOAD_MB"):
        config.pengaturan_unggah({"MAX_UPLOAD_MB": mb})


def test_konfigurasi_unggah_salah_memberi_503(app, engine, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "abc")
    ctx = konteks.Konteks(engine=engine, sekarang=lambda: 1_000_000.0, muat_env=lambda: None,
                          sesi={"rahasia": RAHASIA, "acak": False, "umur": 3600, "cookie_aman": False})
    a = main.buat_app(lambda: {"ok": True}, konteks=ctx)
    c, _ = _klien_masuk(a, engine, "x@contoh.com")
    r = _unggah(c)
    assert r.status_code == 503 and "MAX_UPLOAD_MB" in r.json()["detail"]


# ---------------------------------------------------------------- kolom yang dipakai ada di schema.sql
def _kolom(sql, tabel):
    blok = re.search(rf"CREATE TABLE IF NOT EXISTS {tabel} \((.*?)\) ENGINE", sql, re.S).group(1)
    return set(re.findall(r"^\s{2}(\w+)\s", blok, re.M)), blok


def test_kolom_yang_dipakai_ada_di_schema_sql():
    sql = (Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
    kolom_p, blok_p = _kolom(sql, "projects")
    assert set(proyek._KOLOM.replace(" ", "").split(",")) <= kolom_p
    assert {"user_id", "source_type", "source_ref"} <= kolom_p
    for nilai in ("'9:16'", "'1:1'", "'4:5'", "'upload'", "'queued'"):
        assert nilai in blok_p
    kolom_j, blok_j = _kolom(sql, "job_queue")
    assert {"type", "payload", "status"} <= kolom_j and "'process_project'" in blok_j
    assert "quota_projects" in _kolom(sql, "users")[0]


# ---------------------------------------------------------------- tautan YouTube
TAUTAN = "https://www.youtube.com/watch?v=abc123XYZ_-"


def _tautan(klien, url=TAUTAN, **data):
    return klien.post("/projects", data={"url": url, **data})


def test_tautan_berhasil_tanpa_berkas_dan_masuk_antrean(ani, engine, simpan):
    klien, uid = ani
    r = _tautan(klien, n_clips="2", ratio="4:5")
    assert r.status_code == 201
    p = r.json()
    assert (p["source_type"], p["source_ref"], p["title"], p["status"], p["stage"]) == ("link", TAUTAN, "", "queued", "Antre")
    assert (p["n_clips"], p["ratio"]) == (2, "4:5")
    assert (simpan / "projects" / "1").is_dir() and _berkas_di(simpan) == []        # video diunduh worker nanti
    with engine.connect() as k:
        job = k.execute(text("SELECT type, payload FROM job_queue")).one()
    assert (job[0], json.loads(job[1])) == ("process_project", {"project_id": 1})


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc", "http://youtube.com/watch?v=abc", "https://m.youtube.com/watch?v=abc",
    "https://youtu.be/abc123", "https://www.youtube.com/shorts/abc", "https://YOUTUBE.com/watch?v=abc",
    "https://www.youtube.com:443/watch?v=abc", "  https://youtu.be/abc  ",
])
def test_tautan_youtube_yang_diterima(ani, url):
    assert _tautan(ani[0], url).status_code == 201


@pytest.mark.parametrize("url", [
    "http://localhost:8000/admin", "http://127.0.0.1/x", "https://evil.com/?youtube.com", "https://youtube.com.evil.com/x",
    "https://evilyoutube.com/x", "https://www.youtube.com@evil.com/x", "https://user:pw@www.youtube.com/x",
    "ftp://www.youtube.com/x", "file:///etc/passwd", "javascript:alert(1)", "bukan tautan", "www.youtube.com/watch?v=abc",
    "https://www.youtube.com:8080/x", "https://www.youtube.com/watch?v=a b", "https://vimeo.com/123",
    "https://www.youtube.com/" + "a" * 600,
])
def test_tautan_yang_ditolak(ani, engine, simpan, url):
    r = _tautan(ani[0], url)
    assert r.status_code == 422
    assert _hitung(engine, "projects") == 0 and _hitung(engine, "job_queue") == 0 and not simpan.exists()


def test_berkas_dan_tautan_sekaligus_atau_kosong_ditolak(ani, engine):
    klien, _ = ani
    r = klien.post("/projects", files={"file": ("a.mp4", VIDEO, "video/mp4")}, data={"url": TAUTAN})
    assert r.status_code == 422 and "salah satu" in r.json()["detail"]
    r = klien.post("/projects", data={})
    assert r.status_code == 422 and "wajib" in r.json()["detail"]
    r = klien.post("/projects", data={"url": "   "})
    assert r.status_code == 422 and _hitung(engine, "projects") == 0


def test_tautan_memakai_judul_dari_pengguna_dan_kuota(app, engine):
    klien, _ = _klien_masuk(app, engine, "kecil@contoh.com", kuota=1)
    assert _tautan(klien, title=" Podcast Saya ").json()["title"] == "Podcast Saya"
    r = _tautan(klien)
    assert r.status_code == 403 and "Kuota" in r.json()["detail"]
    r = _unggah(klien)                                                       # kuota berlaku lintas jenis sumber
    assert r.status_code == 403


def test_tautan_tanpa_login_ditolak(app, engine):
    assert _tautan(TestClient(app)).status_code == 401 and _hitung(engine, "projects") == 0


def test_tautan_gagal_menyimpan_dibersihkan(ani, engine, simpan, monkeypatch):
    monkeypatch.setattr(proyek, "antrekan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("macet")))
    r = _tautan(ani[0])
    assert r.status_code == 500 and _hitung(engine, "projects") == 0 and not (simpan / "projects" / "1").exists()


def test_proyek_buat_menolak_jenis_sumber_aneh(engine):
    with engine.begin() as k:
        with pytest.raises(ValueError):
            proyek.buat(k, 1, "t", "s", "auto", "9:16", 3, True, source_type="ftp")


# ---------------------------------------------------------------- jumlah klip otomatis dan durasi klip
def test_jumlah_dan_durasi_klip_dipilih_pengguna(ani, engine):
    klien, _ = ani
    p = _unggah(klien, "a.mp4", clip_density="rapat", clip_length="pendek").json()
    assert (p["n_clips"], p["clip_density"], p["clip_length"]) == (None, "rapat", "pendek")
    p = _tautan(klien, clip_density="jarang", clip_length="panjang").json()
    assert (p["n_clips"], p["clip_density"], p["clip_length"]) == (None, "jarang", "panjang")
    p = _unggah(klien, "b.mp4", n_clips="7").json()                                  # jumlah pasti tetap bisa
    assert p["n_clips"] == 7
    with engine.connect() as k:
        assert k.execute(text("SELECT clip_density, clip_length FROM projects WHERE id = :i"), {"i": p["id"]}).one() == ("sedang", "otomatis")


def test_kolom_baru_ada_di_schema_sql_dan_n_clips_boleh_kosong():
    sql = (Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
    kolom, blok = _kolom(sql, "projects")
    assert {"n_clips", "clip_density", "clip_length"} <= kolom
    assert re.search(r"n_clips\s+TINYINT UNSIGNED NULL", blok) and "NOT NULL DEFAULT 'sedang'" in blok
    for nilai in ("'jarang'", "'sedang'", "'rapat'", "'otomatis'", "'pendek'", "'panjang'"):
        assert nilai in blok


def test_buat_menolak_pilihan_aneh(engine):
    with engine.begin() as k:
        with pytest.raises(ValueError):
            proyek.buat(k, 1, "t", "s", "auto", "9:16", None, True, kepadatan="padat")
        with pytest.raises(ValueError):
            proyek.buat(k, 1, "t", "s", "auto", "9:16", None, True, panjang="super")
