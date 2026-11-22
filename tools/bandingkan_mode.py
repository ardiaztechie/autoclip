"""bandingkan_mode.py: membandingkan klip terpilih mode "lama" vs mode "varian" (hanya-baca terhadap data asli).

Menjalankan rantai yang SAMA dua kali pada kata.json yang sama (mode lama dan mode varian),
mencetak perbandingan, dan (opsional) membuat LEMBAR PENILAIAN BUTA untuk penilaian manual:
  <awalan>_lembar.csv : klip diacak, tanpa kolom mode; diisi penilai
  <awalan>_kunci.json : kunci rahasia (klip mana dari mode apa); JANGAN dibuka sebelum menilai

Tidak mengubah core/, scoring, seleksi, maupun berkas masukan. Berkas lembar/kunci adalah berkas BARU.

Cara pakai:
    python tools/bandingkan_mode.py storage/uji2/kata.json --media storage/uji2/video.mp4 --n 5
    python tools/bandingkan_mode.py storage/uji2/kata.json --media storage/uji2/video.mp4 --n 8 --lembar storage/uji2/penilaian

Catatan: durasi klip tertera di lembar (diperlukan untuk menemukan klipnya) sehingga penilai
bisa menebak mode dari panjang klip. Bila perlu, penilai sebaiknya orang yang tidak mengetahui
rancangan ini, dan menilai dengan mendengarkan, bukan menghitung durasi.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.audio import hitung_energi  # noqa: E402
from core.pipeline import jalankan_rantai  # noqa: E402
from core.segments import split_sentences  # noqa: E402
from core.transcribe import dari_json  # noqa: E402
from core.varian import JUMLAH_BAND_BAWAAN, KATA_GANTUNG, _bersih, kualitas_batas  # noqa: E402


def _mmss(d: float) -> str:
    return f"{int(d // 60):02d}:{int(d % 60):02d}.{int(round((d % 1) * 10)) % 10}"


def ringkas_klip(klip, kalimat, q) -> list[dict]:
    """Rincian tiap klip terpilih: waktu, durasi, skor, dan sifat titik akhirnya."""
    akhir_ke_indeks = {round(s.end, 3): i for i, s in enumerate(kalimat)}
    hasil = []
    for k in klip:
        c = k.candidate
        i = akhir_ke_indeks.get(round(c.end, 3))
        terakhir = c.words[-1].text
        hasil.append({
            "mulai": c.start, "akhir": c.end, "durasi": c.duration, "skor": k.score,
            "bertanda_tegas": terakhir.rstrip().endswith((".", "?", "!")),
            "menggantung": _bersih(terakhir) in KATA_GANTUNG,
            "kualitas_batas": q[i] if i is not None else None,
            "teks_awal": c.sentences[0].text, "teks_akhir": c.sentences[-1].text,
            "teks": c.text,
        })
    return hasil


def _statistik(rincian: list[dict]) -> dict:
    d = sorted(r["durasi"] for r in rincian)
    if not d:
        return {"n": 0}
    m = len(d) // 2
    qs = [r["kualitas_batas"] for r in rincian if r["kualitas_batas"] is not None]
    return {
        "n": len(d), "durasi_min": d[0], "durasi_median": d[m] if len(d) % 2 else (d[m - 1] + d[m]) / 2,
        "durasi_rata2": sum(d) / len(d), "durasi_maks": d[-1],
        "tegas": sum(r["bertanda_tegas"] for r in rincian), "menggantung": sum(r["menggantung"] for r in rincian),
        "q_rata2": sum(qs) / len(qs) if qs else None,
        "skor_rata2": sum(r["skor"] for r in rincian) / len(rincian),
    }


def cetak(nama: str, rincian: list[dict]) -> list[str]:
    o = [f"--- MODE {nama.upper()} ---"]
    for i, r in enumerate(sorted(rincian, key=lambda r: r["mulai"]), 1):
        q = "-" if r["kualitas_batas"] is None else f"{r['kualitas_batas']:.2f}"
        o.append(f"  #{i} {_mmss(r['mulai'])}-{_mmss(r['akhir'])} ({r['durasi']:.1f} dtk) skor {r['skor']:.1f}  "
                 f"tanda tegas: {'ya' if r['bertanda_tegas'] else 'tidak'}  menggantung: "
                 f"{'ya' if r['menggantung'] else 'tidak'}  kualitas batas: {q}")
    s = _statistik(rincian)
    if s["n"]:
        qtxt = "-" if s["q_rata2"] is None else f"{s['q_rata2']:.2f}"
        o.append(f"  ringkasan: n={s['n']}  durasi min/median/rata2/maks = {s['durasi_min']:.1f}/{s['durasi_median']:.1f}/"
                 f"{s['durasi_rata2']:.1f}/{s['durasi_maks']:.1f} dtk  bertanda tegas {s['tegas']}/{s['n']}  "
                 f"menggantung {s['menggantung']}/{s['n']}  kualitas batas rata2 {qtxt}  skor rata2 {s['skor_rata2']:.1f}")
    return o


def buat_lembar(lama: list[dict], varian: list[dict], awalan: Path, seed: int) -> tuple[Path, Path]:
    """Lembar penilaian buta + kunci. Klip yang sama di kedua mode muncul SEKALI (ditandai di kunci)."""
    unik: dict[tuple[float, float], dict] = {}
    for mode, daftar in (("lama", lama), ("varian", varian)):
        for r in daftar:
            kunci = (round(r["mulai"], 2), round(r["akhir"], 2))
            unik.setdefault(kunci, {"rincian": r, "mode": []})["mode"].append(mode)
    baris = list(unik.values())
    random.Random(seed).shuffle(baris)

    lembar = awalan.with_name(awalan.name + "_lembar.csv")
    kunci_berkas = awalan.with_name(awalan.name + "_kunci.json")
    lembar.parent.mkdir(parents=True, exist_ok=True)
    with lembar.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "mulai", "akhir", "durasi_dtk", "teks_kalimat_awal", "teks_kalimat_akhir",
                    "gagasan_selesai (1=ya 0=tidak)", "menarik (1-5)", "catatan"])
        for i, b in enumerate(baris, 1):
            r = b["rincian"]
            w.writerow([i, _mmss(r["mulai"]), _mmss(r["akhir"]), f"{r['durasi']:.1f}",
                        r["teks_awal"], r["teks_akhir"], "", "", ""])
    kunci = {str(i): {"mode": b["mode"], "mulai": b["rincian"]["mulai"], "akhir": b["rincian"]["akhir"],
                      "skor": b["rincian"]["skor"]} for i, b in enumerate(baris, 1)}
    kunci_berkas.write_text(json.dumps({"seed": seed, "catatan": "JANGAN dibuka sebelum penilaian selesai.",
                                        "klip": kunci}, ensure_ascii=False, indent=2), encoding="utf-8")
    return lembar, kunci_berkas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bandingkan klip terpilih mode lama vs varian.")
    ap.add_argument("kata_json")
    ap.add_argument("--media", default=None, help="video asal (profil energi, sama seperti pipeline)")
    ap.add_argument("--n", type=int, default=5, help="jumlah klip per mode (bawaan 5)")
    ap.add_argument("--varian", type=int, default=JUMLAH_BAND_BAWAAN)
    ap.add_argument("--toleransi", type=float, default=0.0)
    ap.add_argument("--lembar", default=None, help="awalan berkas lembar penilaian buta, mis. storage/uji2/penilaian")
    ap.add_argument("--seed", type=int, default=1, help="benih pengacakan lembar (bawaan 1)")
    arg = ap.parse_args(argv)

    try:
        kata = dari_json(Path(arg.kata_json).read_text(encoding="utf-8"))
        energi = hitung_energi(arg.media) if arg.media else None
        lama = jalankan_rantai(kata, arg.n, energi, mode_calon="lama")
        varian = jalankan_rantai(kata, arg.n, energi, mode_calon="varian", jumlah_band=arg.varian, toleransi=arg.toleransi)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"Gagal: {e}")
        return 1

    kalimat = split_sentences(kata)
    q = kualitas_batas(kalimat) if kalimat else []
    r_lama = ringkas_klip(lama.klip, kalimat, q)
    r_varian = ringkas_klip(varian.klip, kalimat, q)

    print("=" * 72)
    print("PERBANDINGAN MODE CALON (hanya-baca)")
    print("=" * 72)
    print(f"Energi: {'dipakai' if energi else 'TIDAK dipakai (skor Trend tidak setara dengan hasil pipeline berenergi)'}")
    print(f"Calon: lama {lama.jumlah_calon} | varian {varian.jumlah_calon}  (varian={arg.varian} pita, toleransi={arg.toleransi:g} dtk)")
    print("Kualitas batas adalah ukuran buatan alat ini (hipotesis), BUKAN bukti klip lebih baik.\n")
    for baris in cetak("lama", r_lama) + [""] + cetak("varian", r_varian):
        print(baris)
    sama = {(round(r["mulai"], 2), round(r["akhir"], 2)) for r in r_lama} & \
           {(round(r["mulai"], 2), round(r["akhir"], 2)) for r in r_varian}
    print(f"\nKlip identik di kedua mode: {len(sama)}")

    if arg.lembar:
        lembar, kunci = buat_lembar(r_lama, r_varian, Path(arg.lembar), arg.seed)
        print(f"\nLembar penilaian buta : {lembar}")
        print(f"Kunci (jangan dibuka) : {kunci}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
