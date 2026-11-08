"""cek_koneksi.py: memastikan aplikasi bisa tersambung ke database autoclip.

Cara pakai (dari folder proyek, dengan .venv aktif):
    python scripts/cek_koneksi.py

Skrip ini hanya MEMBACA. Tidak mengubah atau menghapus apa pun di database.
"""
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# Folder proyek = satu tingkat di atas folder scripts
BASE = Path(__file__).resolve().parent.parent
ENV_FILE = BASE / ".env"

# Sepuluh tabel yang dibuat oleh database/schema.sql
TABEL_WAJIB = [
    "clip_elements", "clip_subtitles", "clips", "job_metrics", "job_queue",
    "landing_sections", "media_assets", "projects", "transcripts", "users",
]


def laporkan(ok, teks):
    print(("[OK]    " if ok else "[GAGAL] ") + teks)


def jelaskan_error(kode, pesan):
    """Mengubah kode error MySQL menjadi saran yang mudah dipahami."""
    saran = {
        2002: "Server tidak bisa dihubungi. Pastikan MySQL di XAMPP berstatus hijau (Running).",
        2003: "Server tidak bisa dihubungi. Pastikan MySQL di XAMPP menyala dan DB_PORT di .env benar.",
        1045: "Nama pengguna atau password salah. Periksa DB_USER dan DB_PASSWORD di .env.",
        1044: "Pengguna ini tidak boleh membuka database tersebut. Periksa ejaan DB_NAME di .env.",
        1049: "Database tidak ditemukan. Periksa DB_NAME di .env, atau impor ulang schema.sql.",
    }
    return saran.get(kode, f"Error tidak dikenal (kode {kode}). Salin pesan di atas dan kirim ke mentor.")


def main():
    if not ENV_FILE.exists():
        laporkan(False, "File .env tidak ditemukan di folder proyek.")
        print("        Jalankan dulu: copy .env.example .env")
        return 1

    load_dotenv(ENV_FILE)
    host = os.getenv("DB_HOST", "127.0.0.1")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    nama_db = os.getenv("DB_NAME", "autoclip")
    try:
        port = int(os.getenv("DB_PORT", "3306"))
    except ValueError:
        laporkan(False, "DB_PORT di .env harus berupa angka, misalnya 3306.")
        return 1

    print("Memeriksa koneksi database...")
    print(f"  Server   : {host}:{port}")
    print(f"  Pengguna : {user}")
    print(f"  Database : {nama_db}")
    print()

    # 1) Sambungkan ke server dan database
    try:
        koneksi = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=nama_db, charset="utf8mb4", connect_timeout=5,
        )
    except pymysql.err.OperationalError as e:
        kode = e.args[0] if e.args else 0
        laporkan(False, f"Gagal tersambung: {e}")
        print("        " + jelaskan_error(kode, str(e)))
        return 1
    except Exception as e:  # noqa: BLE001
        laporkan(False, f"Gagal tersambung: {e}")
        return 1

    masalah = 0
    with koneksi:
        with koneksi.cursor() as c:
            # 2) Versi server
            c.execute("SELECT VERSION()")
            laporkan(True, f"Tersambung ke server: {c.fetchone()[0]}")

            # 3) Daftar tabel
            c.execute("SHOW TABLES")
            ada = {baris[0] for baris in c.fetchall()}
            laporkan(True, f"Database '{nama_db}' ditemukan dengan {len(ada)} tabel")

            hilang = [t for t in TABEL_WAJIB if t not in ada]
            if hilang:
                masalah += 1
                laporkan(False, "Tabel yang belum ada: " + ", ".join(hilang))
                print("        Impor ulang database/schema.sql lewat phpMyAdmin.")
            else:
                laporkan(True, f"Semua {len(TABEL_WAJIB)} tabel yang dibutuhkan ada")

            # 4) Data awal landing page (dibuat oleh schema.sql)
            if "landing_sections" in ada:
                c.execute("SELECT COUNT(*) FROM landing_sections")
                jumlah = c.fetchone()[0]
                if jumlah >= 5:
                    laporkan(True, f"Data awal landing page: {jumlah} bagian")
                else:
                    masalah += 1
                    laporkan(False, f"Data awal landing page hanya {jumlah} bagian (seharusnya 5)")

    print()
    if masalah:
        print("ADA YANG PERLU DIPERBAIKI. Lihat tanda [GAGAL] di atas.")
        return 1
    print("SEMUA SIAP. Aplikasi bisa tersambung ke database.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
