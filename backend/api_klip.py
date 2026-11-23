"""api_klip.py: daftar klip hasil proses dan pemutaran/unduhan videonya, hanya untuk pemilik proyek.

Proyek atau klip milik orang lain dijawab 404 (sama seperti proyek yang tidak ada), supaya keberadaannya tidak bocor.
Video dikirim lewat FileResponse (mendukung Range, jadi bisa diputar dan digeser di browser).
"""
import json
import math
import re

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import proyek
from .auth import pengguna_saat_ini

router = APIRouter()


def _nama_unduhan(judul: str, clip_id: int) -> str:
    dasar = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "", judul or "").strip(" .")[:80]
    return (dasar or f"klip-{clip_id}") + ".mp4"


def _tambah_kemajuan(konteks, project_id: int, klip: list) -> list:
    """Klip yang sedang dirender ulang diberi `kemajuan` = {persen, tahap, berjalan_detik} dari berkas yang ditulis worker,
    atau None bila worker belum melaporkan apa pun."""
    folder = konteks.unggah()["folder"] / "projects" / str(project_id) / "hasil"
    for k in klip:
        if k["status"] != "rendering":
            continue
        try:
            isi = json.loads((folder / f"_ulang_{k['id']}" / "progres.json").read_text(encoding="utf-8"))
            k["kemajuan"] = {"persen": max(0, min(99, int(isi["persen"]))), "tahap": str(isi["tahap"])[:80],
                             "berjalan_detik": max(0.0, float(isi["berjalan"]))}
        except (OSError, ValueError, KeyError, TypeError):
            k["kemajuan"] = None
    return klip


