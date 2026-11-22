"""keamanan.py: hash password (Argon2), token sesi bertanda tangan (HMAC), dan pembatas percobaan login.

Tanpa dependensi baru: argon2-cffi sudah ada di requirements.txt; sisanya pustaka standar Python.
"""
import base64
import hashlib
import hmac
import json

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()           # parameter bawaan argon2-cffi (aman untuk penggunaan umum)
_hash_palsu = None


# ---------------------------------------------------------------- password
def hash_password(password: str) -> str:
    """Acakan satu arah (dengan garam acak). Password asli tidak pernah disimpan."""
    return _hasher.hash(password)


def cek_password(hash_tersimpan: str, password: str) -> bool:
    try:
        return bool(_hasher.verify(hash_tersimpan, password))
    except (VerificationError, InvalidHashError):
        return False


def hash_palsu() -> str:
    """Hash tiruan untuk email yang tidak ada: waktu pengecekannya sama dengan email yang ada,
    sehingga penyerang tidak bisa menebak email mana yang terdaftar dari lamanya respons."""
    global _hash_palsu
    if _hash_palsu is None:
        _hash_palsu = hash_password("password-tiruan-untuk-pengaman-waktu")
    return _hash_palsu


# ---------------------------------------------------------------- token sesi
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


def _tanda(isi: str, rahasia: str) -> bytes:
    return hmac.new(rahasia.encode("utf-8"), isi.encode("ascii"), hashlib.sha256).digest()


def buat_token(uid: int, rahasia: str, sekarang: float, umur: int) -> str:
    """Token = isi (id pengguna + waktu kedaluwarsa) + tanda tangan HMAC. Tanpa rahasia, tidak bisa dipalsukan."""
    isi = _b64(json.dumps({"uid": uid, "exp": int(sekarang + umur)}, separators=(",", ":")).encode("utf-8"))
    return isi + "." + _b64(_tanda(isi, rahasia))


def baca_token(token, rahasia: str, sekarang: float):
    """Mengembalikan id pengguna bila token asli dan belum kedaluwarsa; selain itu None."""
    try:
        isi, tanda = token.split(".")
        if not hmac.compare_digest(_unb64(tanda), _tanda(isi, rahasia)):
            return None
        data = json.loads(_unb64(isi))
        uid, exp = data["uid"], data["exp"]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if isinstance(uid, bool) or not isinstance(uid, int) or isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return uid if exp > sekarang else None


# ---------------------------------------------------------------- pembatas login
class PembatasLogin:
    """Maksimal `maks` percobaan GAGAL per kunci (email) dalam `jendela` detik. Disimpan di memori
    (hilang saat server dimulai ulang). Catatan: orang lain bisa mengunci email tertentu sementara
    dengan sengaja salah memasukkan password; untuk penggunaan lokal skripsi ini bisa diterima."""

    def __init__(self, maks: int = 5, jendela: int = 900):
        self.maks, self.jendela = maks, jendela
        self._gagal = {}

    def _segar(self, kunci, sekarang):
        daftar = [t for t in self._gagal.get(kunci, []) if t > sekarang - self.jendela]
        if daftar:
            self._gagal[kunci] = daftar
        else:
            self._gagal.pop(kunci, None)
        return daftar

    def terblokir(self, kunci: str, sekarang: float) -> bool:
        return len(self._segar(kunci, sekarang)) >= self.maks

    def catat_gagal(self, kunci: str, sekarang: float) -> None:
        self._segar(kunci, sekarang)
        self._gagal.setdefault(kunci, []).append(sekarang)

    def reset(self, kunci: str) -> None:
        self._gagal.pop(kunci, None)
