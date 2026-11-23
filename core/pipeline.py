"""pipeline.py: menyambung rantai kata -> kalimat -> calon -> skor -> seleksi (tanpa video).

Tidak ada rumus baru di sini. Modul ini hanya MEMANGGIL modul yang sudah ada:
segments.split_sentences, segments.build_candidates, scoring.build_idf,
scoring.nilai_calon, selection.pilih_klip. Nilai awal ikut modul masing-masing.

Tanpa --media, profil energi suara tidak dipakai: Trend hanya dari penanda emosi
(energi=None). Dengan --media, energi RMS per detik dihitung (core.audio) dan dipakai.
Skor kedua mode TIDAK setara, jangan dibandingkan langsung.

Cara pakai (dari folder proyek, .venv aktif):
    python -m core.pipeline storage/uji/kata.json --n 3 --simpan storage/uji/klip.json
    python -m core.pipeline storage/uji/kata.json --media storage/uji/video_uji.mp4
"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .audio import hitung_energi
from .scoring import build_idf, nilai_calon, nilai_huruf
from .segments import JEDA_MAKS_CALON_BAWAAN, build_candidates, split_sentences
from .varian import JUMLAH_BAND_BAWAAN, build_candidates_varian
from .selection import pilih_klip
from .transcribe import dari_json


# --- Parameter eksperimental (belum punya dasar riset; disetel dari uji) -----------------
DETIK_PER_KLIP_BAWAAN = 75.0         # jumlah klip otomatis = durasi video / angka ini (tebakan, perlu disetel)
TINGKAT_JUMLAH = {                   # "sedikit/sedang/banyak" -> detik video per klip (tebakan)
    "jarang": 120.0,
    "sedang": DETIK_PER_KLIP_BAWAAN,
    "rapat": 50.0,
}
TOLERANSI_OTOMATIS = 20.0            # detik di atas maks pada durasi "otomatis" (keputusan user)
PRESET_DURASI = {                    # nama -> (min_detik, maks_detik)
    "otomatis": (30.0, 60.0),        # bawaan: + toleransi 20 dtk (maks 80), mode calon varian
    "pendek": (15.0, 30.0),
    "sedang": (30.0, 60.0),
    "panjang": (60.0, 90.0),
    "sangat_panjang": (90.0, 120.0),   # sampai 2 menit
    "ekstra_panjang": (120.0, 180.0),  # sampai 3 menit
}


def jumlah_klip_otomatis(durasi_video_detik: float, detik_per_klip: float = DETIK_PER_KLIP_BAWAAN) -> int:
    """Jumlah klip menurut durasi video: 1 klip per `detik_per_klip` detik, minimal 1."""
    if not (detik_per_klip > 0):
        raise ValueError("detik_per_klip harus > 0")
    if not (durasi_video_detik >= 0):
        raise ValueError("durasi video tidak boleh negatif")
    return max(1, int(durasi_video_detik / detik_per_klip))


@dataclass(frozen=True)
class HasilRantai:
    jumlah_kata: int
    jumlah_kalimat: int
    jumlah_calon: int
    jumlah_dinilai: int
    ditolak_scoring: list          # [(nomor, alasan)]
    klip: list                     # list[ScoredCandidate] terpilih, urut waktu mulai
    ditolak_seleksi: list          # [(nomor, alasan)]
    energi_dipakai: bool


def jalankan_rantai(kata, n: int = 3, energi=None, *, min_detik: float = 20, maks_detik: float = 60,
                    jeda_maks_calon: float | None = JEDA_MAKS_CALON_BAWAAN,
                    mode_calon: str = "lama", jumlah_band: int = JUMLAH_BAND_BAWAAN,
                    toleransi: float = 0.0) -> HasilRantai:
    """kata: list[Word]. Mengembalikan ringkasan tiap tahap dan klip terpilih.

    min_detik dan maks_detik = rentang durasi calon klip (bawaan 20-60 dtk, sesuai rencana).
    jeda_maks_calon = calon yang memuat jeda antar kalimat lebih panjang dari ini tidak dibuat
    (None = mati, perilaku lama).
    mode_calon: "lama" (bawaan, per_start=3) atau "varian" (perbaikan B, EKSPERIMENTAL: beberapa panjang
    per titik awal; lihat core/varian.py). jumlah_band dan toleransi hanya dipakai pada mode "varian"."""
    if mode_calon not in ("lama", "varian"):
        raise ValueError("mode_calon harus 'lama' atau 'varian'")
    if not (min_detik > 0 and maks_detik >= min_detik):
        raise ValueError("durasi harus: 0 < min_detik <= maks_detik")
    kalimat = split_sentences(kata)
    if mode_calon == "varian":
        calon = build_candidates_varian(kalimat, min_sec=min_detik, max_sec=maks_detik, jumlah_band=jumlah_band,
                                        jeda_maks_calon=jeda_maks_calon, toleransi_sec=toleransi)
    else:
        calon = build_candidates(kalimat, min_sec=min_detik, max_sec=maks_detik, jeda_maks_calon=jeda_maks_calon)
    model = build_idf(kalimat)
    penilaian = nilai_calon(calon, model, energi)
    seleksi = pilih_klip(penilaian.dinilai, n)
    return HasilRantai(len(kata), len(kalimat), len(calon), len(penilaian.dinilai),
                       penilaian.ditolak, seleksi.terpilih, seleksi.ditolak, energi is not None)


def klip_ke_dict(k) -> dict:
    return {
        "mulai": round(k.start, 3), "akhir": round(k.end, 3), "durasi": round(k.end - k.start, 3),
        "skor": round(k.score, 2), "huruf": nilai_huruf(k.score),
        "hook": round(k.hook, 3), "flow": round(k.flow, 3),
        "value": round(k.value, 3), "trend": round(k.trend, 3),
        "teks": k.candidate.text,
    }


def _mmss(d: float) -> str:
    return f"{int(d // 60):02d}:{d % 60:04.1f}"


def _tampil(h: HasilRantai) -> str:
    baris = [
        f"Kata            : {h.jumlah_kata}",
        f"Kalimat         : {h.jumlah_kalimat}",
        f"Calon clip      : {h.jumlah_calon}",
        f"Lolos penilaian : {h.jumlah_dinilai} (ditolak: {len(h.ditolak_scoring)})",
        f"Klip terpilih   : {len(h.klip)} (ditolak seleksi: {len(h.ditolak_seleksi)})",
        "Trend           : " + ("dengan energi suara" if h.energi_dipakai
                                else "HANYA penanda emosi (energi belum dipakai)"),
        "",
    ]
    for i, k in enumerate(h.klip, 1):
        d = klip_ke_dict(k)
        baris += [
            f"#{i}  {_mmss(d['mulai'])} - {_mmss(d['akhir'])} ({d['durasi']:.0f} dtk)  "
            f"skor {d['skor']:.1f} ({d['huruf']})",
            f"    hook {d['hook']:.2f}  flow {d['flow']:.2f}  value {d['value']:.2f}  trend {d['trend']:.2f}",
            f"    \"{d['teks'][:160]}{'...' if len(d['teks']) > 160 else ''}\"",
        ]
    if not h.klip:
        baris.append("(tidak ada klip terpilih)")
    return "\n".join(baris)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rantai terminal: kata -> klip terpilih.")
    ap.add_argument("kata_json", help="berkas JSON hasil core.transcribe --simpan")
    ap.add_argument("--n", type=int, default=None,
                    help=f"jumlah klip; kosong = otomatis menurut --tingkat (eksperimental)")
    ap.add_argument("--tingkat", choices=tuple(TINGKAT_JUMLAH), default="sedang",
                    help="dipakai bila --n kosong: jarang=1 klip/120 dtk video, sedang=1/75 dtk, rapat=1/50 dtk (tebakan)")
    ap.add_argument("--durasi", choices=tuple(PRESET_DURASI), default="otomatis",
                    help="otomatis (bawaan) = 30-60 dtk + toleransi 20; pendek 15-30; sedang 30-60; panjang 60-90 dtk. "
                         "Isi --min-detik/--maks-detik sendiri untuk angka bebas (menggantikan pilihan ini)")
    ap.add_argument("--min-detik", type=float, default=None, help="durasi klip minimum (angka bebas)")
    ap.add_argument("--maks-detik", type=float, default=None, help="durasi klip maksimum (angka bebas)")
    ap.add_argument("--jeda-maks-calon", type=float, default=JEDA_MAKS_CALON_BAWAAN,
                    help=f"calon yang memuat jeda antar kalimat lebih panjang dari ini (dtk) tidak dibuat; "
                         f"0 = mati, perilaku lama (bawaan {JEDA_MAKS_CALON_BAWAAN:g}, eksperimental)")
    ap.add_argument("--mode-calon", choices=("lama", "varian"), default="varian",
                    help="varian (bawaan CLI) = beberapa panjang per titik awal (EKSPERIMENTAL); lama = per_start=3")
    ap.add_argument("--varian", type=int, default=JUMLAH_BAND_BAWAAN,
                    help=f"jumlah pita durasi pada mode varian (bawaan {JUMLAH_BAND_BAWAAN}, hipotesis)")
    ap.add_argument("--toleransi", type=float, default=None,
                    help="mode varian: detik di atas maks yang boleh dipakai bila batasnya sangat baik "
                         f"(bawaan: {TOLERANSI_OTOMATIS:g} untuk durasi otomatis, 0 untuk pilihan lain)")
    ap.add_argument("--media", default=None, help="video/audio asal transkrip, untuk menghitung energi suara")
    ap.add_argument("--simpan", default=None, help="simpan klip terpilih ke berkas JSON")
    arg = ap.parse_args(argv)
    try:
        kata = dari_json(Path(arg.kata_json).read_text(encoding="utf-8"))
        energi = hitung_energi(arg.media) if arg.media else None
        n = arg.n if arg.n is not None else jumlah_klip_otomatis(kata[-1].end if kata else 0.0, TINGKAT_JUMLAH[arg.tingkat])
        if arg.min_detik is not None or arg.maks_detik is not None:
            mn = arg.min_detik if arg.min_detik is not None else 20.0
            mk = arg.maks_detik if arg.maks_detik is not None else 60.0
        else:
            mn, mk = PRESET_DURASI[arg.durasi]
        tol = arg.toleransi if arg.toleransi is not None else (
            TOLERANSI_OTOMATIS if arg.durasi == "otomatis" and arg.min_detik is None and arg.maks_detik is None else 0.0)
        hasil = jalankan_rantai(kata, n, energi, min_detik=mn, maks_detik=mk,
                                jeda_maks_calon=arg.jeda_maks_calon if arg.jeda_maks_calon > 0 else None,
                                mode_calon=arg.mode_calon, jumlah_band=arg.varian, toleransi=tol)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    print(_tampil(hasil))
    if arg.simpan:
        tujuan = Path(arg.simpan)
        tujuan.parent.mkdir(parents=True, exist_ok=True)
        tujuan.write_text(json.dumps([klip_ke_dict(k) for k in hasil.klip], ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"\nKlip disimpan ke: {tujuan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
