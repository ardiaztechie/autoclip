"""api_proyek.py: unggah video (berkas atau tautan YouTube) dan daftar/detail proyek milik pengguna yang sedang masuk.

Alur POST /projects: simpan video ke berkas sementara -> (satu transaksi) buat baris projects,
pindahkan video ke storage/projects/<id>/source.<ekstensi>, taruh pekerjaan di job_queue.
Bila langkah mana pun gagal, transaksi dibatalkan dan berkas dibersihkan.

Catatan: FastAPI menerima seluruh unggahan lebih dulu (disimpan sementara), baru batas ukuran diperiksa.
"""
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from . import pengguna, proyek
from .auth import pengguna_saat_ini

log = logging.getLogger("autoclip")
router = APIRouter()

EKSTENSI = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
POTONGAN = 1024 * 1024
# Hanya YouTube: server tidak boleh disuruh mengunduh dari alamat sembarang (mencegah akses ke jaringan internal).
HOST_YOUTUBE = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
MAKS_HURUF_TAUTAN = 500


def tautan_youtube(teks: str) -> str:
    """Mengembalikan tautan yang sudah dirapikan, atau memunculkan ValueError dengan pesan yang jelas."""
    tautan = (teks or "").strip()
    if not tautan or len(tautan) > MAKS_HURUF_TAUTAN or re.search(r"\s", tautan):
        raise ValueError("Tautan tidak valid")
    bagian = urlsplit(tautan)
    if bagian.scheme not in ("http", "https") or bagian.username or bagian.password:
        raise ValueError("Tautan harus berupa alamat http(s) YouTube")
    try:
        bagian.port
    except ValueError:
        raise ValueError("Tautan tidak valid") from None
    if (bagian.hostname or "").lower() not in HOST_YOUTUBE or bagian.port not in (None, 80, 443):
        raise ValueError("Hanya tautan YouTube (youtube.com atau youtu.be) yang didukung")
    return tautan


def _nama_aman(nama) -> str:
    """Hanya nama berkasnya (tanpa folder, termasuk gaya Windows), tanpa karakter kontrol, maks 500 huruf."""
    dasar = re.split(r"[\\/]", nama or "")[-1]
    return re.sub(r"[\x00-\x1f]", "", dasar).strip()[:500]


def _simpan_sementara(berkas: UploadFile, cfg: dict, ekstensi: str) -> Path:
    folder = cfg["folder"] / "tmp"
    tujuan = folder / (uuid.uuid4().hex + ekstensi)
    total = 0
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with open(tujuan, "wb") as f:
            while True:
                potong = berkas.file.read(POTONGAN)
                if not potong:
                    break
                total += len(potong)
                if total > cfg["maks_bytes"]:
                    raise HTTPException(413, f"Ukuran video melebihi batas {cfg['maks_bytes'] // (1024 * 1024)} MB")
                f.write(potong)
        if total == 0:
            raise HTTPException(422, "Berkas video kosong")
    except OSError:
        tujuan.unlink(missing_ok=True)
        log.exception("gagal menyimpan unggahan")
        raise HTTPException(500, "Gagal menyimpan video ke disk") from None
    except BaseException:
        tujuan.unlink(missing_ok=True)
        raise
    return tujuan


@router.post("/projects", status_code=201)
def buat_proyek(
    request: Request,
    file: UploadFile | None = File(None),
    url: str = Form("", max_length=2000),
    title: str = Form("", max_length=200),
    language: str = Form("auto", pattern=r"^(auto|[a-z]{2,3})$"),
    ratio: Literal["9:16", "1:1", "4:5"] = Form("9:16"),
    n_clips: int | None = Form(None, ge=1, le=50),
    clip_density: Literal["jarang", "sedang", "rapat"] = Form("sedang"),
    clip_length: Literal["otomatis", "pendek", "sedang", "panjang", "sangat_panjang", "ekstra_panjang"] = Form("otomatis"),
    face_tracking: bool = Form(True),
    u: dict = Depends(pengguna_saat_ini),
):
    k = request.app.state.konteks
    ada_berkas = file is not None and bool(file.filename)
    ada_tautan = bool(url.strip())
    if ada_berkas and ada_tautan:
        raise HTTPException(422, "Pilih salah satu: berkas video atau tautan YouTube")
    if not ada_berkas and not ada_tautan:
        raise HTTPException(422, "Berkas video atau tautan YouTube wajib diisi")
    if ada_tautan:
        try:
            tautan = tautan_youtube(url)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        return _buat_dari_tautan(request, tautan, title, language, ratio, n_clips, face_tracking, u, clip_density, clip_length)
    nama = _nama_aman(file.filename)
    ekstensi = Path(nama).suffix.lower()
    if ekstensi not in EKSTENSI:
        raise HTTPException(422, "Format video tidak didukung. Gunakan: mp4, mov, mkv, webm, atau avi")
    cfg, engine = k.unggah(), k.engine()
    if u["role"] != "admin":                                       # admin tidak dibatasi kuota (untuk pengujian)
        with engine.connect() as c:
            batas, ada = pengguna.kuota_proyek(c, u["id"]), proyek.jumlah(c, u["id"])
        if ada >= batas:
            raise HTTPException(403, f"Kuota proyek habis ({batas}). Hubungi admin.")
    sementara = _simpan_sementara(file, cfg, ekstensi)
    folder_proyek = None
    try:
        with engine.begin() as c:
            pid = proyek.buat(c, u["id"], title.strip() or Path(nama).stem[:200], nama, language, ratio,
                              n_clips, face_tracking, kepadatan=clip_density, panjang=clip_length)
            folder_proyek = cfg["folder"] / "projects" / str(pid)
            folder_proyek.mkdir(parents=True, exist_ok=True)
            os.replace(sementara, folder_proyek / f"source{ekstensi}")
            proyek.antrekan(c, pid)
    except Exception:
        log.exception("gagal membuat proyek")
        sementara.unlink(missing_ok=True)
        if folder_proyek is not None:
            shutil.rmtree(folder_proyek, ignore_errors=True)
        raise HTTPException(500, "Gagal menyimpan proyek") from None
    with engine.connect() as c:                                    # di luar try: proyek sudah tersimpan, jangan dihapus
        return proyek.cari(c, pid, u["id"])


