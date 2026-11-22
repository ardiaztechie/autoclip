"""api_klip.py: daftar klip hasil proses dan pemutaran/unduhan videonya, hanya untuk pemilik proyek.

Proyek atau klip milik orang lain dijawab 404 (sama seperti proyek yang tidak ada), supaya keberadaannya tidak bocor.
Video dikirim lewat FileResponse (mendukung Range, jadi bisa diputar dan digeser di browser).
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from . import proyek
from .auth import pengguna_saat_ini

router = APIRouter()


def _nama_unduhan(judul: str, clip_id: int) -> str:
    dasar = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "", judul or "").strip(" .")[:80]
    return (dasar or f"klip-{clip_id}") + ".mp4"


@router.get("/projects/{project_id}/clips")
def daftar_klip(project_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    with request.app.state.konteks.engine().connect() as c:
        if proyek.cari(c, project_id, u["id"]) is None:
            raise HTTPException(404, "Proyek tidak ditemukan")
        return proyek.daftar_klip(c, project_id)


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
