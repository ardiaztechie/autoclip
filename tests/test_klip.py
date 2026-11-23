"""Tes daftar klip dan pemutaran/unduhan video (backend/api_klip.py). SQLite di memori + folder sementara."""
import json
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
      status TEXT NOT NULL DEFAULT 'queued', file_path TEXT, size_bytes INTEGER, render_seconds REAL,
      edit_count INTEGER NOT NULL DEFAULT 0, edit_settings TEXT)""",
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


def _proyek_dengan_klip(engine, simpan, uid, judul=("Judul Satu", "Judul Dua"), skor=(60.0, 80.0),
                         mulai=(10.0, 20.0)):
    """Satu proyek berisi dua klip jadi dengan berkas sungguhan di storage/projects/<id>/."""
    with engine.begin() as k:
        pid = proyek.buat(k, uid, "Proyek", "v.mp4", "auto", "9:16", 2, True)
    folder = simpan / "projects" / str(pid)
    folder.mkdir(parents=True)
    daftar = []
    for i, (j, sk, m) in enumerate(zip(judul, skor, mulai), start=1):
        (folder / f"klip_{i:02d}_9x16.mp4").write_bytes(ISI)
        daftar.append({"start": m, "end": m + 30, "score": sk, "hook": 0.8, "flow": 0.6, "value": 0.5,
                       "trend": 0.4, "title": j, "caption": f"Caption {i}", "hashtags": ["#a", "#b"],
                       "file_path": f"projects/{pid}/klip_{i:02d}_9x16.mp4", "size_bytes": len(ISI)})
    with engine.begin() as k:
        proyek.simpan_klip(k, pid, "9:16", daftar)
    return pid


def _id_klip(engine, pid):
    with engine.connect() as k:
        return [r[0] for r in k.execute(text("SELECT id FROM clips WHERE project_id = :p ORDER BY id"), {"p": pid})]


# ---------------------------------------------------------------- daftar klip
def test_daftar_klip_urut_menit_video_dan_tanpa_lokasi_server(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    r = klien.get(f"/projects/{pid}/clips")
    assert r.status_code == 200
    d = r.json()
    assert [k["title"] for k in d] == ["Judul Satu", "Judul Dua"]                     # menit 10 dulu, bukan skor 80
    k = d[1]
    assert (k["start_sec"], k["end_sec"], k["duration_sec"], k["score"], k["ratio"], k["status"]) == (20.0, 50.0, 30.0, 80.0, "9:16", "done")
    assert (k["hook"], k["flow"], k["value"], k["trend"]) == (0.8, 0.6, 0.5, 0.4)
    assert (k["caption"], k["hashtags"], k["size_bytes"], k["ada_video"]) == ("Caption 2", ["#a", "#b"], len(ISI), True)
    assert "file_path" not in k and str(simpan) not in r.text and "klip_02" not in r.text


def test_urutan_menurut_menit_walau_disimpan_terbalik(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid, mulai=(300.0, 45.5))        # klip pertama disimpan = menit 300
    d = klien.get(f"/projects/{pid}/clips").json()
    assert [k["title"] for k in d] == ["Judul Dua", "Judul Satu"] and [k["start_sec"] for k in d] == [45.5, 300.0]


def test_menit_sama_diurutkan_menurut_id(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid, mulai=(10.0, 10.0))
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
        k.execute(text("UPDATE clips SET status = 'queued' WHERE id = 1"))
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
        k.execute(text("UPDATE clips SET status = 'queued' WHERE id = :i"), {"i": ids[1]})
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


# ---------------------------------------------------------------- edit judul, caption, hashtag
def test_edit_teks_klip_tersimpan_dan_urutan_serta_video_tidak_berubah(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    r = klien.patch(f"/projects/{pid}/clips/{kid}", json={"title": "  Judul Baru  ", "caption": "Caption baru", "hashtags": ["seru", "#lucu", "#Seru x", "lucu"]})
    assert r.status_code == 200
    d = r.json()
    assert (d["title"], d["caption"], d["hashtags"]) == ("Judul Baru", "Caption baru", ["#seru", "#lucu", "#Serux"])
    assert d["ada_video"] is True and d["start_sec"] == 10.0
    assert [k["title"] for k in klien.get(f"/projects/{pid}/clips").json()] == ["Judul Baru", "Judul Dua"]


def test_edit_teks_klip_validasi(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert klien.patch(f"/projects/{pid}/clips/{kid}", json={"title": "x" * 201}).status_code == 422
    assert klien.patch(f"/projects/{pid}/clips/{kid}", json={"caption": "x" * 501}).status_code == 422
    assert klien.patch(f"/projects/{pid}/clips/{kid}", json={"hashtags": ["#a"] * 31}).status_code == 422
    kosong = klien.patch(f"/projects/{pid}/clips/{kid}", json={"title": "", "caption": "", "hashtags": []})
    assert kosong.status_code == 200 and kosong.json()["hashtags"] == []


def test_edit_teks_klip_orang_lain_klip_lain_dan_tanpa_login(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    isi = {"title": "Dibajak", "caption": "", "hashtags": []}
    assert budi[0].patch(f"/projects/{pid}/clips/{kid}", json=isi).status_code == 404
    assert klien.patch(f"/projects/{pid}/clips/999999", json=isi).status_code == 404
    pid2 = _proyek_dengan_klip(engine, simpan, uid)
    assert klien.patch(f"/projects/{pid2}/clips/{kid}", json=isi).status_code == 404        # klip bukan milik proyek di URL
    assert TestClient(app).patch(f"/projects/{pid}/clips/{kid}", json=isi).status_code == 401
    assert klien.get(f"/projects/{pid}/clips").json()[0]["title"] == "Judul Satu"


def test_rapikan_hashtag():
    assert proyek.rapikan_hashtag(["a b", "#c", "##d", "c", "", "  "]) == ["#ab", "#c", "#d"]
    assert len(proyek.rapikan_hashtag([f"t{i}" for i in range(50)])) == 30
    assert proyek.rapikan_hashtag(None) == []


# ---------------------------------------------------------------- atur batas klip + render ulang
def _selesaikan(engine, pid, durasi=600.0):
    with engine.begin() as k:
        proyek.ubah(k, pid, status="done", stage="Selesai", progress=100, duration_sec=durasi)


def _sumber(simpan, pid):
    (simpan / "projects" / str(pid) / "source.mp4").write_bytes(b"video")


def test_render_ulang_menandai_klip_dan_mengantrekan_pekerjaan(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _selesaikan(engine, pid)
    _sumber(simpan, pid)
    kid = _id_klip(engine, pid)[0]
    r = klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json={"start_sec": 8.5, "end_sec": 60})
    assert r.status_code == 202 and r.json()["status"] == "rendering" and r.json()["ada_video"] is True
    with engine.connect() as k:
        tipe, isi, st = k.execute(text("SELECT type, payload, status FROM job_queue")).one()
    assert (tipe, st) == ("render_clip", "queued")
    assert json.loads(isi) == {"project_id": pid, "clip_id": kid, "mulai": 8.5, "akhir": 60.0}
    assert klien.get(f"/projects/{pid}/clips/{kid}/video").status_code == 200               # video lama tetap bisa diputar
    assert klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json={"start_sec": 9, "end_sec": 60}).status_code == 409


@pytest.mark.parametrize("isi,kode", [
    ({"start_sec": 10, "end_sec": 12}, 422),            # < 5 detik
    ({"start_sec": 0, "end_sec": 301}, 422),            # > 300 detik
    ({"start_sec": 30, "end_sec": 20}, 422),
    ({"start_sec": -1, "end_sec": 20}, 422),
    ({"start_sec": 590, "end_sec": 601}, 422),          # melewati durasi video 600 dtk
    ({"start_sec": 1}, 422),
])
def test_render_ulang_batas_tidak_valid(ani, engine, simpan, isi, kode):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _selesaikan(engine, pid)
    _sumber(simpan, pid)
    kid = _id_klip(engine, pid)[0]
    assert klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json=isi).status_code == kode
    with engine.connect() as k:
        assert k.execute(text("SELECT COUNT(*) FROM job_queue")).scalar() == 0


def test_render_ulang_syarat_proyek_dan_kepemilikan(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    isi = {"start_sec": 10, "end_sec": 40}
    assert klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json=isi).status_code == 409       # proyek belum 'done'
    _selesaikan(engine, pid)
    assert klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json=isi).status_code == 409       # video sumber tidak ada
    _sumber(simpan, pid)
    assert klien.post(f"/projects/{pid}/clips/999999/render-ulang", json=isi).status_code == 404
    assert budi[0].post(f"/projects/{pid}/clips/{kid}/render-ulang", json=isi).status_code == 404
    assert TestClient(app).post(f"/projects/{pid}/clips/{kid}/render-ulang", json=isi).status_code == 401
    with engine.connect() as k:
        assert k.execute(text("SELECT COUNT(*) FROM job_queue")).scalar() == 0


def test_batal_render_mengembalikan_klip_ke_done_dan_membatalkan_pekerjaan(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _selesaikan(engine, pid)
    _sumber(simpan, pid)
    kid = _id_klip(engine, pid)[0]
    assert klien.post(f"/projects/{pid}/clips/{kid}/batal-render").status_code == 409            # belum dirender ulang
    klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json={"start_sec": 8.5, "end_sec": 60})
    r = klien.post(f"/projects/{pid}/clips/{kid}/batal-render")
    assert r.status_code == 200 and r.json()["status"] == "done"
    with engine.connect() as k:
        assert k.execute(text("SELECT status, error FROM job_queue")).one()[:] == ("failed", "dibatalkan")
    assert klien.get(f"/projects/{pid}/clips/{kid}/video").status_code == 200
    assert klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json={"start_sec": 9, "end_sec": 60}).status_code == 202   # bisa diulang


def test_batal_render_kepemilikan_dan_klip_tidak_ada(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _selesaikan(engine, pid)
    _sumber(simpan, pid)
    kid = _id_klip(engine, pid)[0]
    klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json={"start_sec": 10, "end_sec": 40})
    assert klien.post(f"/projects/{pid}/clips/999999/batal-render").status_code == 404
    assert budi[0].post(f"/projects/{pid}/clips/{kid}/batal-render").status_code == 404
    assert TestClient(app).post(f"/projects/{pid}/clips/{kid}/batal-render").status_code == 401
    with engine.connect() as k:
        assert k.execute(text("SELECT status FROM clips WHERE id = :i"), {"i": kid}).scalar() == "rendering"


def test_daftar_klip_menyertakan_kemajuan_render_ulang(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _selesaikan(engine, pid)
    _sumber(simpan, pid)
    kid = _id_klip(engine, pid)[0]
    assert all("kemajuan" not in k for k in klien.get(f"/projects/{pid}/clips").json())     # tidak sedang dirender
    klien.post(f"/projects/{pid}/clips/{kid}/render-ulang", json={"start_sec": 8.5, "end_sec": 60})
    dirender = [k for k in klien.get(f"/projects/{pid}/clips").json() if k["id"] == kid][0]
    assert dirender["kemajuan"] is None                                                       # worker belum melapor
    folder = simpan / "projects" / str(pid) / "hasil" / f"_ulang_{kid}"
    folder.mkdir(parents=True)
    (folder / "progres.json").write_text(json.dumps({"persen": 42, "tahap": "Merender video", "berjalan": 31.5}), encoding="utf-8")
    dirender = [k for k in klien.get(f"/projects/{pid}/clips").json() if k["id"] == kid][0]
    assert dirender["kemajuan"] == {"persen": 42, "tahap": "Merender video", "berjalan_detik": 31.5}
    (folder / "progres.json").write_text("{rusak", encoding="utf-8")
    assert [k for k in klien.get(f"/projects/{pid}/clips").json() if k["id"] == kid][0]["kemajuan"] is None


# ---------------------------------------------------------------- gaya subtitle dan koreksi kata
def test_klip_punya_subtitle_bawaan(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    k = klien.get(f"/projects/{pid}/clips").json()[0]
    assert k["subtitle"] == {"gaya": "klasik", "posisi": "bawah", "ukuran": "sedang", "animasi": "tanpa", "aktif": True} and k["koreksi"] == []
    assert k["subtitle_perlu_render"] is False


def test_simpan_subtitle_dan_koreksi_dipertahankan_bila_tidak_dikirim(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    r = klien.put(f"/projects/{pid}/clips/{kid}/subtitle",
                  json={"gaya": "sorot", "posisi": "tengah", "ukuran": "besar", "aktif": True,
                        "koreksi": [{"s": 10.5, "w": "  halo   dunia "}, {"s": 11.2, "w": ""}]})
    assert r.status_code == 200
    assert r.json()["subtitle"] == {"gaya": "sorot", "posisi": "tengah", "ukuran": "besar", "animasi": "tanpa", "aktif": True}
    assert r.json()["subtitle_perlu_render"] is True
    assert r.json()["koreksi"] == [{"s": 10.5, "w": "halo dunia"}, {"s": 11.2, "w": ""}]
    r = klien.put(f"/projects/{pid}/clips/{kid}/subtitle", json={"gaya": "kotak", "aktif": False})    # tanpa koreksi
    assert r.json()["subtitle"]["gaya"] == "kotak" and r.json()["subtitle"]["aktif"] is False
    assert len(r.json()["koreksi"]) == 2
    r = klien.put(f"/projects/{pid}/clips/{kid}/subtitle", json={"gaya": "kotak", "koreksi": []})    # dikosongkan
    assert r.json()["koreksi"] == []
    assert klien.get(f"/projects/{pid}/clips").json()[0]["subtitle"]["gaya"] == "kotak"
    assert klien.get(f"/projects/{pid}/clips").json()[1]["subtitle"]["gaya"] == "klasik"             # klip lain tidak berubah


@pytest.mark.parametrize("isi", [
    {"gaya": "tidak ada"}, {"posisi": "kiri"}, {"ukuran": "raksasa"}, {"animasi": "terbang"}, {"aktif": "mungkin"},
    {"koreksi": [{"s": -1, "w": "x"}]}, {"koreksi": [{"s": 1, "w": "x" * 61}]}, {"koreksi": [{"w": "x"}]},
])
def test_simpan_subtitle_isi_tidak_valid(ani, engine, simpan, isi):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert klien.put(f"/projects/{pid}/clips/{kid}/subtitle", json=isi).status_code == 422


def test_simpan_subtitle_syarat_dan_kepemilikan(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    isi = {"gaya": "kuning"}
    assert budi[0].put(f"/projects/{pid}/clips/{kid}/subtitle", json=isi).status_code == 404
    assert klien.put(f"/projects/{pid}/clips/999999/subtitle", json=isi).status_code == 404
    assert TestClient(app).put(f"/projects/{pid}/clips/{kid}/subtitle", json=isi).status_code == 401
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i"), {"i": kid})
    assert klien.put(f"/projects/{pid}/clips/{kid}/subtitle", json=isi).status_code == 409            # sedang dirender
    with engine.connect() as k:
        assert k.execute(text("SELECT edit_settings FROM clips WHERE id = :i"), {"i": kid}).scalar() is None


def test_subtitle_semua_menyamakan_gaya_dan_mengantrekan_render(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    ids = _id_klip(engine, pid)
    klien.put(f"/projects/{pid}/clips/{ids[0]}/subtitle", json={"koreksi": [{"s": 12, "w": "x"}]})
    assert klien.post(f"/projects/{pid}/clips/subtitle-semua", json={"gaya": "sorot"}).status_code == 409     # belum selesai
    _selesaikan(engine, pid)
    assert klien.post(f"/projects/{pid}/clips/subtitle-semua", json={"gaya": "sorot"}).status_code == 409     # sumber tidak ada
    _sumber(simpan, pid)
    with engine.begin() as k:
        k.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i"), {"i": ids[1]})                  # satu klip sibuk
    r = klien.post(f"/projects/{pid}/clips/subtitle-semua", json={"gaya": "sorot", "posisi": "atas"})
    assert r.status_code == 202 and r.json() == {"diantre": 1}
    klip = {k["id"]: k for k in klien.get(f"/projects/{pid}/clips").json()}
    assert klip[ids[0]]["subtitle"]["gaya"] == "sorot" and klip[ids[0]]["subtitle"]["posisi"] == "atas"
    assert klip[ids[0]]["koreksi"] == [{"s": 12.0, "w": "x"}] and klip[ids[0]]["status"] == "rendering"      # koreksi utuh
    assert klip[ids[1]]["subtitle"]["gaya"] == "klasik"                                                         # dilewati
    with engine.connect() as k:
        assert k.execute(text("SELECT COUNT(*) FROM job_queue WHERE type = 'render_clip'")).scalar() == 1


def test_subtitle_semua_kepemilikan(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _selesaikan(engine, pid)
    _sumber(simpan, pid)
    assert budi[0].post(f"/projects/{pid}/clips/subtitle-semua", json={"gaya": "sorot"}).status_code == 404
    assert TestClient(app).post(f"/projects/{pid}/clips/subtitle-semua", json={"gaya": "sorot"}).status_code == 401
    assert klien.post(f"/projects/999/clips/subtitle-semua", json={"gaya": "sorot"}).status_code == 404


# ---------------------------------------------------------------- kata di sekitar klip (untuk editor)
def _tulis_kata(simpan, pid, kata):
    folder = simpan / "projects" / str(pid) / "hasil"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "kata.json").write_text(json.dumps(kata), encoding="utf-8")


def test_kata_klip_memuat_kata_di_sekitar_klip(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)                    # klip 1: 10-40 dtk
    _tulis_kata(simpan, pid, [{"w": f"k{i}", "s": float(i), "e": i + 0.5} for i in range(0, 200)])
    kid = _id_klip(engine, pid)[0]
    d = klien.get(f"/projects/{pid}/clips/{kid}/kata?margin=5").json()
    assert (d["dari"], d["sampai"]) == (5.0, 45.0)
    assert d["kata"][0] == {"w": "k5", "s": 5.0, "e": 5.5}                       # k4 berakhir 4,5 (< 5): di luar
    assert d["kata"][-1]["w"] == "k45" and len(d["kata"]) == 41
    besar = klien.get(f"/projects/{pid}/clips/{kid}/kata?margin=99999").json()
    assert besar["dari"] == 0.0 and besar["sampai"] == 160.0                       # dibatasi 120 dtk


def test_kata_klip_tanpa_atau_dengan_transkrip_rusak_kosong_dan_galat_lainnya(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert klien.get(f"/projects/{pid}/clips/{kid}/kata").json()["kata"] == []            # kata.json belum ada
    _tulis_kata(simpan, pid, {"bukan": "daftar"})
    assert klien.get(f"/projects/{pid}/clips/{kid}/kata").json()["kata"] == []            # bentuk salah
    assert klien.get(f"/projects/{pid}/clips/{kid}/kata?margin=-1").status_code == 422
    assert klien.get(f"/projects/{pid}/clips/999/kata").status_code == 404
    assert budi[0].get(f"/projects/{pid}/clips/{kid}/kata").status_code == 404
    assert TestClient(app).get(f"/projects/{pid}/clips/{kid}/kata").status_code == 401


def test_kata_rentang_bebas_untuk_garis_waktu(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _tulis_kata(simpan, pid, [{"w": f"k{i}", "s": float(i), "e": i + 0.5} for i in range(0, 300)])
    d = klien.get(f"/projects/{pid}/kata?dari=100&sampai=103").json()
    assert (d["dari"], d["sampai"]) == (100.0, 103.0)
    assert [k["w"] for k in d["kata"]] == ["k100", "k101", "k102", "k103"]
    assert klien.get(f"/projects/{pid}/kata?dari=0&sampai=900").status_code == 200
    for query in ("dari=5&sampai=5", "dari=9&sampai=3", "dari=-1&sampai=4", "dari=0&sampai=901", "dari=0"):
        assert klien.get(f"/projects/{pid}/kata?{query}").status_code == 422, query
    assert klien.get(f"/projects/{pid}/kata?dari=1000&sampai=1100").json()["kata"] == []        # lewat akhir transkrip
    assert budi[0].get(f"/projects/{pid}/kata?dari=0&sampai=10").status_code == 404
    assert klien.get("/projects/99999/kata?dari=0&sampai=10").status_code == 404
    assert TestClient(app).get(f"/projects/{pid}/kata?dari=0&sampai=10").status_code == 401


# ---------------------------------------------------------------- video asli untuk pratinjau editor
def test_video_sumber_pemilik_didukung_range_dan_tanpa_nama_berkas(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    folder = simpan / "projects" / str(pid)
    (folder / "source.mp4.part").write_bytes(b"sisa")                         # sisa unduhan tidak boleh dikirim
    assert klien.get(f"/projects/{pid}/source").status_code == 404
    (folder / "source.mp4").write_bytes(ISI)
    r = klien.get(f"/projects/{pid}/source")
    assert r.status_code == 200 and r.content == ISI and r.headers["content-type"] == "video/mp4"
    assert "source.mp4" not in r.headers.get("content-disposition", "")
    r = klien.get(f"/projects/{pid}/source", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == ISI[10:20]
    assert budi[0].get(f"/projects/{pid}/source").status_code == 404
    assert TestClient(app).get(f"/projects/{pid}/source").status_code == 401
    assert klien.get("/projects/99999/source").status_code == 404


def test_jeda_bawaan_simpan_dan_perlu_render(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert klien.get(f"/projects/{pid}/clips").json()[0]["jeda"] == {"aktif": False, "ambang": 0.6}
    r = klien.put(f"/projects/{pid}/clips/{kid}/jeda", json={"aktif": True, "ambang": 1.2})
    assert r.status_code == 200 and r.json()["jeda"] == {"aktif": True, "ambang": 1.2} and r.json()["subtitle_perlu_render"] is True
    # menyimpan subtitle tidak menghapus pilihan jeda
    r = klien.put(f"/projects/{pid}/clips/{kid}/subtitle", json={"gaya": "kotak"})
    assert r.json()["jeda"] == {"aktif": True, "ambang": 1.2}
    # dimatikan lagi: kembali sama dengan video yang ada (ambang tidak berarti saat mati)
    r = klien.put(f"/projects/{pid}/clips/{kid}/jeda", json={"aktif": False, "ambang": 2.0})
    assert r.json()["jeda"]["aktif"] is False
    klien.put(f"/projects/{pid}/clips/{kid}/subtitle", json={})
    assert klien.get(f"/projects/{pid}/clips").json()[0]["subtitle_perlu_render"] is False


@pytest.mark.parametrize("isi", [{"aktif": "ya"}, {"ambang": 0.1}, {"ambang": 3.5}, {"ambang": "x"}, {"ambang": None}])
def test_jeda_isi_tidak_valid(ani, engine, simpan, isi):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    assert klien.put(f"/projects/{pid}/clips/{_id_klip(engine, pid)[0]}/jeda", json=isi).status_code == 422


def test_jeda_syarat_dan_kepemilikan(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert TestClient(app).put(f"/projects/{pid}/clips/{kid}/jeda", json={"aktif": True}).status_code == 401
    assert budi[0].put(f"/projects/{pid}/clips/{kid}/jeda", json={"aktif": True}).status_code == 404
    assert klien.put(f"/projects/{pid}/clips/99999/jeda", json={"aktif": True}).status_code == 404
    with engine.begin() as c:
        c.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i"), {"i": kid})
    assert klien.put(f"/projects/{pid}/clips/{kid}/jeda", json={"aktif": True}).status_code == 409


def test_potongan_manual_simpan_gabung_dan_perlu_render(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert klien.get(f"/projects/{pid}/clips").json()[0]["potong"] == []
    r = klien.put(f"/projects/{pid}/clips/{kid}/potong", json={"selang": [[20, 22], [10, 12], [11.5, 13]]})
    assert r.status_code == 200 and r.json()["potong"] == [[10.0, 13.0], [20.0, 22.0]] and r.json()["subtitle_perlu_render"] is True
    assert klien.put(f"/projects/{pid}/clips/{kid}/subtitle", json={}).json()["potong"] == [[10.0, 13.0], [20.0, 22.0]]
    assert klien.put(f"/projects/{pid}/clips/{kid}/potong", json={"selang": []}).json()["subtitle_perlu_render"] is False


@pytest.mark.parametrize("isi", [{"selang": [[5, 5]]}, {"selang": [[6, 5]]}, {"selang": [[-1, 5]]}, {"selang": [[1]]}, {"selang": "x"}])
def test_potongan_manual_tidak_valid(ani, engine, simpan, isi):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    assert klien.put(f"/projects/{pid}/clips/{_id_klip(engine, pid)[0]}/potong", json=isi).status_code == 422


def test_potongan_manual_syarat_dan_kepemilikan(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert TestClient(app).put(f"/projects/{pid}/clips/{kid}/potong", json={"selang": []}).status_code == 401
    assert budi[0].put(f"/projects/{pid}/clips/{kid}/potong", json={"selang": []}).status_code == 404
    with engine.begin() as c:
        c.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i"), {"i": kid})
    assert klien.put(f"/projects/{pid}/clips/{kid}/potong", json={"selang": []}).status_code == 409


def test_klip_gagal_render_menyertakan_alasan_bukan_pembatalan(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    with engine.begin() as c:
        c.execute(text("UPDATE clips SET status = 'failed' WHERE id = :i"), {"i": kid})
        c.execute(text("INSERT INTO job_queue (type, payload, status, error) VALUES ('render_clip', :p, 'failed', 'FFmpeg gagal: contoh')"),
                  {"p": json.dumps({"project_id": pid, "clip_id": kid, "mulai": 1.0, "akhir": 9.0})})
    k = next(x for x in klien.get(f"/projects/{pid}/clips").json() if x["id"] == kid)
    assert k["galat_render"] == "FFmpeg gagal: contoh"
    with engine.begin() as c:
        c.execute(text("INSERT INTO job_queue (type, payload, status, error) VALUES ('render_clip', :p, 'failed', 'dibatalkan')"),
                  {"p": json.dumps({"project_id": pid, "clip_id": kid, "mulai": 1.0, "akhir": 9.0})})
    k = next(x for x in klien.get(f"/projects/{pid}/clips").json() if x["id"] == kid)
    assert k["galat_render"] is None


def _status_proyek(engine, pid, status):
    with engine.begin() as c:
        c.execute(text("UPDATE projects SET status = :s WHERE id = :i"), {"s": status, "i": pid})


def test_hapus_klip_menghapus_baris_berkas_dan_antrean(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    k1, k2 = _id_klip(engine, pid)
    with engine.begin() as c:
        c.execute(text("INSERT INTO job_queue (type, payload) VALUES ('render_clip', :p)"),
                  {"p": json.dumps({"project_id": pid, "clip_id": k1, "mulai": 1.0, "akhir": 9.0})})
    assert klien.delete(f"/projects/{pid}/clips/{k1}").status_code == 204
    assert [k["id"] for k in klien.get(f"/projects/{pid}/clips").json()] == [k2]
    assert not (simpan / "projects" / str(pid) / "klip_01_9x16.mp4").exists()
    assert (simpan / "projects" / str(pid) / "klip_02_9x16.mp4").exists()                  # klip lain utuh
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM job_queue")).scalar() == 0
    assert klien.delete(f"/projects/{pid}/clips/{k1}").status_code == 404                  # sudah tidak ada


def test_hapus_klip_ditolak_saat_dirender_dan_untuk_orang_lain(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    kid = _id_klip(engine, pid)[0]
    assert TestClient(app).delete(f"/projects/{pid}/clips/{kid}").status_code == 401
    assert budi[0].delete(f"/projects/{pid}/clips/{kid}").status_code == 404
    with engine.begin() as c:
        c.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i"), {"i": kid})
    assert klien.delete(f"/projects/{pid}/clips/{kid}").status_code == 409
    assert len(_id_klip(engine, pid)) == 2


def test_hapus_proyek_menghapus_semua_klip_berkas_dan_antrean(ani, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    lain = _proyek_dengan_klip(engine, simpan, uid)
    _tulis_kata(simpan, pid, [{"w": "a", "s": 1, "e": 2}])
    _status_proyek(engine, pid, "done")
    with engine.begin() as c:
        for isi in ({"project_id": pid}, {"project_id": lain}):
            c.execute(text("INSERT INTO job_queue (type, payload) VALUES ('process_project', :p)"), {"p": json.dumps(isi)})
    assert klien.delete(f"/projects/{pid}").status_code == 204
    assert klien.get(f"/projects/{pid}").status_code == 404
    assert not (simpan / "projects" / str(pid)).exists()
    assert (simpan / "projects" / str(lain) / "klip_01_9x16.mp4").exists()                 # proyek lain tidak tersentuh
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM clips WHERE project_id = :p"), {"p": pid}).scalar() == 0
        assert c.execute(text("SELECT COUNT(*) FROM clips WHERE project_id = :p"), {"p": lain}).scalar() == 2
        assert c.execute(text("SELECT COUNT(*) FROM job_queue")).scalar() == 1


@pytest.mark.parametrize("status", ["queued", "processing"])
def test_hapus_proyek_ditolak_saat_diproses(ani, engine, simpan, status):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _status_proyek(engine, pid, status)
    assert klien.delete(f"/projects/{pid}").status_code == 409
    assert (simpan / "projects" / str(pid)).exists()


def test_hapus_proyek_syarat_kepemilikan_dan_klip_dirender(app, ani, budi, engine, simpan):
    klien, uid = ani
    pid = _proyek_dengan_klip(engine, simpan, uid)
    _status_proyek(engine, pid, "done")
    assert TestClient(app).delete(f"/projects/{pid}").status_code == 401
    assert budi[0].delete(f"/projects/{pid}").status_code == 404
    assert (simpan / "projects" / str(pid)).exists()
    with engine.begin() as c:
        c.execute(text("UPDATE clips SET status = 'rendering' WHERE project_id = :p"), {"p": pid})
    assert klien.delete(f"/projects/{pid}").status_code == 409
    assert klien.delete("/projects/99999").status_code == 404
