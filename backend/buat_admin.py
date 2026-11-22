"""buat_admin.py: membuat akun ADMIN pertama dari terminal (admin lain dibuat lewat endpoint /admin/users).

Cara pakai (dari folder proyek, .venv aktif, MySQL di XAMPP menyala):
    python -m backend.buat_admin --email kamu@contoh.com --nama "Nama Kamu"
Password diketik dua kali dan TIDAK tampil di layar (itu normal).
"""
import argparse
import getpass
import re
import sys

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from . import pengguna
from .keamanan import hash_password
from .konteks import GalatKonfigurasi, Konteks


def main(argv=None, *, ambil_password=getpass.getpass, konteks=None) -> int:
    ap = argparse.ArgumentParser(description="Membuat akun admin AutoClip.")
    ap.add_argument("--email", required=True)
    ap.add_argument("--nama", required=True)
    arg = ap.parse_args(argv)
    email, nama = arg.email.strip().lower(), arg.nama.strip()
    if not re.match(pengguna.POLA_EMAIL, email) or len(email) > 190:
        print("[GAGAL] Format email tidak valid.")
        return 1
    if not nama or len(nama) > 120:
        print("[GAGAL] Nama harus diisi (maksimal 120 huruf).")
        return 1
    sandi = ambil_password("Password (minimal 8 karakter): ")
    if sandi != ambil_password("Ulangi password: "):
        print("[GAGAL] Kedua password tidak sama.")
        return 1
    if not 8 <= len(sandi) <= 128:
        print("[GAGAL] Password harus 8 sampai 128 karakter.")
        return 1
    try:
        engine = (konteks or Konteks()).engine()
        with engine.begin() as k:
            pengguna.buat(k, email, nama, hash_password(sandi), "admin")
    except GalatKonfigurasi as e:
        print(f"[GAGAL] {e}")
        return 1
    except IntegrityError:
        print("[GAGAL] Email itu sudah terdaftar.")
        return 1
    except SQLAlchemyError:
        print("[GAGAL] Database tidak bisa dihubungi. Pastikan MySQL di XAMPP berstatus Running dan .env benar.")
        return 1
    print(f"[OK] Akun admin dibuat: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
