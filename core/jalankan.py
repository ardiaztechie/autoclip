"""jalankan.py: satu perintah dari video sampai klip jadi (Prototype 2).

Tidak ada rumus baru di sini. Modul ini hanya MENYAMBUNG empat langkah yang sudah ada,
dengan memanggil main() masing-masing seolah-olah Anda mengetik empat perintah:

    1. core.transcribe : video -> kata.json        (dilewati bila kata.json sudah ada, kecuali --ulang)
    2. core.pipeline   : kata.json + video -> klip.json (pemilihan klip; skoring TIDAK diubah)
    3. core.metadata   : kata.json + klip.json -> metadata.json (judul, caption, hashtag; versi aturan)
    4. core.render     : video + klip.json + kata.json -> klip_XX_9x16.mp4 (wajah, zoom, subtitle)

Semua hasil ditulis ke satu folder (bawaan storage/hasil/<nama video>/).

Pilihan yang tidak Anda isi tidak diteruskan, jadi nilai bawaan tiap modul tetap berlaku.

Cara pakai (dari folder proyek, .venv aktif):
    python -m core.jalankan storage/uji/video_uji.mp4
    python -m core.jalankan video.mp4 --tingkat rapat --durasi pendek
    python -m core.jalankan video.mp4 --n 5 --rasio 1:1 --folder storage/hasil/coba
"""
import argparse
import sys
import time
from pathlib import Path

from . import metadata, pipeline, render, transcribe
from .face import RASIO_VALID
from .pipeline import PRESET_DURASI, TINGKAT_JUMLAH

FOLDER_BAWAAN = Path("storage") / "hasil"
NAMA_KATA = "kata.json"
NAMA_KLIP = "klip.json"
NAMA_METADATA = "metadata.json"
TOTAL_LANGKAH = 4


# ===========================================================================
# MENYUSUN ARGUMEN TIAP LANGKAH (hanya yang diisi pengguna yang diteruskan)
# ===========================================================================
def argv_transkripsi(video, kata_json, arg) -> list:
    a = [str(video), "--simpan", str(kata_json)]
    if arg.bahasa:
        a += ["--bahasa", arg.bahasa]
    if arg.model:
        a += ["--model", arg.model]
    return a


def argv_pipeline(video, kata_json, klip_json, arg) -> list:
    a = [str(kata_json), "--media", str(video), "--simpan", str(klip_json)]
    if arg.n is not None:
        a += ["--n", str(arg.n)]
    if arg.tingkat:
        a += ["--tingkat", arg.tingkat]
    if arg.durasi:
        a += ["--durasi", arg.durasi]
    if arg.min_detik is not None:
        a += ["--min-detik", str(arg.min_detik)]
    if arg.maks_detik is not None:
        a += ["--maks-detik", str(arg.maks_detik)]
    if arg.jeda_maks_calon is not None:
        a += ["--jeda-maks-calon", str(arg.jeda_maks_calon)]
    if arg.mode_calon:
        a += ["--mode-calon", arg.mode_calon]
    if arg.toleransi is not None:
        a += ["--toleransi", str(arg.toleransi)]
    return a


def argv_metadata(kata_json, klip_json, metadata_json) -> list:
    return [str(kata_json), str(klip_json), "--simpan", str(metadata_json)]


def argv_render(video, klip_json, kata_json, folder, arg) -> list:
    a = [str(video), str(klip_json), "--kata", str(kata_json), "--folder", str(folder)]
    if arg.rasio:
        a += ["--rasio", arg.rasio]
    if arg.mode:
        a += ["--mode", arg.mode]
    if arg.tanpa_zoom:
        a += ["--tanpa-zoom"]
    if arg.lebar is not None:
        a += ["--lebar", str(arg.lebar)]
    return a