def _buat_dari_tautan(request, tautan, title, language, ratio, n_clips, face_tracking, u, clip_density="sedang",
                      clip_length="otomatis"):
    """Proyek dari tautan YouTube: hanya baris proyek, folder, dan antrean. Video diunduh oleh worker."""
    k = request.app.state.konteks
    cfg, engine = k.unggah(), k.engine()
    if u["role"] != "admin":
        with engine.connect() as c:
            batas, ada = pengguna.kuota_proyek(c, u["id"]), proyek.jumlah(c, u["id"])
        if ada >= batas:
            raise HTTPException(403, f"Kuota proyek habis ({batas}). Hubungi admin.")
    folder_proyek = None
    try:
        with engine.begin() as c:
            pid = proyek.buat(c, u["id"], title.strip(), tautan, language, ratio, n_clips, face_tracking,
                              source_type="link", kepadatan=clip_density, panjang=clip_length)
            folder_proyek = cfg["folder"] / "projects" / str(pid)
            folder_proyek.mkdir(parents=True, exist_ok=True)
            proyek.antrekan(c, pid)
    except Exception:
        log.exception("gagal membuat proyek dari tautan")
        if folder_proyek is not None:
            shutil.rmtree(folder_proyek, ignore_errors=True)
        raise HTTPException(500, "Gagal menyimpan proyek") from None
    with engine.connect() as c:
        return proyek.cari(c, pid, u["id"])


@router.get("/projects")
def daftar_proyek(request: Request, u: dict = Depends(pengguna_saat_ini)):
    with request.app.state.konteks.engine().connect() as c:
        return proyek.daftar(c, u["id"])


@router.get("/projects/{project_id}")
def detail_proyek(project_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    with request.app.state.konteks.engine().connect() as c:
        p = proyek.cari(c, project_id, u["id"])
    if p is None:
        raise HTTPException(404, "Proyek tidak ditemukan")         # proyek orang lain pun dijawab 404
    return p


@router.post("/projects/{project_id}/batal")
def batal_proyek(project_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Membatalkan pemrosesan proyek yang masih antre atau berjalan. Proyek tidak dihapus."""
    with request.app.state.konteks.engine().begin() as c:
        try:
            return proyek.batalkan_proyek(c, project_id, u["id"])
        except LookupError:
            raise HTTPException(404, "Proyek tidak ditemukan") from None
        except RuntimeError:
            raise HTTPException(409, "Proyek ini tidak sedang diproses") from None


def hapus_folder_proyek(konteks, project_id: int) -> None:
    """Menghapus folder berkas proyek (video asli, kata.json, klip hasil). Galat disk diabaikan: baris database sudah terhapus."""
    import shutil
    folder = (konteks.unggah()["folder"] / "projects" / str(project_id)).resolve()
    akar = (konteks.unggah()["folder"] / "projects").resolve()
    if folder.parent == akar and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


@router.delete("/projects/{project_id}", status_code=204)
def hapus_proyek(project_id: int, request: Request, u: dict = Depends(pengguna_saat_ini)):
    """Menghapus proyek beserta semua klip dan berkas videonya. Tidak bisa dibatalkan."""
    konteks = request.app.state.konteks
    with konteks.engine().begin() as c:
        try:
            proyek.hapus_proyek(c, project_id, u["id"])
        except LookupError:
            raise HTTPException(404, "Proyek tidak ditemukan") from None
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from None
    hapus_folder_proyek(konteks, project_id)
