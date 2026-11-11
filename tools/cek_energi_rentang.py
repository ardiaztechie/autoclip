"""cek_energi_rentang.py: pengecekan HANYA-BACA kerasnya suara pada rentang waktu tertentu.

Berguna untuk memeriksa bagian video yang tidak punya kata di transkrip (jeda panjang):
apakah di sana benar-benar sunyi, ada suara non-bicara, atau ada ucapan yang tidak
tertranskripsi. Tidak mengubah berkas apa pun.

Yang dicetak per jendela waktu: energi rata-rata dibagi MEDIAN energi seluruh video
(rasio 1,0 = sekeras bicara biasa) dan jumlah kata transkrip di jendela itu
(bila kata.json diberikan).

Cara pakai:
    python tools/cek_energi_rentang.py storage/uji2/video.mp4 --mulai 20 --akhir 75
    python tools/cek_energi_rentang.py storage/uji2/video.mp4 --mulai 20 --akhir 75 --kata storage/uji2/kata.json

Catatan: rasio energi hanya petunjuk. Energi tinggi bisa musik atau tepuk tangan, bukan ucapan.
Untuk memastikan, putar bagian itu dan dengarkan.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _median(nilai: list[float]) -> float:
    s = sorted(nilai)
    if not s:
        return 0.0
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def per_jendela(profil, mulai: float, akhir: float, jendela: float, kata=None) -> dict:
    """Hitung rasio energi (terhadap median video) dan jumlah kata per jendela.

    profil: objek dengan .step (detik per nilai) dan .values (energi tiap langkah).
    """
    nilai = list(profil.values)
    median_video = _median([v for v in nilai if v > 0]) or 1e-12
    baris = []
    t = mulai
    while t < akhir - 1e-9:
        t2 = min(t + jendela, akhir)
        i0 = max(0, int(t // profil.step))
        i1 = min(len(nilai), max(i0 + 1, int(t2 // profil.step)))
        potong = nilai[i0:i1]
        rata = sum(potong) / len(potong) if potong else 0.0
        n_kata = None
        if kata is not None:
            n_kata = sum(1 for k in kata if t <= k.start < t2)
        baris.append({"mulai": t, "akhir": t2, "rasio": rata / median_video, "kata": n_kata})
        t = t2
    return {"median_video": median_video, "jendela": baris}


def _mmss(d: float) -> str:
    return f"{int(d // 60):02d}:{int(d % 60):02d}"


def cetak(h: dict) -> str:
    o = ["=" * 60, "ENERGI SUARA PER JENDELA (hanya-baca)", "=" * 60,
         "rasio 1,0 = sekeras median seluruh video (bicara biasa); mendekati 0 = sunyi", ""]
    o.append(" jendela        rasio   kata   gambaran")
    for b in h["jendela"]:
        r = b["rasio"]
        bar = "#" * min(40, int(round(r * 20)))
        kata = "  -  " if b["kata"] is None else f"{b['kata']:5d}"
        o.append(f" {_mmss(b['mulai'])}-{_mmss(b['akhir'])}   {r:6.2f}  {kata}   {bar}")
    o.append("")
    return "\n".join(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Energi suara per jendela waktu (hanya-baca).")
    ap.add_argument("media", help="video/audio")
    ap.add_argument("--mulai", type=float, default=0.0)
    ap.add_argument("--akhir", type=float, default=90.0)
    ap.add_argument("--jendela", type=float, default=5.0, help="lebar jendela, detik (bawaan 5)")
    ap.add_argument("--kata", default=None, help="kata.json untuk menghitung kata per jendela (opsional)")
    arg = ap.parse_args(argv)
    if not (arg.akhir > arg.mulai >= 0 and arg.jendela > 0):
        print("Rentang tidak valid: harus 0 <= mulai < akhir dan jendela > 0.")
        return 1

    from core.audio import hitung_energi
    from core.transcribe import dari_json
    try:
        profil = hitung_energi(arg.media)
        kata = dari_json(Path(arg.kata).read_text(encoding="utf-8")) if arg.kata else None
    except (OSError, ValueError, RuntimeError) as e:
        print(f"Gagal: {e}")
        return 1
    print(cetak(per_jendela(profil, arg.mulai, arg.akhir, arg.jendela, kata)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
