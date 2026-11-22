"""Tes daftar klip dan pemutaran/unduhan video (backend/api_klip.py). SQLite di memori + folder sementara."""
import os
import re
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

pytest.importorskip("httpx")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient  # noqa: E402

from backend import keamanan, konteks, main, pengguna, proyek  # noqa: E402

RAHASIA = "r" * 32
ISI = bytes(range(256)) * 40            # 10240 byte, mudah dicek potongannya
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
    """CREATE TABLE clips (
      id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, start_sec REAL NOT NULL, end_sec REAL NOT NULL,
      score REAL NOT NULL DEFAULT 0, hook REAL NOT NULL DEFAULT 0, flow REAL NOT NULL DEFAULT 0,
      value_score REAL NOT NULL DEFAULT 0, trend REAL NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '', titles TEXT,
      caption TEXT NOT NULL DEFAULT '', hashtags TEXT, ratio TEXT NOT NULL DEFAULT '9:16',
      status TEXT NOT NULL DEFAULT 'queued', file_path TEXT, size_bytes INTEGER, render_seconds REAL)""",
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


def _masuk(app, engine, email):
    with engine.begin() as k:
        uid = pengguna.buat(k, email, "Nama", keamanan.hash_password("password123"), "user")
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": email, "password": "password123"}).status_code == 200
    return c, uid


@pytest.fixture
def ani(app, engine):
    return _masuk(app, engine, "ani@contoh.com")


@pytest.fixture
def budi(app, engine):
    return _masuk(app, engine, "budi@contoh.com")


def _proyek_dengan_klip(engine, simpan, uid, judul=("Judul Satu", "Judul Dua"), skor=(60.0, 80.0)):
    """Satu proyek berisi dua klip jadi dengan berkas sungguhan di storage/projects/<id>/."""
    with engine.begin() as k:
        pid = proyek.buat(k, uid, "Proyek", "v.mp4", "auto", "9:16", 2, True)
    folder = simpan / "projects" / str(pid)
    folder.mkdir(parents=True)
    daftar = []
    for i, (j, sk) in enumerate(zip(judul, skor), start=1):
        (folder / f"klip_{i:02d}_9x16.mp4").write_bytes(ISI)
        daftar.append({"start": 10.0 * i, "end": 10.0 * i + 30, "score": sk, "hook": 0.8, "flow": 0.6, "value": 0.5,
                       "trend": 0.4, "title": j, "caption": f"Caption {i}", "hashtags": ["#a", "#b"],
                       "file_path": f"projects/{pid}/klip_{i:02d}_9x16.mp4", "size_bytes": len(ISI)})
    with engine.begin() as k:
        proyek.simpan_klip(k, pid, "9:16", daftar)
    return pid


def _id_klip(engine, pid):
    with engine.connect() as k:
        return [r[0] for r in k.execute(text("SELECT id FROM clips WHERE project_id = :p ORDER BY id"), {"p": pid})]


