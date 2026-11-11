"""cek_calon_hening.py: pengecekan HANYA-BACA, apakah calon panjang memuat keheningan panjang.

Pertanyaan yang dijawab:
  1. Berapa calon yang melintasi jeda panjang (bawaan: >= 10 dtk)?
  2. Berapa dari calon di atas 40 dtk yang memuat jeda itu? (menguji dugaan bahwa
     ekor panjang durasi calon hanya berisi keheningan)
  3. Bagaimana skor dan peringkat calon-calon itu di antara semua calon?
  4. Apakah ada yang masuk klip terpilih (Top-N)?

Skrip ini memakai fungsi asli (split_sentences, build_candidates, build_idf,
nilai_calon, pilih_klip) apa adanya. Tidak mengubah core/, scoring, seleksi,
maupun berkas masukan; tidak menulis berkas apa pun.

Cara pakai:
    python tools/cek_calon_hening.py storage/uji2/kata.json
    python tools/cek_calon_hening.py storage/uji2/kata.json --media storage/uji2/video.mp4
    python tools/cek_calon_hening.py storage/uji2/kata.json --ambang 2.0 --n 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.scoring import build_idf, nilai_calon  # noqa: E402
from core.segments import build_candidates, split_sentences  # noqa: E402
from core.selection import pilih_klip  # noqa: E402
from core.transcribe import dari_json  # noqa: E402


def _mmss(d: float) -> str:
    return f"{int(d // 60):02d}:{int(d % 60):02d}"


def cari_jeda(kata, ambang: float) -> list[tuple[float, float, float]]:
    """Daftar (durasi, awal, akhir) jeda antar kata >= ambang, urut waktu."""
    hasil = []
    for i in range(len(kata) - 1):
        d = kata[i + 1].start - kata[i].end
        if d >= ambang:
            hasil.append((d, kata[i].end, kata[i + 1].start))
    return hasil


def melintasi(calon, awal: float, akhir: float) -> bool:
    return calon.start < awal and calon.end > akhir


def periksa(kata, ambang: float = 10.0, n: int = 3, energi=None,
            min_sec: float = 20, max_sec: float = 60, batas_panjang: float = 40.0) -> dict:
    kalimat = split_sentences(kata)
    calon = build_candidates(kalimat, min_sec=min_sec, max_sec=max_sec)
    model = build_idf(kalimat)
    pen = nilai_calon(calon, model, energi)
    seleksi = pilih_klip(pen.dinilai, n)

    # skor & peringkat per indeks calon
    urut = sorted(range(len(pen.dinilai)), key=lambda i: pen.dinilai[i].score, reverse=True)
    peringkat = {pen.indeks_dinilai[i]: r + 1 for r, i in enumerate(urut)}
    skor = {pen.indeks_dinilai[i]: pen.dinilai[i] for i in range(len(pen.dinilai))}
    ditolak = {i for i, _ in pen.ditolak}
    terpilih_awal = {(round(s.start, 3), round(s.end, 3)) for s in seleksi.terpilih}

    jeda = cari_jeda(kata, ambang)
    panjang = [i for i, c in enumerate(calon) if c.duration > batas_panjang]

    rincian = []
    for d, a, b in jeda:
        ids = [i for i, c in enumerate(calon) if melintasi(c, a, b)]
        baris = []
        for i in ids:
            c = calon[i]
            s = skor.get(i)
            baris.append({
                "indeks": i, "mulai": c.start, "akhir": c.end, "durasi": c.duration,
                "porsi_hening": d / c.duration,
                "ditolak_scoring": i in ditolak,
                "skor": s.score if s else None,
                "hook": s.hook if s else None, "flow": s.flow if s else None,
                "value": s.value if s else None, "trend": s.trend if s else None,
                "peringkat": peringkat.get(i),
                "terpilih": (round(c.start, 3), round(c.end, 3)) in terpilih_awal,
            })
        rincian.append({"durasi": d, "awal": a, "akhir": b, "calon": baris})

    ids_melintas_semua = {r["indeks"] for j in rincian for r in j["calon"]}
    return {
        "n_kata": len(kata), "n_calon": len(calon), "n_dinilai": len(pen.dinilai),
        "n_ditolak_scoring": len(pen.ditolak), "n_terpilih": len(seleksi.terpilih),
        "energi_dipakai": energi is not None,
        "batas_panjang": batas_panjang,
        "n_calon_panjang": len(panjang),
        "n_calon_panjang_yang_melintasi": sum(1 for i in panjang if i in ids_melintas_semua),
        "n_calon_melintasi_semua_jeda": len(ids_melintas_semua),
        "jeda": rincian,
        "terpilih": [(s.start, s.end, s.score) for s in seleksi.terpilih],
        "skor_tertinggi": max((s.score for s in pen.dinilai), default=None),
        "median_skor": (sorted(s.score for s in pen.dinilai)[len(pen.dinilai) // 2] if pen.dinilai else None),
    }


def cetak(h: dict, ambang: float) -> str:
    o = []
    o.append("=" * 72)
    o.append("CEK CALON YANG MEMUAT KEHENINGAN (hanya-baca)")
    o.append("=" * 72)
    o.append(f"Kata: {h['n_kata']}  Calon: {h['n_calon']}  Dinilai: {h['n_dinilai']}  "
             f"Ditolak scoring: {h['n_ditolak_scoring']}  Terpilih: {h['n_terpilih']}")
    o.append("Profil energi: " + ("dipakai" if h["energi_dipakai"] else "TIDAK dipakai (skor Trend hanya dari penanda emosi)"))
    if h["skor_tertinggi"] is not None:
        o.append(f"Skor semua calon: median {h['median_skor']:.1f}, tertinggi {h['skor_tertinggi']:.1f}")

    o.append(f"\n[A] Jeda >= {ambang:g} dtk: {len(h['jeda'])} buah")
    o.append(f"    Calon di atas {h['batas_panjang']:g} dtk: {h['n_calon_panjang']}; "
             f"yang melintasi salah satu jeda itu: {h['n_calon_panjang_yang_melintasi']}")
    o.append(f"    Calon yang melintasi minimal satu jeda tsb: {h['n_calon_melintasi_semua_jeda']} dari {h['n_calon']}")

    for g in h["jeda"]:
        o.append(f"\n[B] Jeda {g['durasi']:.2f} dtk pada {_mmss(g['awal'])}-{_mmss(g['akhir'])}: "
                 f"{len(g['calon'])} calon melintasinya")
        if not g["calon"]:
            continue
        o.append("     mulai  akhir  durasi  hening%  skor  hook  flow  value trend  peringkat  catatan")
        for r in sorted(g["calon"], key=lambda r: r["mulai"]):
            catatan = []
            if r["terpilih"]:
                catatan.append("TERPILIH")
            if r["ditolak_scoring"]:
                catatan.append("ditolak scoring")
            skor_txt = "   -  " if r["skor"] is None else f"{r['skor']:5.1f}"
            def _s(x): return "  -  " if x is None else f"{x:5.2f}"
            per = "-" if r["peringkat"] is None else str(r["peringkat"])
            o.append(f"    {_mmss(r['mulai']):>6} {_mmss(r['akhir']):>6} {r['durasi']:6.1f}  {100 * r['porsi_hening']:5.0f}%  "
                     f"{skor_txt} {_s(r['hook'])} {_s(r['flow'])} {_s(r['value'])} {_s(r['trend'])}  "
                     f"{per:>8}  {' '.join(catatan)}")

    o.append("\n[C] Klip terpilih (Top-N)")
    for s, e, sk in h["terpilih"]:
        o.append(f"    {_mmss(s)}-{_mmss(e)}  durasi {e - s:.1f} dtk  skor {sk:.1f}")
    o.append("")
    return "\n".join(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cek calon yang memuat keheningan panjang (hanya-baca).")
    ap.add_argument("kata_json")
    ap.add_argument("--media", default=None, help="video/audio asal transkrip (untuk profil energi, sama seperti core.pipeline)")
    ap.add_argument("--ambang", type=float, default=10.0, help="jeda minimal yang dianggap keheningan panjang (bawaan 10 dtk)")
    ap.add_argument("--n", type=int, default=3, help="jumlah klip Top-N (bawaan 3)")
    ap.add_argument("--min-detik", type=float, default=20)
    ap.add_argument("--maks-detik", type=float, default=60)
    arg = ap.parse_args(argv)

    try:
        kata = dari_json(Path(arg.kata_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Gagal membaca {arg.kata_json}: {e}")
        return 1
    if not kata:
        print("Transkrip kosong.")
        return 1

    energi = None
    if arg.media:
        from core.audio import hitung_energi
        try:
            energi = hitung_energi(arg.media)
        except Exception as e:  # noqa: BLE001 - tampilkan apa adanya
            print(f"Gagal menghitung energi dari {arg.media}: {e}")
            return 1

    print(cetak(periksa(kata, arg.ambang, arg.n, energi, arg.min_detik, arg.maks_detik), arg.ambang))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
