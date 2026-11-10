"""transcribe.py: mengubah audio/video menjadi daftar kata bertimestamp (faster-whisper).

Keluarannya memakai wadah yang sudah ada (core.models.Word), sehingga langsung bisa
masuk ke split_sentences -> build_candidates -> score_candidates -> select_top_n.

Hal yang dilakukan modul ini:
  - memuat model faster-whisper di CPU (int8) dan mentranskripsi dengan timestamp per kata
  - membersihkan kata (spasi di tepi, kata kosong, timestamp tidak valid dibuang dan DIHITUNG)
  - menyimpan/memuat hasil ke JSON (format kolom transcripts.words: [{"w":..,"s":..,"e":..}])
  - menghitung statistik tumpang tindih antar kata, sebagai bahan menyetel
    TOLERANSI_TUMPANG_TINDIH pada scoring.py (modul scoring TIDAK diubah di sini)

Yang TIDAK dilakukan: menilai kualitas transkrip. Whisper bisa salah dengar, salah tanda
baca, atau mengarang teks pada bagian hening/musik. Kualitas diukur terpisah (misalnya WER)
pada tahap pengujian skripsi.

Pengaturan dibaca dari .env (semua opsional):
    WHISPER_MODEL=small        ukuran model: tiny, base, small, medium
    WHISPER_THREADS=4          jumlah thread CPU
    WHISPER_COMPUTE=int8       tipe hitung (int8 hemat memori di CPU)
    MODEL_DIR=D:/cache/whisper folder penyimpanan model yang diunduh

Cara pakai dari terminal (dari folder proyek, .venv aktif):
    python -m core.transcribe video.mp4 --bahasa id --simpan storage/uji/kata.json
"""
import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .models import Word

BASE = Path(__file__).resolve().parent.parent

# --- Nilai awal (dapat disetel lewat .env atau argumen) ---------------------
MODEL_BAWAAN = "small"
THREAD_BAWAAN = 4
COMPUTE_BAWAAN = "int8"
UKURAN_MODEL_VALID = ("tiny", "base", "small", "medium")
VAD_BAWAAN = True            # saring bagian tanpa suara supaya tidak "dikarang" Whisper
BEAM_BAWAAN = 5

_CACHE_MODEL: dict = {}


@dataclass(frozen=True)
class HasilTranskripsi:
    kata: list                       # list[Word], urut sesuai keluaran Whisper
    bahasa: str                      # kode bahasa terdeteksi atau yang diminta
    probabilitas_bahasa: float       # keyakinan deteksi bahasa (0-1)
    durasi: float                    # durasi audio dalam detik
    model: str                       # ukuran model yang dipakai
    kata_dibuang: int = 0            # kata kosong atau berwaktu tidak valid yang dibuang
    detik_proses: float = 0.0        # lama proses transkripsi


@dataclass(frozen=True)
class StatistikWaktu:
    jumlah_kata: int
    jumlah_tumpang_tindih: int       # pasangan kata berurutan yang saling menumpuk waktunya
    tumpang_tindih_maks: float       # detik, terbesar
    jumlah_mundur: int               # kata yang mulai lebih awal dari kata sebelumnya
    jeda_terpanjang: float           # detik, jeda terbesar antar kata


# ===========================================================================
# PENGATURAN
# ===========================================================================
def baca_pengaturan() -> dict:
    """Membaca .env (bila ada) dan mengembalikan pengaturan dengan nilai bawaan."""
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
    except ImportError:  # python-dotenv tidak terpasang: pakai variabel lingkungan saja
        pass

    def _int(nama, bawaan):
        try:
            nilai = int(os.getenv(nama, bawaan))
            return nilai if nilai > 0 else bawaan
        except ValueError:
            return bawaan

    ukuran = (os.getenv("WHISPER_MODEL") or MODEL_BAWAAN).strip().lower()
    return {
        "model": ukuran,
        "threads": _int("WHISPER_THREADS", THREAD_BAWAAN),
        "compute": (os.getenv("WHISPER_COMPUTE") or COMPUTE_BAWAAN).strip(),
        "model_dir": (os.getenv("MODEL_DIR") or "").strip() or None,
    }


# ===========================================================================
# PEMBERSIHAN KATA
# ===========================================================================
def _angka_valid(x) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:
        return False


def _ke_word(kata_whisper):
    """Satu kata keluaran Whisper -> Word, atau None bila tidak layak dipakai."""
    teks = getattr(kata_whisper, "word", None)
    mulai = getattr(kata_whisper, "start", None)
    akhir = getattr(kata_whisper, "end", None)
    if not isinstance(teks, str) or not teks.strip():
        return None
    if not (_angka_valid(mulai) and _angka_valid(akhir)) or mulai < 0 or akhir < mulai:
        return None
    return Word(teks.strip(), round(float(mulai), 3), round(float(akhir), 3))


def kumpulkan_kata(segmen) -> tuple:
    """Meratakan segmen Whisper menjadi (daftar Word, jumlah kata dibuang)."""
    hasil, dibuang = [], 0
    for seg in segmen:
        for k in (getattr(seg, "words", None) or []):
            w = _ke_word(k)
            if w is None:
                dibuang += 1
            else:
                hasil.append(w)
    return hasil, dibuang


def statistik_waktu(kata) -> StatistikWaktu:
    """Statistik tumpang tindih dan jeda antar kata berurutan (tanpa menilai baik/buruk)."""
    kata = list(kata)
    tumpang = mundur = 0
    maks = jeda_maks = 0.0
    for a, b in zip(kata, kata[1:]):
        if b.start < a.start:
            mundur += 1
        selisih = b.start - a.end
        if selisih < 0:
            tumpang += 1
            maks = max(maks, -selisih)
        else:
            jeda_maks = max(jeda_maks, selisih)
    return StatistikWaktu(len(kata), tumpang, maks, mundur, jeda_maks)


