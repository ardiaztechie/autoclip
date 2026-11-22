"""auth.py: login (cookie sesi), logout, siapa yang sedang masuk, dan pembuatan akun oleh admin.

Semua pengecekan "siapa yang masuk" ada di SATU tempat (pengguna_saat_ini). Bila nanti mau diganti
ke token, cukup ubah fungsi itu dan dua endpoint login/logout.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from . import pengguna
from .keamanan import baca_token, buat_token, cek_password, hash_palsu, hash_password

NAMA_COOKIE = "autoclip_sesi"
router = APIRouter()


class Masuk(BaseModel):
    email: str = Field(max_length=190)
    password: str = Field(min_length=1, max_length=128)


class PenggunaBaru(BaseModel):
    email: str = Field(pattern=pengguna.POLA_EMAIL, max_length=190)
    nama: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"

    @field_validator("email", "nama", mode="before")
    @classmethod
    def _pangkas_spasi(cls, nilai):
        return nilai.strip() if isinstance(nilai, str) else nilai


def _konteks(request: Request):
    return request.app.state.konteks


# ---------------------------------------------------------------- pengecekan siapa yang masuk
def pengguna_saat_ini(request: Request) -> dict:
    k = _konteks(request)
    token = request.cookies.get(NAMA_COOKIE)
    uid = baca_token(token, k.sesi()["rahasia"], k.sekarang()) if token else None
    if uid is None:
        raise HTTPException(401, "Belum masuk")
    with k.engine().connect() as koneksi:
        u = pengguna.cari_id(koneksi, uid)
    if u is None or not u["is_active"]:                  # akun dihapus atau dinonaktifkan: sesi lama ikut tidak berlaku
        raise HTTPException(401, "Belum masuk")
    return u


def wajib_admin(u: dict = Depends(pengguna_saat_ini)) -> dict:
    if u["role"] != "admin":
        raise HTTPException(403, "Hanya admin yang boleh melakukan ini")
    return u


# ---------------------------------------------------------------- endpoint
@router.post("/auth/login")
def login(isi: Masuk, request: Request):
    k = _konteks(request)
    email, sekarang = isi.email.strip().lower(), k.sekarang()
    if k.pembatas.terblokir(email, sekarang):
        raise HTTPException(429, "Terlalu banyak percobaan gagal. Coba lagi beberapa menit lagi.")
    with k.engine().connect() as koneksi:
        u = pengguna.cari_email(koneksi, email)
    cocok = cek_password(u["password_hash"] if u else hash_palsu(), isi.password)
    if u is None or not cocok:
        k.pembatas.catat_gagal(email, sekarang)
        raise HTTPException(401, "Email atau password salah")
    if not u["is_active"]:
        raise HTTPException(403, "Akun dinonaktifkan. Hubungi admin.")
    k.pembatas.reset(email)
    sesi = k.sesi()
    jawaban = JSONResponse(pengguna.publik(u))
    jawaban.set_cookie(NAMA_COOKIE, buat_token(u["id"], sesi["rahasia"], sekarang, sesi["umur"]),
                       max_age=sesi["umur"], httponly=True, samesite="lax", secure=sesi["cookie_aman"], path="/")
    return jawaban


@router.post("/auth/logout")
def logout():
    jawaban = JSONResponse({"ok": True})
    jawaban.delete_cookie(NAMA_COOKIE, path="/")
    return jawaban


@router.get("/auth/me")
def saya(u: dict = Depends(pengguna_saat_ini)):
    return pengguna.publik(u)


@router.post("/admin/users", status_code=201)
def buat_pengguna(isi: PenggunaBaru, request: Request, _admin: dict = Depends(wajib_admin)):
    email, nama = isi.email.strip().lower(), isi.nama.strip()
    if not nama:
        raise HTTPException(422, "Nama tidak boleh kosong")
    try:
        with _konteks(request).engine().begin() as koneksi:
            uid = pengguna.buat(koneksi, email, nama, hash_password(isi.password), isi.role)
    except IntegrityError:
        raise HTTPException(409, "Email sudah terdaftar") from None
    return {"id": uid, "email": email, "name": nama, "role": isi.role}


@router.get("/admin/users")
def daftar_pengguna(request: Request, _admin: dict = Depends(wajib_admin)):
    with _konteks(request).engine().connect() as koneksi:
        return pengguna.daftar(koneksi)
