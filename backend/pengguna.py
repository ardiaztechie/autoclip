"""pengguna.py: akses tabel users. Hanya SQL biasa (text), supaya mudah dibaca dan dites."""
from sqlalchemy import text

POLA_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_KOLOM = "id, email, name, password_hash, role, is_active"


def _baris(r):
    if r is None:
        return None
    d = dict(r._mapping)
    d["is_active"] = bool(d["is_active"])
    return d


def cari_email(k, email: str):
    return _baris(k.execute(text(f"SELECT {_KOLOM} FROM users WHERE email = :e"), {"e": email}).first())


def cari_id(k, uid: int):
    return _baris(k.execute(text(f"SELECT {_KOLOM} FROM users WHERE id = :i"), {"i": uid}).first())


def buat(k, email: str, nama: str, password_hash: str, role: str) -> int:
    """Menambah akun; mengembalikan id. Email ganda memunculkan sqlalchemy.exc.IntegrityError."""
    hasil = k.execute(text("INSERT INTO users (email, name, password_hash, role) VALUES (:e, :n, :h, :r)"),
                      {"e": email, "n": nama, "h": password_hash, "r": role})
    return int(hasil.lastrowid)


def daftar(k) -> list:
    baris = k.execute(text("SELECT id, email, name, role, is_active, created_at FROM users ORDER BY id")).all()
    return [{"id": b.id, "email": b.email, "name": b.name, "role": b.role,
             "is_active": bool(b.is_active), "created_at": str(b.created_at)} for b in baris]


def publik(u: dict) -> dict:
    """Bagian akun yang boleh dikirim ke browser (tanpa hash password)."""
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"]}


def kuota_proyek(k, uid: int) -> int:
    """Batas jumlah proyek akun ini (kolom quota_projects)."""
    return int(k.execute(text("SELECT quota_projects FROM users WHERE id = :i"), {"i": uid}).scalar())
