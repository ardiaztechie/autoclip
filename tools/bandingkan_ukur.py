"""bandingkan_ukur.py: membandingkan dua laporan ukur.json (hanya-baca).

Membaca dua berkas hasil `tools/ukur_durasi.py --simpan ...` dan mencetak tabel
berdampingan. Tidak menulis apa pun.

Cara pakai:
    python tools/bandingkan_ukur.py storage/uji2/ukur.json storage/uji/ukur.json
    python tools/bandingkan_ukur.py A.json B.json --nama-a debat --nama-b podcast
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.ukur_durasi import persentil  # noqa: E402


def _ambil(d: dict, *jalur, bawaan=None):
    for k in jalur:
        if not isinstance(d, dict) or k not in d:
            return bawaan
        d = d[k]
    return d


def _fmt(x, satuan: str = "", desimal: int = 2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, int):
        return f"{x}{satuan}"
    return f"{x:.{desimal}f}{satuan}"


def _persen(bagian, total) -> float | None:
    return 100 * bagian / total if total else None


def baris_metrik(h: dict) -> list[tuple[str, object]]:
    a = h.get("awal", {})
    n_awal = a.get("n_awal")
    alasan = a.get("alasan", {})
    lewat = a.get("lewat_batas", [])
    terpanjang_dibuat = a.get("terpanjang_diambil", [])
    terpanjang_sah = a.get("terpanjang_sah", [])
    sah = a.get("n_sah_tanpa_batas_per_start")
    hilang = a.get("n_hilang_per_start")
    return [
        ("Durasi transkrip (menit)", (_ambil(h, "video", "durasi_detik") or 0) / 60),
        ("Jumlah kata", _ambil(h, "video", "n_kata")),
        ("--- KALIMAT", None),
        ("Jumlah kalimat", _ambil(h, "kalimat", "n")),
        ("Durasi kalimat: median (dtk)", _ambil(h, "kalimat", "durasi", "median")),
        ("Durasi kalimat: p90 (dtk)", _ambil(h, "kalimat", "durasi", "p90")),
        ("Kata per kalimat: median", _ambil(h, "kalimat", "kata_per_kalimat", "median")),
        ("Kalimat bertanda akhir (%)", _ambil(h, "kalimat", "persen_bertanda_akhir")),
        ("--- JEDA", None),
        ("Jeda antar kalimat: median (dtk)", _ambil(h, "jeda", "antar_kalimat", "median")),
        ("Jeda antar kalimat: p90 (dtk)", _ambil(h, "jeda", "antar_kalimat", "p90")),
        ("Jeda antar kalimat: maks (dtk)", _ambil(h, "jeda", "antar_kalimat", "maks")),
        ("Jeda dalam kalimat: p90 (dtk)", _ambil(h, "jeda", "dalam_kalimat", "p90")),
        ("Jeda antar kata > jeda_maks (jumlah)", _ambil(h, "jeda", "n_jeda_lebih_dari_jeda_maks")),
        ("--- CALON YANG TERBENTUK", None),
        ("Jumlah calon", _ambil(h, "calon", "n")),
        ("Durasi calon: median (dtk)", _ambil(h, "calon", "durasi", "median")),
        ("Durasi calon: rata-rata (dtk)", _ambil(h, "calon", "durasi", "rata2")),
        ("Durasi calon: p90 (dtk)", _ambil(h, "calon", "durasi", "p90")),
        ("Durasi calon: maks (dtk)", _ambil(h, "calon", "durasi", "maks")),
        ("--- PENGARUH per_start", None),
        ("Titik awal berhenti karena per_start (%)", _persen(alasan.get("per_start", 0), n_awal)),
        ("Titik akhir sah bila per_start tak dibatasi", sah),
        ("Titik akhir sah yang tak dibuat", hilang),
        ("  ... sebagai % dari yang sah", _persen(hilang, sah) if sah is not None else None),
        ("Terpanjang yang dibuat per awal: median (dtk)", persentil(terpanjang_dibuat, 50)),
        ("Terpanjang yang sah per awal: median (dtk)", persentil(terpanjang_sah, 50)),
        ("--- PENGARUH maks_sec", None),
        ("Titik awal berhenti karena maks_sec (%)", _persen(alasan.get("maks_sec", 0), n_awal)),
        ("Titik awal tanpa calon (%)", _persen(alasan.get("tanpa_calon", 0), n_awal)),
        ("Awal yang akan menabrak maks_sec (jumlah)", len(lewat) if a else None),
        ("Lewat batas titik akhir pertama: median (dtk)", persentil(lewat, 50)),
        ("Lewat batas titik akhir pertama: p90 (dtk)", persentil(lewat, 90)),
        ("Lewat batas titik akhir pertama: maks (dtk)", max(lewat) if lewat else None),
        ("--- JEDA TERPANJANG", None),
        ("Jeda terpanjang (dtk)", (_ambil(h, "jeda_panjang") or [{}])[0].get("durasi") if _ambil(h, "jeda_panjang") else None),
        ("  calon dibuat yang melintasinya",
         (_ambil(h, "jeda_panjang") or [{}])[0].get("calon_dibuat_melintasi") if _ambil(h, "jeda_panjang") else None),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bandingkan dua laporan ukur.json.")
    ap.add_argument("a", help="laporan pertama (ukur.json)")
    ap.add_argument("b", help="laporan kedua (ukur.json)")
    ap.add_argument("--nama-a", default="A")
    ap.add_argument("--nama-b", default="B")
    arg = ap.parse_args(argv)

    try:
        ha = json.loads(Path(arg.a).read_text(encoding="utf-8"))
        hb = json.loads(Path(arg.b).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Gagal membaca laporan: {e}")
        return 1

    pa, pb = ha.get("parameter", {}), hb.get("parameter", {})
    if pa != pb:
        print(f"PERINGATAN: parameter berbeda!  {arg.nama_a}: {pa}  |  {arg.nama_b}: {pb}\n")

    ma, mb = baris_metrik(ha), baris_metrik(hb)
    lebar = max(len(n) for n, _ in ma) + 2
    print(f"{'Metrik':<{lebar}}{arg.nama_a:>14}{arg.nama_b:>14}")
    print("-" * (lebar + 28))
    for (nama, va), (_, vb) in zip(ma, mb):
        if nama.startswith("---"):
            print(f"\n{nama[4:]}")
            continue
        print(f"{nama:<{lebar}}{_fmt(va):>14}{_fmt(vb):>14}")
    print("\n'n/a' = tidak tersedia (mis. laporan dibuat dengan versi skrip lama atau tidak ada jeda >= 1 dtk).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
