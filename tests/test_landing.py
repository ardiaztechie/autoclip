"""Tes landing page + CMS (backend/landing.py). Database = SQLite di memori."""
import json

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from backend import keamanan, konteks, landing, main, pengguna  # noqa: E402

RAHASIA = "r" * 32
TABEL = [
    """CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
       password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', is_active INTEGER NOT NULL DEFAULT 1,
       created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE landing_sections (section_key TEXT PRIMARY KEY, content TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
       is_visible INTEGER NOT NULL DEFAULT 1, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
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


def _klien(engine):
    ctx = konteks.Konteks(engine=engine, sekarang=lambda: 1_000_000.0,
                          sesi={"rahasia": RAHASIA, "acak": False, "umur": 3600, "cookie_aman": False})
    return TestClient(main.buat_app(lambda: {"ok": True}, konteks=ctx))


def _masuk_sebagai(engine, role):
    klien = _klien(engine)
    with engine.begin() as k:
        pengguna.buat(k, f"{role}@contoh.com", role, keamanan.hash_password("password123"), role)
    assert klien.post("/auth/login", json={"email": f"{role}@contoh.com", "password": "password123"}).status_code == 200
    return klien


@pytest.fixture
def admin(engine):
    return _masuk_sebagai(engine, "admin")


def test_landing_publik_memakai_bawaan_bila_tabel_kosong_dan_tanpa_login(engine):
    r = _klien(engine).get("/landing")
    assert r.status_code == 200
    assert [b["key"] for b in r.json()] == ["hero", "fitur", "cara_kerja", "faq", "footer"]
    assert r.json()[0]["content"] == landing.BAWAAN["hero"]


def test_landing_tanpa_tabel_tetap_bawaan():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert len(_klien(e).get("/landing").json()) == 5


def test_admin_menyimpan_bagian_dan_pengunjung_melihatnya(engine, admin):
    isi = {"title": "Judul baru", "subtitle": "Sub", "cta_text": "Mulai"}
    r = admin.put("/admin/landing/hero", json={"content": isi, "is_visible": True, "sort_order": 1})
    assert r.status_code == 200 and r.json()["content"] == isi
    publik = _klien(engine).get("/landing").json()
    assert publik[0] == {"key": "hero", "content": isi}
    admin.put("/admin/landing/hero", json={"content": {**isi, "title": "Lagi"}, "is_visible": True, "sort_order": 1})   # perbarui, bukan dobel
    with engine.connect() as k:
        assert k.execute(text("SELECT COUNT(*) FROM landing_sections")).scalar() == 1


def test_sembunyikan_dan_urutan_bagian(engine, admin):
    admin.put("/admin/landing/faq", json={"content": landing.BAWAAN["faq"], "is_visible": False, "sort_order": 4})
    admin.put("/admin/landing/footer", json={"content": landing.BAWAAN["footer"], "is_visible": True, "sort_order": 0})
    publik = [b["key"] for b in _klien(engine).get("/landing").json()]
    assert "faq" not in publik and publik[0] == "footer"
    semua = admin.get("/admin/landing").json()
    assert [b["key"] for b in semua][:1] == ["footer"] and next(b for b in semua if b["key"] == "faq")["is_visible"] is False
    assert all("bawaan" in b for b in semua)


@pytest.mark.parametrize("kunci,isi", [
    ("hero", {"title": "", "subtitle": "x", "cta_text": "x"}),
    ("hero", {"title": "x" * 121, "subtitle": "x", "cta_text": "x"}),
    ("hero", {"title": "x", "subtitle": "x", "cta_text": "x", "ekstra": 1}),
    ("fitur", {"items": [{"title": "a", "text": "b"}] * 9}),
    ("fitur", {"items": [{"title": "", "text": "b"}]}),
    ("cara_kerja", {"steps": ["ok", "  "]}),
    ("cara_kerja", {"steps": ["x" * 151]}),
    ("faq", {"items": [{"q": "q"}]}),
    ("footer", {"text": "x" * 201}),
    ("footer", {"text": 5}),
])
def test_isi_tidak_valid_ditolak(admin, kunci, isi):
    assert admin.put(f"/admin/landing/{kunci}", json={"content": isi, "is_visible": True, "sort_order": 1}).status_code == 422


def test_kunci_tidak_dikenal_dan_urutan_tidak_valid(admin):
    assert admin.put("/admin/landing/lain", json={"content": {}, "sort_order": 1}).status_code == 404
    assert admin.put("/admin/landing/footer", json={"content": {"text": "x"}, "sort_order": -1}).status_code == 422


def test_hanya_admin_boleh_mengubah(engine):
    assert _klien(engine).put("/admin/landing/footer", json={"content": {"text": "x"}, "sort_order": 1}).status_code == 401
    biasa = _masuk_sebagai(engine, "user")
    assert biasa.put("/admin/landing/footer", json={"content": {"text": "x"}, "sort_order": 1}).status_code == 403
    assert biasa.get("/admin/landing").status_code == 403
    assert _klien(engine).get("/admin/landing").status_code == 401


def test_isi_rusak_di_database_jatuh_ke_bawaan_dan_tidak_merusak_landing(engine):
    with engine.begin() as k:
        k.execute(text("INSERT INTO landing_sections (section_key, content, sort_order) VALUES ('hero', '{rusak', 1)"))
        k.execute(text("INSERT INTO landing_sections (section_key, content, sort_order) VALUES ('footer', :c, 2)"),
                  {"c": json.dumps({"text": 123})})
    publik = {b["key"]: b["content"] for b in _klien(engine).get("/landing").json()}
    assert publik["hero"] == landing.BAWAAN["hero"] and publik["footer"] == landing.BAWAAN["footer"]


def test_bawaan_sama_dengan_isi_awal_di_schema_sql():
    import re
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "database" / "schema.sql").read_text(encoding="utf-8")
    for kunci in landing.KUNCI:
        m = re.search(rf"\('{kunci}',\s*'(\{{.*?\}})',\s*\d+\)", sql, re.S)
        assert m, kunci
        assert json.loads(m.group(1)) == landing.BAWAAN[kunci], kunci
