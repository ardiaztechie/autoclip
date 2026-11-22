"""Tes backend/buat_admin.py (pembuatan admin pertama dari terminal). Database = SQLite di memori."""
import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from backend import buat_admin, keamanan, konteks, pengguna


TABEL = """CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""


@pytest.fixture(autouse=True)
def hasher_cepat(monkeypatch):
    monkeypatch.setattr(keamanan, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture
def ctx():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with e.begin() as k:
        k.execute(text(TABEL))
    return konteks.Konteks(engine=e)


def _sandi(*urutan):
    it = iter(urutan)
    return lambda prompt: next(it)


def _jalankan(ctx, *sandi, email="Admin@Contoh.com", nama=" Admin "):
    return buat_admin.main(["--email", email, "--nama", nama], ambil_password=_sandi(*sandi), konteks=ctx)


def test_membuat_admin(ctx, capsys):
    assert _jalankan(ctx, "password123", "password123") == 0
    with ctx.engine().connect() as k:
        u = pengguna.cari_email(k, "admin@contoh.com")
    assert u["role"] == "admin" and u["name"] == "Admin" and u["is_active"] is True
    assert keamanan.cek_password(u["password_hash"], "password123") and "password123" not in u["password_hash"]
    assert "[OK]" in capsys.readouterr().out


@pytest.mark.parametrize("sandi,potongan", [(("password123", "beda-sekali"), "tidak sama"),
                                            (("pendek", "pendek"), "8 sampai 128"),
                                            (("x" * 129, "x" * 129), "8 sampai 128")])
def test_password_tidak_valid_tidak_membuat_akun(ctx, capsys, sandi, potongan):
    assert _jalankan(ctx, *sandi) == 1
    assert potongan in capsys.readouterr().out
    with ctx.engine().connect() as k:
        assert k.execute(text("SELECT COUNT(*) FROM users")).scalar() == 0


@pytest.mark.parametrize("email,nama", [("bukan-email", "A"), ("a@b", "A"), ("a@contoh.com", "   ")])
def test_email_atau_nama_tidak_valid(ctx, email, nama):
    assert _jalankan(ctx, "password123", "password123", email=email, nama=nama) == 1


def test_email_ganda(ctx, capsys):
    assert _jalankan(ctx, "password123", "password123") == 0
    assert _jalankan(ctx, "password123", "password123") == 1
    assert "sudah terdaftar" in capsys.readouterr().out


def test_database_mati(capsys):
    class Mati:
        def begin(self):
            raise OperationalError("x", {}, Exception("rahasia"))

    assert _jalankan(konteks.Konteks(engine=Mati()), "password123", "password123") == 1
    out = capsys.readouterr().out
    assert "XAMPP" in out and "rahasia" not in out


def test_konfigurasi_salah(monkeypatch, capsys):
    monkeypatch.setenv("DB_PORT", "abc")
    assert _jalankan(konteks.Konteks(muat_env=lambda: None), "password123", "password123") == 1
    assert "DB_PORT" in capsys.readouterr().out
