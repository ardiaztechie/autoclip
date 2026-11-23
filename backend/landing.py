"""landing.py: isi landing page yang bisa diedit admin (CMS sederhana). Tabel landing_sections (lihat database/schema.sql).

Publik: GET /landing -> bagian yang tampil, urut menurut sort_order.
Admin : GET /admin/landing (semua bagian + isi bawaan), PUT /admin/landing/{kunci} (isi, tampil/sembunyi, urutan).
Isi tiap bagian divalidasi per jenis (panjang dibatasi), jadi admin tidak bisa menyimpan bentuk yang merusak halaman.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .auth import wajib_admin

router = APIRouter()

KUNCI = ("hero", "fitur", "cara_kerja", "faq", "footer")

BAWAAN = {
    "hero": {"title": "Ubah video panjang menjadi clip pendek", "subtitle": "Otomatis, lengkap dengan subtitle, judul, dan caption.",
             "cta_text": "Masuk"},
    "fitur": {"items": [
        {"title": "Clip otomatis", "text": "Bagian menarik dipilih dan dipotong untuk kamu."},
        {"title": "Fokus ke wajah", "text": "Bingkai mengikuti pembicara dan zoom secara halus."},
        {"title": "Siap diedit", "text": "Potong seperti di CapCut, koreksi subtitle, ganti judul."}]},
    "cara_kerja": {"steps": ["Unggah video atau tempel tautan", "Tunggu proses selesai", "Edit seperlunya lalu unduh"]},
    "faq": {"items": [{"q": "Berapa lama video maksimal?", "a": "Tidak ada batas durasi; video yang lebih panjang hanya diproses lebih lama."}]},
    "footer": {"text": "Proyek skripsi Teknik Informatika"},
}
URUTAN_BAWAAN = {k: i for i, k in enumerate(KUNCI, start=1)}


class _Ketat(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Hero(_Ketat):
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(max_length=300)
    cta_text: str = Field(min_length=1, max_length=30)


class Butir(_Ketat):
    title: str = Field(min_length=1, max_length=60)
    text: str = Field(max_length=200)


class Fitur(_Ketat):
    items: list[Butir] = Field(max_length=8)


class CaraKerja(_Ketat):
    steps: list[str] = Field(max_length=8)


class Tanya(_Ketat):
    q: str = Field(min_length=1, max_length=150)
    a: str = Field(max_length=600)


class Faq(_Ketat):
    items: list[Tanya] = Field(max_length=12)


class Footer(_Ketat):
    text: str = Field(max_length=200)


MODEL = {"hero": Hero, "fitur": Fitur, "cara_kerja": CaraKerja, "faq": Faq, "footer": Footer}


def bersihkan_isi(kunci: str, isi) -> dict:
    """Memvalidasi isi satu bagian; ValueError berisi pesan bila bentuknya salah."""
    from pydantic import ValidationError
    try:
        hasil = MODEL[kunci].model_validate(isi).model_dump()
    except ValidationError as e:
        raise ValueError("Isi bagian tidak valid: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3])) from None
    if kunci == "cara_kerja":
        langkah = [s.strip() for s in hasil["steps"]]
        if any(not s or len(s) > 150 for s in langkah):
            raise ValueError("Isi bagian tidak valid: tiap langkah harus 1-150 huruf")
        hasil["steps"] = langkah
    return hasil


def _isi(nilai, kunci: str) -> dict:
    """Kolom JSON (teks di MariaDB/SQLite) -> dict; rusak -> isi bawaan, supaya landing tidak pernah rusak."""
    if isinstance(nilai, (bytes, bytearray)):
        nilai = nilai.decode("utf-8", "replace")
    if isinstance(nilai, str):
        try:
            nilai = json.loads(nilai)
        except ValueError:
            return BAWAAN[kunci]
    try:
        return bersihkan_isi(kunci, nilai)
    except ValueError:
        return BAWAAN[kunci]


def semua_bagian(k) -> list:
    """Semua bagian (termasuk tersembunyi) urut menurut sort_order. Bagian yang belum ada di tabel diisi bawaan."""
    ada = {}
    try:
        for r in k.execute(text("SELECT section_key, content, sort_order, is_visible FROM landing_sections")).all():
            if r[0] in MODEL:
                ada[r[0]] = {"key": r[0], "content": _isi(r[1], r[0]), "sort_order": int(r[2]), "is_visible": bool(r[3])}
    except Exception:                                   # tabel belum ada: pakai bawaan sepenuhnya
        ada = {}
    for kunci in KUNCI:
        ada.setdefault(kunci, {"key": kunci, "content": BAWAAN[kunci], "sort_order": URUTAN_BAWAAN[kunci], "is_visible": True})
    return sorted(ada.values(), key=lambda b: (b["sort_order"], KUNCI.index(b["key"])))


@router.get("/landing")
def landing(request: Request):
    """Isi landing page untuk pengunjung (tanpa login): hanya bagian yang ditampilkan."""
    with request.app.state.konteks.engine().connect() as k:
        return [{"key": b["key"], "content": b["content"]} for b in semua_bagian(k) if b["is_visible"]]


@router.get("/admin/landing")
def landing_admin(request: Request, _admin: dict = Depends(wajib_admin)):
    with request.app.state.konteks.engine().connect() as k:
        bagian = semua_bagian(k)
    return [{**b, "bawaan": BAWAAN[b["key"]]} for b in bagian]


class SimpanBagian(BaseModel):
    content: dict
    is_visible: bool = True
    sort_order: int = Field(ge=0, le=1000)


@router.put("/admin/landing/{kunci}")
def simpan_bagian(kunci: str, isi: SimpanBagian, request: Request, _admin: dict = Depends(wajib_admin)):
    """Menyimpan satu bagian landing (isi, tampil/sembunyi, urutan). Mengembalikan bagian yang tersimpan."""
    if kunci not in MODEL:
        raise HTTPException(404, "Bagian tidak dikenal")
    try:
        bersih = bersihkan_isi(kunci, isi.content)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    nilai = {"k": kunci, "c": json.dumps(bersih, ensure_ascii=False), "o": isi.sort_order, "v": 1 if isi.is_visible else 0}
    with request.app.state.konteks.engine().begin() as c:
        n = c.execute(text("UPDATE landing_sections SET content = :c, sort_order = :o, is_visible = :v WHERE section_key = :k"), nilai).rowcount
        if n == 0:
            c.execute(text("INSERT INTO landing_sections (section_key, content, sort_order, is_visible) VALUES (:k, :c, :o, :v)"), nilai)
    return {"key": kunci, "content": bersih, "sort_order": isi.sort_order, "is_visible": isi.is_visible}
