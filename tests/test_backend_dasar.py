"""Tes backend dasar (config, db, /health). TIDAK menyambung ke MariaDB sungguhan: engine dan pemeriksa dipalsukan."""
import logging

import pytest
from sqlalchemy.exc import OperationalError

from backend import config, db, konteks, main


# ---------------------------------------------------------------- config
def test_pengaturan_bawaan():
    assert config.pengaturan_db({}) == {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "", "nama": "autoclip"}


def test_pengaturan_dari_env():
    env = {"DB_HOST": "h", "DB_PORT": "3307", "DB_USER": "u", "DB_PASSWORD": "p", "DB_NAME": "n"}
    assert config.pengaturan_db(env) == {"host": "h", "port": 3307, "user": "u", "password": "p", "nama": "n"}


def test_port_bukan_angka_ditolak_dengan_pesan_jelas():
    with pytest.raises(ValueError, match="DB_PORT"):
        config.pengaturan_db({"DB_PORT": "abc"})


def test_url_database_bagian_dan_karakter_khusus_password():
    p = {"host": "127.0.0.1", "port": 3306, "user": "u", "password": "p@ss:w/ord", "nama": "autoclip"}
    url = config.url_database(p)
    assert url.drivername == "mysql+pymysql" and url.host == "127.0.0.1" and url.port == 3306
    assert url.database == "autoclip" and url.username == "u" and url.query["charset"] == "utf8mb4"
    assert url.password == "p@ss:w/ord"                                  # nilai asli tetap utuh
    assert "p@ss:w/ord" not in url.render_as_string(hide_password=False)  # tetapi di teks alamat di-escape
    assert "p@ss" not in str(url)                                        # dan str() menyembunyikan password


def test_url_database_tanpa_password():
    url = config.url_database({"host": "h", "port": 1, "user": "root", "password": "", "nama": "d"})
    assert url.password is None


def test_muat_env_tidak_menimpa_variabel_yang_sudah_ada(tmp_path, monkeypatch):
    berkas = tmp_path / ".env"
    berkas.write_text("DB_HOST=dari_file\nDB_NAME=dari_file\n", encoding="utf-8")
    monkeypatch.setenv("DB_HOST", "dari_env")
    monkeypatch.delenv("DB_NAME", raising=False)
    config.muat_env(berkas)
    assert config.pengaturan_db()["host"] == "dari_env" and config.pengaturan_db()["nama"] == "dari_file"


def test_muat_env_berkas_tidak_ada_tidak_error(tmp_path):
    config.muat_env(tmp_path / "tidak_ada.env")


# ---------------------------------------------------------------- db
class _Hasil:
    def __init__(self, nilai):
        self._n = nilai

    def scalar(self):
        return self._n


class _Koneksi:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        assert "VERSION" in str(sql)
        return _Hasil("10.4.32-MariaDB")


class _EngineSehat:
    def connect(self):
        return _Koneksi()


class _EngineMati:
    def connect(self):
        raise OperationalError("SELECT 1", {}, Exception("password=RAHASIA host=10.0.0.5"))


def test_cek_database_sehat():
    assert db.cek_database(_EngineSehat()) == {"ok": True, "versi": "10.4.32-MariaDB"}


def test_cek_database_mati_tidak_membocorkan_detail(caplog):
    with caplog.at_level(logging.WARNING, logger="autoclip.db"):
        hasil = db.cek_database(_EngineMati())
    assert hasil["ok"] is False and "XAMPP" in hasil["pesan"]
    assert "RAHASIA" not in str(hasil) and "10.0.0.5" not in str(hasil)
    assert "cek database gagal" in caplog.text                      # detail tetap ada di log


def test_buat_engine_tidak_langsung_menyambung():
    engine = db.buat_engine({"host": "192.0.2.1", "port": 3306, "user": "u", "password": "p", "nama": "d"})
    assert engine.url.host == "192.0.2.1"                           # belum ada sambungan yang dicoba


# ---------------------------------------------------------------- /health
@pytest.fixture
def klien():
    pytest.importorskip("httpx")                                    # TestClient butuh httpx
    from fastapi.testclient import TestClient

    def buat(cek):
        return TestClient(main.buat_app(cek))

    return buat


def test_health_sehat(klien):
    r = klien(lambda: {"ok": True, "versi": "10.4.32-MariaDB"}).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": {"ok": True, "versi": "10.4.32-MariaDB"}}


def test_health_database_bermasalah_memberi_503(klien):
    r = klien(lambda: {"ok": False, "pesan": "mati"}).get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "bermasalah", "database": {"ok": False, "pesan": "mati"}}


def test_alamat_lain_404(klien):
    assert klien(lambda: {"ok": True}).get("/tidak-ada").status_code == 404


def test_pemeriksa_bawaan_port_salah_dilaporkan_bukan_crash(klien, monkeypatch):
    monkeypatch.setenv("DB_PORT", "abc")
    r = klien_bawaan(klien).get("/health")
    assert r.status_code == 503 and "DB_PORT" in r.json()["database"]["pesan"]


def test_pemeriksa_bawaan_membuat_engine_sekali(klien, monkeypatch):
    dibuat = []
    monkeypatch.setattr(konteks, "buat_engine", lambda p: dibuat.append(p) or _EngineSehat())
    c = klien_bawaan(klien)
    assert c.get("/health").status_code == 200 and c.get("/health").status_code == 200
    assert len(dibuat) == 1


def klien_bawaan(klien):
    """Aplikasi dengan pemeriksa bawaan; .env asli tidak boleh ikut terbaca."""
    from fastapi.testclient import TestClient
    return TestClient(main.buat_app(konteks=konteks.Konteks(muat_env=lambda: None)))


def test_aplikasi_bawaan_tidak_menyambung_saat_diimpor():
    assert "/health" in main.app.openapi()["paths"]


def test_koneksi_mysql_memakai_zona_waktu_utc(monkeypatch):
    """Frontend menganggap waktu dari server adalah UTC; MariaDB XAMPP memakai zona waktu Windows kecuali dipaksa."""
    diterima = {}
    monkeypatch.setattr(db, "create_engine", lambda url, **kw: diterima.update(kw))
    db.buat_engine({"host": "h", "port": 1, "user": "u", "password": "", "nama": "d"})
    assert diterima["connect_args"]["init_command"] == "SET time_zone = '+00:00'"
    assert diterima["connect_args"]["connect_timeout"] == 5 and diterima["pool_pre_ping"] is True