# ===========================================================================
# JSON (format kolom transcripts.words)
# ===========================================================================
def ke_json(kata) -> str:
    return json.dumps([{"w": k.text, "s": k.start, "e": k.end} for k in kata], ensure_ascii=False)


def dari_json(teks: str) -> list:
    """Memuat daftar Word dari JSON. Data yang bentuknya salah memunculkan ValueError yang jelas."""
    try:
        data = json.loads(teks)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON kata tidak valid: {e}") from None
    if not isinstance(data, list):
        raise ValueError("JSON kata harus berupa daftar")
    hasil = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or not {"w", "s", "e"} <= item.keys():
            raise ValueError(f"item ke-{i} tidak berisi kunci w, s, e")
        hasil.append(Word(item["w"], item["s"], item["e"]))
    return hasil


# ===========================================================================
# TRANSKRIPSI
# ===========================================================================
def _buat_model(ukuran: str, threads: int, compute: str, model_dir):
    """Memuat model (sekali per kombinasi pengaturan). Diunduh otomatis saat pertama dipakai."""
    kunci = (ukuran, threads, compute, model_dir)
    if kunci not in _CACHE_MODEL:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("faster-whisper belum terpasang. Jalankan: pip install -r requirements.txt") from None
        _CACHE_MODEL[kunci] = WhisperModel(ukuran, device="cpu", compute_type=compute,
                                           cpu_threads=threads, download_root=model_dir)
    return _CACHE_MODEL[kunci]


def transkripsi(path_media, bahasa=None, ukuran_model=None, *, vad: bool = VAD_BAWAAN,
                beam: int = BEAM_BAWAAN) -> HasilTranskripsi:
    """Mentranskripsi file audio atau video menjadi kata bertimestamp.

    bahasa=None berarti Whisper mendeteksi sendiri. Isi "id" untuk bahasa Indonesia
    agar lebih stabil dan lebih cepat. Berkas yang tidak ada memunculkan FileNotFoundError;
    ukuran model yang tidak dikenal memunculkan ValueError.
    """
    jalur = Path(path_media)
    if not jalur.is_file():
        raise FileNotFoundError(f"Berkas tidak ditemukan: {jalur}")
    peng = baca_pengaturan()
    ukuran = (ukuran_model or peng["model"]).strip().lower()
    if ukuran not in UKURAN_MODEL_VALID:
        raise ValueError(f"ukuran model harus salah satu dari {UKURAN_MODEL_VALID}, diterima: {ukuran!r}")

    model = _buat_model(ukuran, peng["threads"], peng["compute"], peng["model_dir"])
    mulai = time.perf_counter()
    segmen, info = model.transcribe(str(jalur), language=bahasa, word_timestamps=True,
                                    vad_filter=vad, beam_size=beam)
    kata, dibuang = kumpulkan_kata(segmen)         # generator: transkripsi berjalan di sini
    lama = time.perf_counter() - mulai
    return HasilTranskripsi(
        kata=kata,
        bahasa=str(getattr(info, "language", bahasa or "")),
        probabilitas_bahasa=float(getattr(info, "language_probability", 0.0) or 0.0),
        durasi=float(getattr(info, "duration", 0.0) or 0.0),
        model=ukuran, kata_dibuang=dibuang, detik_proses=lama)


# ===========================================================================
# ANTARMUKA TERMINAL: python -m core.transcribe video.mp4
# ===========================================================================
def _ringkas(hasil: HasilTranskripsi) -> str:
    st = statistik_waktu(hasil.kata)
    laju = len(hasil.kata) / hasil.durasi if hasil.durasi > 0 else 0.0
    rtf = hasil.detik_proses / hasil.durasi if hasil.durasi > 0 else 0.0
    baris = [
        f"Model            : {hasil.model}",
        f"Bahasa           : {hasil.bahasa} (keyakinan {hasil.probabilitas_bahasa:.0%})",
        f"Durasi audio     : {hasil.durasi:.1f} dtk",
        f"Waktu proses     : {hasil.detik_proses:.1f} dtk (x{rtf:.2f} dari durasi audio)",
        f"Jumlah kata      : {st.jumlah_kata} (dibuang: {hasil.kata_dibuang})",
        f"Kata per detik   : {laju:.2f}",
        f"Tumpang tindih   : {st.jumlah_tumpang_tindih} pasangan, terbesar {st.tumpang_tindih_maks:.3f} dtk",
        f"Kata mundur waktu: {st.jumlah_mundur}",
        f"Jeda terpanjang  : {st.jeda_terpanjang:.2f} dtk",
        "Contoh kata      : " + " ".join(k.text for k in hasil.kata[:15]),
    ]
    return "\n".join(baris)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Transkripsi audio/video menjadi kata bertimestamp.")
    ap.add_argument("media", help="jalur berkas audio atau video")
    ap.add_argument("--bahasa", default=None, help="kode bahasa, misalnya id atau en (bawaan: deteksi otomatis)")
    ap.add_argument("--model", default=None, help=f"ukuran model {UKURAN_MODEL_VALID} (bawaan dari .env)")
    ap.add_argument("--simpan", default=None, help="simpan kata ke berkas JSON ini")
    arg = ap.parse_args(argv)

    try:
        hasil = transkripsi(arg.media, arg.bahasa, arg.model)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    print(_ringkas(hasil))
    if arg.simpan:
        tujuan = Path(arg.simpan)
        tujuan.parent.mkdir(parents=True, exist_ok=True)
        tujuan.write_text(ke_json(hasil.kata), encoding="utf-8")
        print(f"Kata disimpan ke : {tujuan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