# ---------------------------------------------------------------- daftar klip
def test_daftar_klip_urut_skor_tertinggi_dan_tanpa_lokasi_server(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    r = klien.get(f"/projects/{pid}/clips")
    assert r.status_code == 200
    d = r.json()
    assert [k["title"] for k in d] == ["Judul Dua", "Judul Satu"]                     # skor 80 dulu
    k = d[0]
    assert (k["start_sec"], k["end_sec"], k["duration_sec"], k["score"], k["ratio"], k["status"]) == (20.0, 50.0, 30.0, 80.0, "9:16", "done")
    assert (k["hook"], k["flow"], k["value"], k["trend"]) == (0.8, 0.6, 0.5, 0.4)
    assert (k["caption"], k["hashtags"], k["size_bytes"], k["ada_video"]) == ("Caption 2", ["#a", "#b"], len(ISI), True)
    assert "file_path" not in k and str(simpan) not in r.text and "klip_02" not in r.text


def test_skor_sama_diurutkan_menurut_id(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid, skor=(70.0, 70.0))
    assert [k["title"] for k in klien.get(f"/projects/{pid}/clips").json()] == ["Judul Satu", "Judul Dua"]


def test_proyek_tanpa_klip_daftar_kosong(ani, engine):
    klien, uid = ani
    with engine.begin() as k:
        pid = proyek.buat(k, uid, "Kosong", "v.mp4", "auto", "9:16", 2, True)
    r = klien.get(f"/projects/{pid}/clips")
    assert r.status_code == 200 and r.json() == []


def test_klip_hanya_dari_proyek_yang_diminta(ani, engine, simpan):
    klien, uid = ani
    p1 = _proyek_dengan_klip(engine, simpan, uid, judul=("A1", "A2"))
    p2 = _proyek_dengan_klip(engine, simpan, uid, judul=("B1", "B2"))
    assert sorted(k["title"] for k in klien.get(f"/projects/{p1}/clips").json()) == ["A1", "A2"]
    assert sorted(k["title"] for k in klien.get(f"/projects/{p2}/clips").json()) == ["B1", "B2"]


@pytest.mark.parametrize("mentah", ['["#x", "#y"]', "bukan json", "null", '{"a": 1}', "", None])
def test_hashtag_rusak_tidak_membuat_galat(ani, engine, simpan, mentah):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET hashtags = :h WHERE project_id = :p"), {"h": mentah, "p": pid})
    r = klien.get(f"/projects/{pid}/clips")
    assert r.status_code == 200
    assert r.json()[0]["hashtags"] == (["#x", "#y"] if mentah == '["#x", "#y"]' else [])


def test_klip_belum_jadi_tidak_dianggap_punya_video(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET status = 'rendering' WHERE id = 1"))
        k.execute(text("UPDATE clips SET file_path = NULL WHERE id = 2"))
    assert [k["ada_video"] for k in klien.get(f"/projects/{pid}/clips").json()] == [False, False]


# ---------------------------------------------------------------- izin
def test_orang_lain_dan_tanpa_login_mendapat_404_atau_401(app, ani, budi, engine, simpan):
    klien_ani, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    cid = _id_klip(engine, pid)[0]
    klien_budi, _ = budi
    for jalur in (f"/projects/{pid}/clips", f"/projects/{pid}/clips/{cid}/video"):
        assert klien_budi.get(jalur).status_code == 404
        assert TestClient(app).get(jalur).status_code == 401
        assert klien_ani.get(jalur).status_code == 200
    r = klien_budi.get(f"/projects/{pid}/clips/{cid}/video")
    assert r.json()["detail"] == klien_budi.get("/projects/9999/clips").json()["detail"]      # sama dengan proyek tak ada


def test_klip_proyek_lain_tidak_bisa_diambil_lewat_proyek_sendiri(ani, engine, simpan):
    klien, uid = ani
    p1 = _proyek_dengan_klip(engine, simpan, uid)
    p2 = _proyek_dengan_klip(engine, simpan, uid)
    klip_p2 = _id_klip(engine, p2)[0]
    assert klien.get(f"/projects/{p1}/clips/{klip_p2}/video").status_code == 404
    assert klien.get(f"/projects/{p2}/clips/{klip_p2}/video").status_code == 200


# ---------------------------------------------------------------- video
def test_video_diputar_inline_dan_didukung_range(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    cid = _id_klip(engine, pid)[1]
    r = klien.get(f"/projects/{pid}/clips/{cid}/video")
    assert r.status_code == 200 and r.content == ISI
    assert r.headers["content-type"] == "video/mp4" and r.headers["content-disposition"].startswith("inline")
    assert "Judul%20Dua.mp4" in r.headers["content-disposition"]
    p = klien.get(f"/projects/{pid}/clips/{cid}/video", headers={"Range": "bytes=100-199"})
    assert p.status_code == 206 and p.content == ISI[100:200]
    assert p.headers["content-range"] == f"bytes 100-199/{len(ISI)}"


def test_unduh_memakai_attachment_dan_nama_aman(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid, judul=('Judul: "aneh"/..\\x?', ""))
    ids = _id_klip(engine, pid)
    r = klien.get(f"/projects/{pid}/clips/{ids[0]}/video?unduh=true")
    kepala = r.headers["content-disposition"]
    assert kepala.startswith("attachment") and "/" not in kepala.split("filename")[1] and "\\" not in kepala and "?" not in kepala
    assert f"klip-{ids[1]}.mp4" in klien.get(f"/projects/{pid}/clips/{ids[1]}/video?unduh=true").headers["content-disposition"]


def test_video_tidak_ada_atau_belum_jadi_404(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    ids = _id_klip(engine, pid)
    assert klien.get(f"/projects/{pid}/clips/999/video").status_code == 404                     # klip tidak ada
    (simpan / "projects" / str(pid) / "klip_01_9x16.mp4").unlink()
    assert klien.get(f"/projects/{pid}/clips/{ids[0]}/video").status_code == 404                # berkas hilang
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i"), {"i": ids[1]})
    assert klien.get(f"/projects/{pid}/clips/{ids[1]}/video").status_code == 404                # belum selesai


@pytest.mark.parametrize("lokasi", ["../../rahasia.txt", "projects/2/klip_01_9x16.mp4", "/etc/passwd", "..", ""])
def test_lokasi_berkas_di_luar_folder_proyek_ditolak(ani, engine, simpan, lokasi):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    (simpan.parent / "rahasia.txt").write_text("rahasia")
    p2 = _proyek_dengan_klip(engine, simpan, uid)                  # folder proyek lain berisi berkas sungguhan
    assert p2 == 2
    cid = _id_klip(engine, pid)[0]
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET file_path = :f WHERE id = :i"), {"f": lokasi, "i": cid})
    r = klien.get(f"/projects/{pid}/clips/{cid}/video")
    assert r.status_code == 404 and "rahasia" not in r.text


@pytest.mark.skipif(os.name == "nt", reason="tautan simbolik butuh izin khusus di Windows")
def test_tautan_simbolik_keluar_folder_ditolak(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    luar = simpan.parent / "luar.mp4"
    luar.write_bytes(b"rahasia")
    tautan = simpan / "projects" / str(pid) / "tautan.mp4"
    tautan.symlink_to(luar)
    cid = _id_klip(engine, pid)[0]
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET file_path = :f WHERE id = :i"), {"f": f"projects/{pid}/tautan.mp4", "i": cid})
    assert klien.get(f"/projects/{pid}/clips/{cid}/video").status_code == 404


def test_kolom_klip_yang_dipakai_ada_di_schema_sql():
    sql = (Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
    blok = re.search(r"CREATE TABLE IF NOT EXISTS clips \((.*?)\) ENGINE", sql, re.S).group(1)
    kolom = set(re.findall(r"^\s{2}(\w+)\s", blok, re.M))
    assert set(proyek._KOLOM_KLIP.replace(" ", "").replace("\n", "").split(",")) <= kolom


def test_klip_harus_milik_proyek_di_url_bukan_hanya_berkas_di_dalam_folder(ani, engine, simpan):
    """Klip proyek 2 yang (secara tidak wajar) menunjuk berkas di folder proyek 1 tetap tidak boleh keluar lewat URL proyek 1."""
    klien, uid = ani
    p1 = _proyek_dengan_klip(engine, simpan, uid)
    p2 = _proyek_dengan_klip(engine, simpan, uid)
    klip_p2 = _id_klip(engine, p2)[0]
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET file_path = :f WHERE id = :i"), {"f": f"projects/{p1}/klip_01_9x16.mp4", "i": klip_p2})
    assert klien.get(f"/projects/{p1}/clips/{klip_p2}/video").status_code == 404
