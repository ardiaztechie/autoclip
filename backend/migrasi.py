"""migrasi.py: menyesuaikan database yang SUDAH ada dengan database/schema.sql terbaru. Aman dijalankan berulang kali.

Menjalankan (dari folder proyek, .venv aktif, MySQL di XAMPP menyala):
    python -m backend.migrasi

Migrasi 1 (2026-11-22): jumlah klip otomatis dan durasi klip.
  - projects.n_clips boleh NULL (NULL = jumlah klip otomatis menurut durasi video)
  - projects.clip_density  ENUM('jarang','sedang','rapat')               bawaan 'sedang'
  - projects.clip_length   ENUM('otomatis','pendek','sedang','panjang')  bawaan 'otomatis'
Migrasi 2 (2026-11-23): durasi klip "sangat_panjang" (90-120 detik) dan "ekstra_panjang" (120-180 detik) ditambahkan ke ENUM clip_length.
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
SQL_PANJANG = ("ALTER TABLE projects ADD COLUMN clip_length ENUM('otomatis','pendek','sedang','panjang','sangat_panjang','ekstra_panjang') "
               "NOT NULL DEFAULT 'otomatis' AFTER clip_density")
SQL_PANJANG_SAMPAI_3_MENIT = ("ALTER TABLE projects MODIFY clip_length "
                              "ENUM('otomatis','pendek','sedang','panjang','sangat_panjang','ekstra_panjang') NOT NULL DEFAULT 'otomatis'")


def _info_kolom(k, tabel: str, kolom: str):
    """(ada?, boleh_kosong?) untuk satu kolom di database yang sedang dipakai."""
    r = _baris_kolom(k, tabel, kolom)
    return (r is not None, r is not None and str(r[0]).upper() == "YES")


def _baris_kolom(k, tabel: str, kolom: str):
    return k.execute(text("SELECT IS_NULLABLE, COLUMN_TYPE FROM information_schema.COLUMNS "
                          "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"),
                     {"t": tabel, "c": kolom}).first()


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
    panjang_baru = False
    for kolom, sql in (("clip_density", SQL_KEPADATAN), ("clip_length", SQL_PANJANG)):
        if _info_kolom(k, "projects", kolom)[0]:
            laporan.append(f"projects.{kolom}: sudah ada (dilewati)")
        else:
            k.execute(text(sql))
            laporan.append(f"projects.{kolom}: ditambahkan")
            panjang_baru = panjang_baru or kolom == "clip_length"
    if panjang_baru:
        pass                                              # kolom baru sudah memuat semua pilihan
    elif "ekstra_panjang" in str(_baris_kolom(k, "projects", "clip_length")[1]).lower():
        laporan.append("projects.clip_length: sudah punya 'ekstra_panjang' (dilewati)")
    else:
        k.execute(text(SQL_PANJANG_SAMPAI_3_MENIT))
        laporan.append("projects.clip_length: ditambah pilihan 'sangat_panjang' (sampai 2 menit) dan 'ekstra_panjang' (sampai 3 menit)")
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