def buat_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Satu perintah: video -> klip jadi (transkripsi, pemilihan, render).")
    ap.add_argument("video", help="jalur berkas video")
    ap.add_argument("--folder", default=None,
                    help=f"folder hasil (bawaan: {FOLDER_BAWAAN.as_posix()}/<nama video>)")
    ap.add_argument("--ulang", action="store_true",
                    help="transkripsi ulang walau kata.json sudah ada di folder hasil")
    g = ap.add_argument_group("transkripsi")
    g.add_argument("--bahasa", default=None, help="kode bahasa, mis. id (bawaan: deteksi otomatis)")
    g.add_argument("--model", default=None, help="ukuran model whisper (bawaan dari .env)")
    g = ap.add_argument_group("pemilihan klip (eksperimental, lihat core.pipeline)")
    g.add_argument("--n", type=int, default=None, help="jumlah klip pasti; kosong = otomatis menurut --tingkat")
    g.add_argument("--tingkat", choices=tuple(TINGKAT_JUMLAH), default=None, help="jarang, sedang (bawaan), rapat")
    g.add_argument("--durasi", choices=tuple(PRESET_DURASI), default=None,
                   help="otomatis (bawaan), pendek, sedang, panjang")
    g.add_argument("--min-detik", type=float, default=None, help="durasi klip minimum (angka bebas)")
    g.add_argument("--maks-detik", type=float, default=None, help="durasi klip maksimum (angka bebas)")
    g.add_argument("--jeda-maks-calon", type=float, default=None, help="0 = mati (bawaan modul: 10 dtk)")
    g.add_argument("--mode-calon", choices=("lama", "varian"), default=None, help="bawaan modul: varian")
    g.add_argument("--toleransi", type=float, default=None, help="toleransi di atas durasi maks (dtk)")
    g = ap.add_argument_group("render")
    g.add_argument("--rasio", choices=list(RASIO_VALID), default=None, help="bawaan modul: 9:16")
    g.add_argument("--mode", choices=["pembicara", "satu-wajah", "tengah"], default=None,
                   help="bawaan modul: pembicara")
    g.add_argument("--tanpa-zoom", action="store_true", help="matikan zoom penekanan")
    g.add_argument("--lebar", type=int, default=None, help="lebar keluaran piksel (genap)")
    return ap


# ===========================================================================
# MENJALANKAN
# ===========================================================================
def _jalankan_langkah(nomor: int, total: int, nama: str, fungsi, argv: list) -> int:
    print(f"\n=== Langkah {nomor}/{total}: {nama} ===")
    mulai = time.perf_counter()
    kode = fungsi(argv)
    print(f"--- {nama}: {'selesai' if kode == 0 else 'GAGAL'} ({time.perf_counter() - mulai:.1f} dtk)")
    return kode


def main(argv=None, *, langkah=None) -> int:
    """langkah: untuk tes; kamus {"transkripsi", "pipeline", "metadata", "render"} -> fungsi(argv) -> kode.
    Bila kosong, memakai main() modul aslinya."""
    arg = buat_parser().parse_args(argv)
    fungsi = {"transkripsi": transcribe.main, "pipeline": pipeline.main, "metadata": metadata.main,
              "render": render.main}
    if langkah:
        fungsi.update(langkah)

    video = Path(arg.video)
    if not video.is_file():
        print(f"[GAGAL] Berkas video tidak ditemukan: {video}")
        return 1
    folder = Path(arg.folder) if arg.folder else FOLDER_BAWAAN / video.stem
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[GAGAL] folder hasil tidak bisa dibuat: {e}")
        return 1
    kata_json, klip_json, metadata_json = folder / NAMA_KATA, folder / NAMA_KLIP, folder / NAMA_METADATA
    print(f"Video : {video}\nHasil : {folder}")
    mulai_total = time.perf_counter()

    # Langkah 1: transkripsi (dilewati bila sudah ada)
    if kata_json.is_file() and not arg.ulang:
        print(f"\n=== Langkah 1/4: transkripsi dilewati ({kata_json.name} sudah ada; pakai --ulang untuk mengulang) ===")
    else:
        if _jalankan_langkah(1, TOTAL_LANGKAH, "transkripsi", fungsi["transkripsi"], argv_transkripsi(video, kata_json, arg)) != 0:
            return 1
        if not kata_json.is_file():
            print(f"[GAGAL] transkripsi tidak menghasilkan {kata_json}")
            return 1

    # Langkah 2: pemilihan klip
    if _jalankan_langkah(2, TOTAL_LANGKAH, "pemilihan klip", fungsi["pipeline"], argv_pipeline(video, kata_json, klip_json, arg)) != 0:
        return 1
    if not klip_json.is_file():
        print(f"[GAGAL] pemilihan klip tidak menghasilkan {klip_json}")
        return 1
    if klip_json.read_text(encoding="utf-8").strip() in ("", "[]"):
        print("[GAGAL] tidak ada klip terpilih. Coba --durasi lain, --tingkat rapat, atau video yang lebih panjang.")
        return 1

    # Langkah 3: judul, caption, hashtag (sebelum render, supaya tetap ada bila render gagal)
    if _jalankan_langkah(3, TOTAL_LANGKAH, "judul, caption, hashtag", fungsi["metadata"],
                         argv_metadata(kata_json, klip_json, metadata_json)) != 0:
        return 1

    # Langkah 4: render
    if _jalankan_langkah(4, TOTAL_LANGKAH, "render", fungsi["render"], argv_render(video, klip_json, kata_json, folder, arg)) != 0:
        return 1

    print(f"\nSELESAI dalam {time.perf_counter() - mulai_total:.1f} dtk. Hasil ada di: {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
