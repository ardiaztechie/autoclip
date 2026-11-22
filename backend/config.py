"""config.py: pengaturan database untuk backend. Dibaca dari environment atau berkas .env (tidak ikut Git).

Nama variabel sama dengan yang dipakai scripts/cek_koneksi.py:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""
import os
from pathlib import Path

from sqlalchemy.engine import URL

BASE = Path(__file__).resolve().parent.parent


def muat_env(jalur: Path = None) -> None:
    """Memuat .env ke environment (variabel yang sudah ada tidak ditimpa). Tanpa python-dotenv: dilewati."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(jalur or (BASE / ".env"))


def pengaturan_db(env=None) -> dict:
    """Mengembalikan {host, port, user, password, nama}. env bawaan = os.environ."""
    e = os.environ if env is None else env
    try:
        port = int(e.get("DB_PORT", "3306"))
    except ValueError:
        raise ValueError("DB_PORT di .env harus berupa angka, misalnya 3306") from None
    return {
        "host": e.get("DB_HOST", "127.0.0.1"),
        "port": port,
        "user": e.get("DB_USER", "root"),
        "password": e.get("DB_PASSWORD", ""),
        "nama": e.get("DB_NAME", "autoclip"),
    }


def url_database(p: dict) -> URL:
    """Alamat koneksi SQLAlchemy. URL.create menangani karakter khusus (@ : /) pada password."""
    return URL.create("mysql+pymysql", username=p["user"], password=p["password"] or None,
                      host=p["host"], port=p["port"], database=p["nama"], query={"charset": "utf8mb4"})


def pengaturan_sesi(env=None) -> dict:
    """Pengaturan sesi login. SESSION_SECRET kosong = dibuat acak setiap server dinyalakan
    (semua orang keluar saat server dimulai ulang); isi di .env agar sesi bertahan."""
    import secrets

    e = os.environ if env is None else env
    rahasia = e.get("SESSION_SECRET", "").strip()
    acak = not rahasia
    if acak:
        rahasia = secrets.token_hex(32)
    elif len(rahasia) < 32:
        raise ValueError('SESSION_SECRET di .env minimal 32 karakter. Buat dengan: '
                         'python -c "import secrets; print(secrets.token_hex(32))"')
    try:
        hari = float(e.get("SESSION_DAYS", "7"))
    except ValueError:
        raise ValueError("SESSION_DAYS di .env harus berupa angka, misalnya 7") from None
    if hari <= 0:
        raise ValueError("SESSION_DAYS di .env harus lebih dari 0")
    return {"rahasia": rahasia, "acak": acak, "umur": int(hari * 86400),
            "cookie_aman": e.get("COOKIE_SECURE", "0").strip().lower() in ("1", "true", "ya", "yes")}


def pengaturan_unggah(env=None, base=BASE) -> dict:
    """Lokasi penyimpanan dan batas ukuran unggahan. STORAGE_DIR relatif dihitung dari folder proyek."""
    e = os.environ if env is None else env
    folder = Path(e.get("STORAGE_DIR", "./storage"))
    if not folder.is_absolute():
        folder = base / folder
    try:
        mb = float(e.get("MAX_UPLOAD_MB", "2048"))
    except ValueError:
        raise ValueError("MAX_UPLOAD_MB di .env harus berupa angka, misalnya 2048") from None
    if mb <= 0:
        raise ValueError("MAX_UPLOAD_MB di .env harus lebih dari 0")
    return {"folder": folder, "maks_bytes": int(mb * 1024 * 1024)}


def pengaturan_proses(env=None) -> dict:
    """Batas pemrosesan. MAX_DURATION_MIN (menit): bawaan TANPA batas durasi; isi angka > 0 untuk membatasi
    (kosong atau 0 = tanpa batas). maks_durasi_detik None berarti tanpa batas."""
    e = os.environ if env is None else env
    mentah = str(e.get("MAX_DURATION_MIN", "")).strip()
    if mentah == "":
        return {"maks_durasi_detik": None}
    try:
        menit = float(mentah)
    except ValueError:
        raise ValueError("MAX_DURATION_MIN di .env harus berupa angka (menit), atau 0/kosong untuk tanpa batas") from None
    if menit < 0:
        raise ValueError("MAX_DURATION_MIN di .env tidak boleh negatif (0 atau kosong = tanpa batas)")
    return {"maks_durasi_detik": menit * 60 if menit > 0 else None}
