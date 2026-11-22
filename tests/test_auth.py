"""Tes login, sesi, dan akun (backend/auth.py). Database = SQLite di memori; tidak menyentuh MariaDB asli."""
import re
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from backend import auth, config, keamanan, konteks, main, pengguna  # noqa: E402

RAHASIA = "r" * 32
UMUR = 3600
TABEL = """CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""


class Jam:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def hasher_cepat(monkeypatch):
    monkeypatch.setattr(keamanan, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    monkeypatch.setattr(keamanan, "_hash_palsu", None)


@pytest.fixture
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with e.begin() as k:
        k.execute(text(TABEL))
    return e


@pytest.fixture
def jam():
    return Jam()


def _buat_klien(engine, jam):
    ctx = konteks.Konteks(engine=engine, sekarang=jam,
                          sesi={"rahasia": RAHASIA, "acak": False, "umur": UMUR, "cookie_aman": False})
    return TestClient(main.buat_app(lambda: {"ok": True}, konteks=ctx))


@pytest.fixture
def klien(engine, jam):
    return _buat_klien(engine, jam)


def _akun(engine, email, password="password123", role="user", aktif=True, nama="Nama"):
    with engine.begin() as k:
        uid = pengguna.buat(k, email, nama, keamanan.hash_password(password), role)
        if not aktif:
            k.execute(text("UPDATE users SET is_active = 0 WHERE id = :i"), {"i": uid})
    return uid


def _masuk(klien, email, password="password123"):
    return klien.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
def admin(engine, klien):
    _akun(engine, "admin@contoh.com", role="admin", nama="Admin")
    assert _masuk(klien, "admin@contoh.com").status_code == 200
    return klien


# ---------------------------------------------------------------- login
def test_login_berhasil_cookie_aman_dan_tanpa_hash(engine, klien):
    _akun(engine, "a@contoh.com", nama="Ani")
    r = _masuk(klien, "a@contoh.com")
    assert r.status_code == 200
    assert r.json() == {"id": 1, "email": "a@contoh.com", "name": "Ani", "role": "user"}
    assert "password" not in r.text and "argon2" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert auth.NAMA_COOKIE in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert f"max-age={UMUR}" in cookie and "secure" not in cookie


def test_cookie_secure_mengikuti_pengaturan(engine, jam):
    ctx = konteks.Konteks(engine=engine, sekarang=jam,
                          sesi={"rahasia": RAHASIA, "acak": False, "umur": UMUR, "cookie_aman": True})
    _akun(engine, "a@contoh.com")
    c = TestClient(main.buat_app(lambda: {"ok": True}, konteks=ctx), base_url="https://testserver")
    assert "secure" in _masuk(c, "a@contoh.com").headers["set-cookie"].lower()


def test_me_setelah_login(engine, klien):
    _akun(engine, "a@contoh.com", nama="Ani")
    _masuk(klien, "a@contoh.com")
    r = klien.get("/auth/me")
    assert r.status_code == 200 and r.json()["email"] == "a@contoh.com"


def test_me_tanpa_login_dan_dengan_cookie_palsu(klien):
    assert klien.get("/auth/me").status_code == 401
    klien.cookies.set(auth.NAMA_COOKIE, "palsu.palsu")
    assert klien.get("/auth/me").status_code == 401
    klien.cookies.set(auth.NAMA_COOKIE, keamanan.buat_token(1, "rahasia-lain" * 4, 1_000_000, UMUR))
    assert klien.get("/auth/me").status_code == 401


def test_password_salah_dan_email_tidak_ada_pesannya_sama(engine, klien):
    _akun(engine, "a@contoh.com")
    r1 = _masuk(klien, "a@contoh.com", "salah-salah")
    r2 = _masuk(klien, "tidak.ada@contoh.com", "salah-salah")
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json() == {"detail": "Email atau password salah"}
    assert auth.NAMA_COOKIE not in r1.headers.get("set-cookie", "")


def test_email_dinormalkan_saat_login(engine, klien):
    _akun(engine, "a@contoh.com")
    assert _masuk(klien, "  A@Contoh.COM ").status_code == 200


def test_akun_nonaktif_ditolak_setelah_password_benar(engine, klien):
    _akun(engine, "a@contoh.com", aktif=False)
    assert _masuk(klien, "a@contoh.com").status_code == 403
    assert _masuk(klien, "a@contoh.com", "salah-salah").status_code == 401     # tidak membocorkan status akun


def test_login_isi_tidak_valid(klien):
    assert klien.post("/auth/login", json={"email": "a@b.c"}).status_code == 422
    assert klien.post("/auth/login", json={"email": "a@b.c", "password": ""}).status_code == 422
    assert klien.post("/auth/login", json={"email": "a@b.c", "password": "x" * 129}).status_code == 422


# ---------------------------------------------------------------- pembatas
def test_login_diblokir_setelah_lima_kali_gagal_lalu_pulih(engine, klien, jam):
    _akun(engine, "a@contoh.com")
    for _ in range(5):
        assert _masuk(klien, "a@contoh.com", "salah-salah").status_code == 401
    assert _masuk(klien, "a@contoh.com").status_code == 429          # password benar pun ditolak saat diblokir
    jam.t += 901
    assert _masuk(klien, "a@contoh.com").status_code == 200


def test_login_berhasil_mereset_hitungan_gagal(engine, klien):
    _akun(engine, "a@contoh.com")
    for _ in range(4):
        _masuk(klien, "a@contoh.com", "salah-salah")
    assert _masuk(klien, "a@contoh.com").status_code == 200
    for _ in range(4):
        assert _masuk(klien, "a@contoh.com", "salah-salah").status_code == 401


def test_email_tidak_ada_juga_dibatasi(klien):
    for _ in range(5):
        _masuk(klien, "hantu@contoh.com", "salah-salah")
    assert _masuk(klien, "hantu@contoh.com", "salah-salah").status_code == 429


# ---------------------------------------------------------------- sesi
def test_logout_menghapus_cookie(engine, klien):
    _akun(engine, "a@contoh.com")
    _masuk(klien, "a@contoh.com")
    r = klien.post("/auth/logout")
    assert r.status_code == 200 and auth.NAMA_COOKIE in r.headers["set-cookie"]
    assert klien.get("/auth/me").status_code == 401


def test_sesi_kedaluwarsa(engine, klien, jam):
    _akun(engine, "a@contoh.com")
    _masuk(klien, "a@contoh.com")
    jam.t += UMUR - 1
    assert klien.get("/auth/me").status_code == 200
    jam.t += 1
    assert klien.get("/auth/me").status_code == 401


def test_akun_dinonaktifkan_atau_dihapus_saat_sesi_berjalan(engine, klien):
    uid = _akun(engine, "a@contoh.com")
    _masuk(klien, "a@contoh.com")
    with engine.begin() as k:
        k.execute(text("UPDATE users SET is_active = 0 WHERE id = :i"), {"i": uid})
    assert klien.get("/auth/me").status_code == 401
    with engine.begin() as k:
        k.execute(text("UPDATE users SET is_active = 1 WHERE id = :i"), {"i": uid})
        assert klien.get("/auth/me").status_code == 200
        k.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
    assert klien.get("/auth/me").status_code == 401


# ---------------------------------------------------------------- admin membuat akun
def test_admin_membuat_akun_yang_lalu_bisa_login(engine, admin):
    r = admin.post("/admin/users", json={"email": " Baru@Contoh.com ", "nama": " Budi ", "password": "password-baru"})
    assert r.status_code == 201
    assert r.json() == {"id": 2, "email": "baru@contoh.com", "name": "Budi", "role": "user"}
    with engine.connect() as k:
        tersimpan = pengguna.cari_email(k, "baru@contoh.com")
    assert tersimpan["password_hash"].startswith("$argon2") and "password-baru" not in tersimpan["password_hash"]
    admin.post("/auth/logout")
    assert _masuk(admin, "baru@contoh.com", "password-baru").status_code == 200


def test_admin_bisa_membuat_admin_lain(admin):
    r = admin.post("/admin/users", json={"email": "b@contoh.com", "nama": "B", "password": "password-baru", "role": "admin"})
    assert r.status_code == 201 and r.json()["role"] == "admin"


def test_pengguna_biasa_dan_tamu_tidak_boleh_membuat_akun(engine, klien):
    isi = {"email": "x@contoh.com", "nama": "X", "password": "password123"}
    assert klien.post("/admin/users", json=isi).status_code == 401
    _akun(engine, "a@contoh.com")
    _masuk(klien, "a@contoh.com")
    assert klien.post("/admin/users", json=isi).status_code == 403
    assert klien.get("/admin/users").status_code == 403


def test_email_ganda_ditolak_tanpa_membedakan_huruf(admin):
    isi = {"email": "ADMIN@contoh.com", "nama": "X", "password": "password123"}
    assert admin.post("/admin/users", json=isi).status_code == 409


@pytest.mark.parametrize("isi", [
    {"email": "bukan-email", "nama": "X", "password": "password123"},
    {"email": "a@b", "nama": "X", "password": "password123"},
    {"email": "x@contoh.com", "nama": "", "password": "password123"},
    {"email": "x@contoh.com", "nama": "   ", "password": "password123"},
    {"email": "x@contoh.com", "nama": "X", "password": "pendek"},
    {"email": "x@contoh.com", "nama": "X", "password": "password123", "role": "superadmin"},
])
def test_isi_akun_baru_tidak_valid(admin, isi):
    assert admin.post("/admin/users", json=isi).status_code == 422


def test_daftar_pengguna_tanpa_hash(admin):
    admin.post("/admin/users", json={"email": "b@contoh.com", "nama": "B", "password": "password123"})
    r = admin.get("/admin/users")
    assert r.status_code == 200 and [u["email"] for u in r.json()] == ["admin@contoh.com", "b@contoh.com"]
    assert "password" not in r.text and "argon2" not in r.text
    assert set(r.json()[0]) == {"id", "email", "name", "role", "is_active", "created_at"}


# ---------------------------------------------------------------- galat infrastruktur
class _EngineMati:
    def connect(self):
        raise OperationalError("SELECT 1", {}, Exception("password=RAHASIA host=10.0.0.5"))

    begin = connect


def test_database_mati_memberi_503_tanpa_bocor(jam):
    ctx = konteks.Konteks(engine=_EngineMati(), sekarang=jam,
                          sesi={"rahasia": RAHASIA, "acak": False, "umur": UMUR, "cookie_aman": False})
    c = TestClient(main.buat_app(lambda: {"ok": True}, konteks=ctx))
    r = _masuk(c, "a@contoh.com")
    assert r.status_code == 503 and "XAMPP" in r.json()["detail"]
    assert "RAHASIA" not in r.text and "10.0.0.5" not in r.text
    assert c.get("/auth/me").status_code == 401                      # tanpa cookie, tak perlu menyentuh database


def test_rahasia_sesi_pendek_memberi_503_dengan_petunjuk(engine, jam, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "pendek")
    _akun(engine, "a@contoh.com")
    ctx = konteks.Konteks(engine=engine, sekarang=jam, muat_env=lambda: None)
    r = _masuk(TestClient(main.buat_app(lambda: {"ok": True}, konteks=ctx)), "a@contoh.com")
    assert r.status_code == 503 and "SESSION_SECRET" in r.json()["detail"]


def test_tanpa_rahasia_dibuat_acak_dan_login_tetap_jalan(engine, jam, monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    _akun(engine, "a@contoh.com")
    ctx = konteks.Konteks(engine=engine, sekarang=jam, muat_env=lambda: None)
    c = TestClient(main.buat_app(lambda: {"ok": True}, konteks=ctx))
    assert _masuk(c, "a@contoh.com").status_code == 200 and c.get("/auth/me").status_code == 200


# ---------------------------------------------------------------- tabel di tes sama dengan schema.sql
def test_kolom_users_yang_dipakai_ada_di_schema_sql():
    sql = (Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
    blok = re.search(r"CREATE TABLE IF NOT EXISTS users \((.*?)\) ENGINE", sql, re.S).group(1)
    kolom = set(re.findall(r"^\s{2}(\w+)\s", blok, re.M))
    assert {"id", "email", "name", "password_hash", "role", "is_active", "created_at"} <= kolom
    assert "ENUM('admin','user')" in blok.replace(" ", "")
