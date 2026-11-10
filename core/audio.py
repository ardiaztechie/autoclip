"""audio.py: mengukur energi suara (RMS) per detik dari berkas audio/video.

Keluarannya core.models.EnergyProfile, masukan untuk Trend pada scoring.py
(scoring TIDAK diubah). Audio dibaca langsung dengan PyAV (sudah terpasang bersama
faster-whisper), jadi FFmpeg CLI tidak wajib. Audio dibaca bertahap, tidak dimuat
seluruhnya ke memori.

Yang dilakukan: audio -> mono 16 kHz -> RMS tiap `langkah` detik (bawaan 1,0 dtk).
Nilai RMS berskala 0..1 (bentuk gelombang float -1..1).

Catatan stereo: penggabungan ke mono oleh FFmpeg membuat dua kanal yang identik terukur
sekitar 1,41x lebih keras daripada audio mono yang sama. Itu hanya selisih skala; Trend memakai
rasio terhadap rata-rata video, jadi tidak terpengaruh selama satu video diukur dengan cara sama.

Keterbatasan (sudah dicatat di audit): RMS naik juga karena musik, tepuk tangan, atau
mikrofon yang dekat, bukan hanya karena isi yang menarik. Tidak ada normalisasi
loudness (misalnya LUFS) di sini.
"""
import math
import sys
from pathlib import Path

from .models import EnergyProfile

LANGKAH_BAWAAN = 1.0        # detik per nilai energi
LAJU_SAMPEL = 16000


def _rms_per_langkah(potongan, jumlah_sampel_per_langkah: int, sisa: dict, hasil: list):
    """Menambah potongan sampel (array numpy 1-D) ke kantong waktu; kantong penuh -> RMS."""
    import numpy as np
    n = len(potongan)
    i = 0
    while i < n:
        ruang = jumlah_sampel_per_langkah - sisa["n"]
        ambil = potongan[i:i + ruang]
        sisa["jumlah_kuadrat"] += float(np.dot(ambil, ambil))
        sisa["n"] += len(ambil)
        i += len(ambil)
        if sisa["n"] >= jumlah_sampel_per_langkah:
            hasil.append(math.sqrt(sisa["jumlah_kuadrat"] / sisa["n"]))
            sisa["n"], sisa["jumlah_kuadrat"] = 0, 0.0


def hitung_energi(path_media, langkah: float = LANGKAH_BAWAAN) -> EnergyProfile:
    """Profil energi RMS dari audio/video.

    Berkas tidak ada -> FileNotFoundError. Langkah tidak valid, berkas tak bisa dibaca,
    atau tanpa jalur audio -> ValueError. Kantong terakhir yang belum penuh tetap
    dihitung dari sampel yang ada.
    """
    if isinstance(langkah, bool) or not isinstance(langkah, (int, float)) \
            or not math.isfinite(langkah) or langkah <= 0:
        raise ValueError("langkah harus angka positif")
    jalur = Path(path_media)
    if not jalur.is_file():
        raise FileNotFoundError(f"Berkas tidak ditemukan: {jalur}")
    try:
        import av
        import numpy as np  # noqa: F401
    except ImportError:
        raise RuntimeError("PyAV/numpy belum terpasang. Jalankan: pip install -r requirements.txt") from None

    per_langkah = max(1, int(round(langkah * LAJU_SAMPEL)))
    hasil: list = []
    sisa = {"n": 0, "jumlah_kuadrat": 0.0}
    try:
        with av.open(str(jalur)) as wadah:
            if not wadah.streams.audio:
                raise ValueError("berkas tidak memiliki jalur audio")
            pengubah = av.AudioResampler(format="flt", layout="mono", rate=LAJU_SAMPEL)
            for frame in wadah.decode(audio=0):
                for f in (pengubah.resample(frame) or []):
                    _rms_per_langkah(f.to_ndarray().reshape(-1), per_langkah, sisa, hasil)
            for f in (pengubah.resample(None) or []):
                _rms_per_langkah(f.to_ndarray().reshape(-1), per_langkah, sisa, hasil)
    except av.error.FFmpegError as e:
        raise ValueError(f"audio tidak dapat dibaca: {e}") from None
    if sisa["n"] > 0:
        hasil.append(math.sqrt(sisa["jumlah_kuadrat"] / sisa["n"]))
    if not hasil:
        raise ValueError("audio kosong (tidak ada sampel)")
    return EnergyProfile(float(langkah), [round(x, 6) for x in hasil])


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Ringkasan energi suara per detik.")
    ap.add_argument("media")
    ap.add_argument("--langkah", type=float, default=LANGKAH_BAWAAN)
    arg = ap.parse_args(argv)
    try:
        p = hitung_energi(arg.media, arg.langkah)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    v = p.values
    rata = sum(v) / len(v)
    print(f"Langkah       : {p.step} dtk")
    print(f"Jumlah nilai  : {len(v)} (sekitar {len(v) * p.step:.1f} dtk)")
    print(f"Rata-rata RMS : {rata:.4f}")
    print(f"Terkecil      : {min(v):.4f}   Terbesar: {max(v):.4f}")
    print(f"Nilai nol     : {sum(1 for x in v if x == 0)} langkah (hening mutlak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
