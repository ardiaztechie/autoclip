"""db.py: koneksi ke database autoclip (MariaDB di XAMPP) lewat SQLAlchemy."""
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .config import url_database

log = logging.getLogger("autoclip.db")


# Semua kolom waktu di schema.sql bertipe TIMESTAMP, yang dibaca dalam zona waktu sesi. Dipaksa UTC supaya jamnya
# sama di mana pun MariaDB berjalan; tampilan (frontend) mengubahnya ke waktu setempat.
SQL_AWAL_KONEKSI = "SET time_zone = '+00:00'"


def buat_engine(p: dict):
    """Engine TIDAK langsung tersambung; koneksi baru dibuka saat dipakai."""
    return create_engine(url_database(p), pool_pre_ping=True,
                         connect_args={"connect_timeout": 5, "init_command": SQL_AWAL_KONEKSI})


def cek_database(engine) -> dict:
    """{"ok": True, "versi": "..."} atau {"ok": False, "pesan": "..."}.
    Detail galat hanya masuk log, tidak dikirim ke pemanggil (bisa memuat alamat server)."""
    try:
        with engine.connect() as koneksi:
            versi = koneksi.execute(text("SELECT VERSION()")).scalar()
        return {"ok": True, "versi": str(versi)}
    except SQLAlchemyError as e:
        log.warning("cek database gagal: %s", e)
        return {"ok": False, "pesan": "database tidak bisa dihubungi; pastikan MySQL di XAMPP berstatus Running"}
