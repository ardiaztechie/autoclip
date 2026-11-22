"""migrasi.py: menyesuaikan database yang SUDAH ada dengan database/schema.sql terbaru. Aman dijalankan berulang kali.

Menjalankan (dari folder proyek, .venv aktif, MySQL di XAMPP menyala):
    python -m backend.migrasi

Migrasi 1 (2026-11-22): jumlah klip otomatis dan durasi klip.
  - projects.n_clips boleh NULL (NULL = jumlah klip otomatis menurut durasi video)
  - projects.clip_density  ENUM('jarang','sedang','rapat')               bawaan 'sedang'
  - projects.clip_length   ENUM('otomatis','pendek','sedang','panjang')  bawaan 'otomatis'
Data lama tidak diubah: proyek yang sudah ada tetap memakai jumlah klip yang dulu dipilih.
"""
import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import config
from .konteks import GalatKonfigurasi, Konteks

SQL_N_CLIPS_BOLEH_KOSONG = "ALTER TABLE projects MODIFY n_clips TINYINT UNSIGNED NULL DEFAULT NULL"
SQL_KEPADATAN = ("ALTER TABLE projects ADD COLUMN clip_density ENUM('jarang','sedang','rapat') "
                 "NOT NULL DEFAULT 'sedang' AFTER n_clips")
SQL_PANJANG = ("ALTER TABLE projects ADD COLUMN clip_length ENUM('otomatis','pendek','sedang','panjang') "
               "NOT NULL DEFAULT 'otomatis' AFTER clip_density")


def _info_kolom(k, tabel: str, kolom: str):
    """(ada?, boleh_kosong?) untuk satu kolom di database yang sedang dipakai."""
    r = k.execute(text("SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                       "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"),
                  {"t": tabel, "c": kolom}).first()
    return (r is not None, r is not None and str(r[0]).upper() == "YES")


def terapkan(k) -> list:
    """Menerapkan migrasi yang belum ada pada koneksi k; mengembalikan daftar kalimat tentang apa yang dikerjakan."""
    laporan = []
    ada, kosong = _info_kolom(k, "projects", "n_clips")
    if not ada:
        raise RuntimeError("tabel projects tidak punya kolom n_clips; jalankan database/schema.sql dulu")
    if kosong:
        laporan.append("projects.n_clips: sudah boleh kosong (dilewati)")
    else:
        k.execute(text(SQL_N_CLIPS_BOLEH_KOSONG))
        laporan.append("projects.n_clips: sekarang boleh kosong (otomatis)")
    for kolom, sql in (("clip_density", SQL_KEPADATAN), ("clip_length", SQL_PANJANG)):
        if _info_kolom(k, "projects", kolom)[0]:
            laporan.append(f"projects.{kolom}: sudah ada (dilewati)")
        else:
            k.execute(text(sql))
            laporan.append(f"projects.{kolom}: ditambahkan")
    return laporan


def main(argv=None, *, konteks=None) -> int:
    ctx = konteks or Konteks()
    try:
        engine = ctx.engine()
        with engine.begin() as k:
            for baris in terapkan(k):
                print("-", baris)
    except GalatKonfigurasi as e:
        print(f"[GAGAL] {e}")
        return 1
    except SQLAlchemyError as e:
        print("[GAGAL] database tidak bisa dihubungi atau menolak perintah; pastikan MySQL di XAMPP berstatus Running")
        print("        rincian:", str(e).splitlines()[0][:200])
        return 1
    except RuntimeError as e:
        print(f"[GAGAL] {e}")
        return 1
    print("Selesai. Database sudah sesuai schema.sql terbaru.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
