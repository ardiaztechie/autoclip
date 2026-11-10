"""pipeline.py: menyambung rantai kata -> kalimat -> calon -> skor -> seleksi (tanpa video).

Tidak ada rumus baru di sini. Modul ini hanya MEMANGGIL modul yang sudah ada:
segments.split_sentences, segments.build_candidates, scoring.build_idf,
scoring.nilai_calon, selection.pilih_klip. Nilai awal ikut modul masing-masing.

Profil energi suara BELUM dihitung (itu tahap berikutnya), jadi Trend hanya dari penanda
emosi (energi=None). Skor dari mode ini TIDAK setara dengan skor yang memakai energi.

Cara pakai (dari folder proyek, .venv aktif):
    python -m core.pipeline storage/uji/kata.json --n 3 --simpan storage/uji/klip.json
"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .scoring import build_idf, nilai_calon, nilai_huruf
from .segments import build_candidates, split_sentences
from .selection import pilih_klip
from .transcribe import dari_json


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


def jalankan_rantai(kata, n: int = 3, energi=None) -> HasilRantai:
    """kata: list[Word]. Mengembalikan ringkasan tiap tahap dan klip terpilih."""
    kalimat = split_sentences(kata)
    calon = build_candidates(kalimat)
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
    ap.add_argument("--n", type=int, default=3, help="jumlah klip (bawaan 3)")
    ap.add_argument("--simpan", default=None, help="simpan klip terpilih ke berkas JSON")
    arg = ap.parse_args(argv)
    try:
        kata = dari_json(Path(arg.kata_json).read_text(encoding="utf-8"))
        hasil = jalankan_rantai(kata, arg.n)
    except (OSError, ValueError) as e:
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