@router.get("/projects/{project_id}/clips")
def daftar_klip(project_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    konteks = request.app.state.konteks
    with konteks.engine().connect() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        klip = proyek.daftar_klip(c, project_id)
        for k in klip:                                   # klip yang gagal dirender ulang: sertakan alasannya
            if k["status"] == "failed":
                k["galat_render"] = proyek.galat_render_terakhir(c, project_id, k["id"])
    return _tambah_kemajuan(konteks, project_id, klip)


class UbahKlip(BaseModel):
    title: str = Field("", max_length=200)
    caption: str = Field("", max_length=500)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


@router.patch("/projects/{project_id}/clips/{clip_id}")
def ubah_klip(project_id: int, clip_id: int, isi: UbahKlip, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Edit judul, caption, dan hashtag. Tidak merender ulang video."""
    with request.app.state.konteks.engine().begin() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        hasil = proyek.ubah_teks_klip(c, project_id, clip_id, isi.title.strip(), isi.caption.strip(), isi.hashtags)
    if hasil is None:
        raise HTTPException(404, "Klip tidak ditemukan")
    return hasil


class Koreksi(BaseModel):
    s: float = Field(ge=0, allow_inf_nan=False)                      # detik mulai kata di video asli (pengenal kata)
    w: str = Field(max_length=proyek.MAKS_HURUF_KATA)                # teks baru; kosong = kata dibuang dari subtitle


class PilihanSubtitle(BaseModel):
    gaya: Literal["klasik", "kuning", "kotak", "sorot", "minimal"] = "klasik"
    posisi: Literal["bawah", "tengah", "atas"] = "bawah"
    ukuran: Literal["kecil", "sedang", "besar"] = "sedang"
    animasi: Literal["tanpa", "muncul", "pudar"] = "tanpa"
    aktif: bool = True


class SubtitleKlip(PilihanSubtitle):
    koreksi: list[Koreksi] | None = Field(default=None, max_length=proyek.MAKS_KOREKSI)


@router.put("/projects/{project_id}/clips/{clip_id}/subtitle")
def simpan_subtitle(project_id: int, clip_id: int, isi: SubtitleKlip, request: Request,
                    u: dict = Depends(pengguna_saat_ini)):
    """Menyimpan gaya subtitle dan koreksi kata satu klip. Tidak merender ulang; hasilnya terlihat setelah render ulang.
    koreksi tidak dikirim = koreksi lama dipertahankan."""
    with request.app.state.konteks.engine().begin() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        klip = proyek.cari_klip(c, project_id, clip_id)
        if klip is None:
            raise HTTPException(404, "Klip tidak ditemukan")
        if klip["status"] == "rendering":
            raise HTTPException(409, "Klip sedang dirender ulang; tunggu selesai atau batalkan dulu")
        koreksi = None if isi.koreksi is None else [k.model_dump() for k in isi.koreksi]
        return proyek.simpan_subtitle(c, project_id, clip_id, isi.model_dump(exclude={"koreksi"}), koreksi)


class JedaKlip(BaseModel):
    aktif: bool = False
    ambang: float = Field(default=proyek.JEDA_BAWAAN["ambang"], ge=proyek.AMBANG_JEDA_MIN, le=proyek.AMBANG_JEDA_MAKS, allow_inf_nan=False)


@router.put("/projects/{project_id}/clips/{clip_id}/jeda")
def simpan_jeda(project_id: int, clip_id: int, isi: JedaKlip, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Menyimpan pilihan potong jeda satu klip. Tidak merender ulang; hasilnya terlihat setelah render ulang."""
    with request.app.state.konteks.engine().begin() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        klip = proyek.cari_klip(c, project_id, clip_id)
        if klip is None:
            raise HTTPException(404, "Klip tidak ditemukan")
        if klip["status"] == "rendering":
            raise HTTPException(409, "Klip sedang dirender ulang; tunggu selesai atau batalkan dulu")
        return proyek.simpan_jeda(c, project_id, clip_id, isi.model_dump())


class PotongKlip(BaseModel):
    selang: list[tuple[float, float]] = Field(default_factory=list, max_length=proyek.MAKS_POTONGAN)


@router.put("/projects/{project_id}/clips/{clip_id}/potong")
def simpan_potong(project_id: int, clip_id: int, isi: PotongKlip, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Menyimpan potongan manual satu klip: selang [awal, akhir] (detik video asli) yang dibuang. Tidak merender ulang."""
    for a, b in isi.selang:
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b):
            raise HTTPException(422, "Selang potongan tidak valid")
    with request.app.state.konteks.engine().begin() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        klip = proyek.cari_klip(c, project_id, clip_id)
        if klip is None:
            raise HTTPException(404, "Klip tidak ditemukan")
        if klip["status"] == "rendering":
            raise HTTPException(409, "Klip sedang dirender ulang; tunggu selesai atau batalkan dulu")
        return proyek.simpan_potong(c, project_id, clip_id, isi.selang)


@router.post("/projects/{project_id}/clips/subtitle-semua", status_code=202)
def subtitle_semua(project_id: int, isi: PilihanSubtitle, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Menyamakan gaya subtitle semua klip proyek, lalu merender ulang tiap klip (batas klip tidak berubah).
    Klip yang sedang dirender dilewati. Render berjalan satu per satu di worker, jadi bisa memakan waktu lama."""
    konteks = request.app.state.konteks
    with konteks.engine().begin() as c:
        p = proyek.cari(c, project_id, u["id"])
        if p is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        if p["status"] != "done":
            raise HTTPException(409, "Proyek belum selesai diproses")
        if not any((konteks.unggah()["folder"] / "projects" / str(project_id)).glob("source.*")):
            raise HTTPException(409, "Video sumber sudah tidak tersedia di server, klip tidak bisa dirender ulang")
        diubah = proyek.terapkan_subtitle_semua(c, project_id, isi.model_dump())
        for cid, mulai, akhir in diubah:
            proyek.jadwalkan_render_ulang(c, project_id, cid, mulai, akhir)
        return {"diantre": len(diubah)}


MARGIN_KATA_MAKS = 120.0          # detik di kiri/kanan klip yang boleh diminta editor
MAKS_KATA_BALASAN = 5000


def _kata_rentang(konteks, project_id: int, dari: float, sampai: float) -> list:
    """Kata kata.json proyek yang beririsan dengan [dari, sampai] (maks MAKS_KATA_BALASAN). Berkas tidak ada/rusak -> kosong."""
    berkas = konteks.unggah()["folder"] / "projects" / str(project_id) / "hasil" / "kata.json"
    kata = []
    try:
        for item in json.loads(berkas.read_text(encoding="utf-8")):
            w, a, b = item["w"], float(item["s"]), float(item["e"])
            if b >= dari and a <= sampai and isinstance(w, str):
                kata.append({"w": w, "s": round(a, 3), "e": round(b, 3)})
    except (OSError, ValueError, KeyError, TypeError):
        kata = []
    return kata[:MAKS_KATA_BALASAN]


@router.get("/projects/{project_id}/clips/{clip_id}/kata")
def kata_klip(project_id: int, clip_id: int, request: Request, margin: float = 30.0,
              u: dict = Depends(pengguna_saat_ini)):
    """Kata-kata transkrip di sekitar klip (dari kata.json proyek): dari `margin` detik sebelum klip sampai `margin` sesudahnya.
    Dipakai editor untuk menampilkan transkrip dan memilih batas klip. Tanpa transkrip -> daftar kosong."""
    if not math.isfinite(margin) or margin < 0:
        raise HTTPException(422, "margin tidak valid")
    margin = min(margin, MARGIN_KATA_MAKS)
    konteks = request.app.state.konteks
    with konteks.engine().connect() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        klip = proyek.cari_klip(c, project_id, clip_id)
    if klip is None:
        raise HTTPException(404, "Klip tidak ditemukan")
    dari, sampai = klip["start_sec"] - margin, klip["end_sec"] + margin
    return {"dari": round(max(dari, 0.0), 3), "sampai": round(sampai, 3), "kata": _kata_rentang(konteks, project_id, dari, sampai)}


RENTANG_KATA_MAKS = 900.0         # detik per permintaan kata rentang bebas


@router.get("/projects/{project_id}/kata")
def kata_rentang(project_id: int, dari: float, sampai: float, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Kata transkrip proyek pada rentang waktu video asli [dari, sampai] (maks RENTANG_KATA_MAKS detik per permintaan).
    Dipakai garis waktu editor yang menampilkan seluruh video dan dimuat sedikit demi sedikit saat digeser."""
    if not (math.isfinite(dari) and math.isfinite(sampai)) or dari < 0 or sampai <= dari or sampai - dari > RENTANG_KATA_MAKS:
        raise HTTPException(422, f"rentang tidak valid (maksimal {int(RENTANG_KATA_MAKS)} detik)")
    konteks = request.app.state.konteks
    with konteks.engine().connect() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
    return {"dari": round(dari, 3), "sampai": round(sampai, 3), "kata": _kata_rentang(konteks, project_id, dari, sampai)}


MIME_SUMBER = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
               ".avi": "video/x-msvideo"}


@router.get("/projects/{project_id}/source")
def video_sumber(project_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Video asli proyek untuk pratinjau batas klip di editor (mendukung Range, jadi bisa digeser). Hanya pemilik proyek.
    Nama berkas di server tidak dikirim."""
    konteks = request.app.state.konteks
    with konteks.engine().connect() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
    folder = (konteks.unggah()["folder"] / "projects" / str(project_id)).resolve()
    for berkas in sorted(folder.glob("source.*")):
        ekstensi = berkas.suffix.lower()
        if ekstensi in MIME_SUMBER and berkas.is_file() and berkas.resolve().is_relative_to(folder):
            return FileResponse(berkas, media_type=MIME_SUMBER[ekstensi], content_disposition_type="inline")
    raise HTTPException(404, "Video asli tidak tersedia di server")


class RenderUlang(BaseModel):
    start_sec: float = Field(ge=0, allow_inf_nan=False)
    end_sec: float = Field(gt=0, allow_inf_nan=False)


@router.post("/projects/{project_id}/clips/{clip_id}/render-ulang", status_code=202)
def render_ulang(project_id: int, clip_id: int, isi: RenderUlang, request: Request,
                 u: dict = Depends(pengguna_saat_ini)):
    """Mengatur batas awal/akhir klip (detik video sumber) lalu merender ulang klip itu lewat worker.
    Video lama tetap bisa diputar sampai render ulang selesai. Skor dan judul tidak dihitung ulang."""
    durasi = isi.end_sec - isi.start_sec
    if durasi < proyek.MIN_KLIP_DETIK or durasi > proyek.MAKS_KLIP_DETIK:
        raise HTTPException(422, f"Durasi klip harus {int(proyek.MIN_KLIP_DETIK)} sampai {int(proyek.MAKS_KLIP_DETIK)} detik")
    konteks = request.app.state.konteks
    with konteks.engine().begin() as c:
        p = proyek.cari(c, project_id, u["id"])
        if p is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        if p["status"] != "done":
            raise HTTPException(409, "Proyek belum selesai diproses")
        if p["duration_sec"] is not None and isi.end_sec > float(p["duration_sec"]) + 0.5:
            raise HTTPException(422, "Batas akhir melewati durasi video")
        folder = konteks.unggah()["folder"] / "projects" / str(project_id)
        if not any(folder.glob("source.*")):
            raise HTTPException(409, "Video sumber sudah tidak tersedia di server, klip tidak bisa dirender ulang")
        try:
            return proyek.jadwalkan_render_ulang(c, project_id, clip_id, isi.start_sec, isi.end_sec)
        except LookupError:
            raise HTTPException(404, "Klip tidak ditemukan") from None
        except RuntimeError:
            raise HTTPException(409, "Klip ini masih dirender ulang") from None


@router.post("/projects/{project_id}/clips/{clip_id}/batal-render")
def batal_render(project_id: int, clip_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Membatalkan render ulang satu klip. Video lama tetap dipakai; batas awal/akhir klip tidak berubah."""
    konteks = request.app.state.konteks
    with konteks.engine().begin() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        try:
            return proyek.batalkan_render_ulang(c, project_id, clip_id)
        except LookupError:
            raise HTTPException(404, "Klip tidak ditemukan") from None
        except RuntimeError:
            raise HTTPException(409, "Klip ini tidak sedang dirender ulang") from None


@router.get("/projects/{project_id}/clips/{clip_id}/video")
def video_klip(project_id: int, clip_id: int, request: Request, unduh: bool = False,
               u: dict = Depends(pengguna_saat_ini)):
    konteks = request.app.state.konteks
    with konteks.engine().connect() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        hasil = proyek.cari_berkas_klip(c, project_id, clip_id)
    if hasil is None:
        raise HTTPException(404, "Klip tidak ditemukan")
    relatif, judul = hasil
    folder_proyek = (konteks.unggah()["folder"] / "projects" / str(project_id)).resolve()
    berkas = (konteks.unggah()["folder"] / relatif).resolve()
    # Berkas harus benar-benar di dalam folder proyek ini (menolak ../ dan tautan simbolik keluar folder).
    if not berkas.is_relative_to(folder_proyek) or not berkas.is_file():
        raise HTTPException(404, "Berkas video tidak ditemukan")
    return FileResponse(berkas, media_type="video/mp4", filename=_nama_unduhan(judul, clip_id),
                        content_disposition_type="attachment" if unduh else "inline")


@router.delete("/projects/{project_id}/clips/{clip_id}", status_code=204)
def hapus_klip(project_id: int, clip_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Menghapus satu klip beserta berkas videonya. Tidak bisa dibatalkan."""
    konteks = request.app.state.konteks
    with konteks.engine().begin() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        try:
            relatif = proyek.hapus_klip(c, project_id, clip_id)
        except LookupError:
            raise HTTPException(404, "Klip tidak ditemukan") from None
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from None
    if relatif:
        akar = konteks.unggah()["folder"]
        folder_proyek = (akar / "projects" / str(project_id)).resolve()
        berkas = (akar / relatif).resolve()
        if berkas.is_relative_to(folder_proyek) and berkas.is_file():
            try:
                berkas.unlink()
            except OSError:
                pass                                     # baris database sudah terhapus; berkas sisa tidak mengganggu
