"""penekanan.py: menentukan saat pembicara MENEKANKAN sesuatu, untuk zoom in (punch-in).

Dua pemicu (salah satu cukup):
  - volume : energi suara melonjak jauh di atas biasanya di sekitarnya, dan sedang ada ucapan
  - emosi  : kata emosi, frasa emosi, atau tanda seru di transkrip (daftar dipakai ulang dari scoring.py)

Hasilnya daftar selang waktu [(awal, akhir)] pada waktu video asal. Zoom itu sendiri dilakukan
render.py; modul ini hanya memutuskan KAPAN, dengan batas agar tidak kebanyakan zoom:
durasi maksimum per zoom, jarak minimum antar zoom, dan porsi maksimum dari durasi klip.
Bila terlalu banyak, yang lebih awal dipertahankan (urut waktu, bukan urut kekuatan).

Keterbatasan: energi suara juga naik karena tepuk tangan, tawa, atau batuk (ucapan yang sedang
berlangsung memfilter sebagian, bukan semua). Transkrip Whisper bisa salah kata atau salah tanda
baca. Seluruh angka di bawah adalah nilai AWAL YANG BELUM DIUJI.

Cara pakai dari terminal (diagnosis, tidak membuat video):
    python -m core.penekanan video.mp4 --mulai 60 --akhir 120 --kata kata.json
"""
import argparse
import math
import sys
from pathlib import Path

from .scoring import FRASA_EMOSI, KATA_EMOSI, _bersihkan_kata

# --- Nilai awal (eksperimental) ---------------------------------------------
FAKTOR_ZOOM = 1.25            # jendela dipersempit menjadi 1/1,25 (zoom in 25%)
LANGKAH_ENERGI = 0.25         # detik per nilai energi untuk mendeteksi lonjakan volume
RASIO_VOLUME = 1.5            # energi >= 1,8x median di sekitarnya
JENDELA_BASIS_VOLUME = 10.0   # detik; lebar jendela pembanding (median)
LANTAI_VOLUME = 0.01          # RMS (0-1) minimum; di bawah ini dianggap hening
DURASI_VOLUME_MIN = 0.4       # detik beruntun agar lonjakan volume dihitung
AWAL_ZOOM = 0.1               # detik; zoom mulai sedikit sebelum puncak
TAHAN_ZOOM = 0.3              # detik; zoom bertahan sedikit sesudah puncak
DURASI_ZOOM_MIN = 0.8         # detik; zoom yang lebih singkat diperpanjang sampai sepanjang ini
DURASI_ZOOM_MAKS = 1.5        # detik; satu zoom tidak lebih lama dari ini
JARAK_ZOOM_MIN = 2.0          # detik jeda antar dua zoom
FRAKSI_ZOOM_MAKS = 0.35       # zoom paling banyak 35% dari durasi klip
DURASI_SISA_MIN = 0.3         # detik; potongan zoom yang lebih pendek dari ini dibuang


def _valid(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _median(nilai):
    n = sorted(nilai)
    if not n:
        return 0.0
    m = len(n) // 2
    return n[m] if len(n) % 2 else (n[m - 1] + n[m]) / 2


def peristiwa_emosi(kata) -> list:
    """[(awal, akhir, alasan)] untuk kata emosi, frasa emosi, dan tanda seru."""
    daftar = [k for k in (kata or []) if isinstance(getattr(k, "text", None), str)
              and _valid(getattr(k, "start", None)) and _valid(getattr(k, "end", None)) and k.end >= k.start]
    hasil = []
    for i, k in enumerate(daftar):
        bersih = _bersihkan_kata(k.text)
        if "!" in k.text:
            hasil.append((k.start, k.end, "!"))
        elif bersih in KATA_EMOSI:
            hasil.append((k.start, k.end, bersih))
        if i + 1 < len(daftar):
            pasangan = bersih + " " + _bersihkan_kata(daftar[i + 1].text)
            if pasangan in FRASA_EMOSI:
                hasil.append((k.start, daftar[i + 1].end, pasangan))
    return hasil


def rasio_energi(energi) -> list:
    """Per nilai energi: rasio terhadap median sekitarnya (0.0 bila energi hening atau profil rusak)."""
    langkah, nilai = getattr(energi, "step", None), getattr(energi, "values", None)
    if not _valid(langkah) or langkah <= 0 or not isinstance(nilai, (list, tuple)) or not nilai:
        return []
    if not all(_valid(v) and v >= 0 for v in nilai):
        return []
    sisi = max(1, int(round(JENDELA_BASIS_VOLUME / langkah)) // 2)
    hasil = []
    for i, v in enumerate(nilai):
        basis = _median(nilai[max(0, i - sisi): i + sisi + 1])
        hasil.append(v / basis if basis > 0 and v >= LANTAI_VOLUME else 0.0)
    return hasil


def statistik_volume(energi, mulai: float, akhir: float, ucapan=None) -> dict:
    """Ringkasan sebaran rasio energi di dalam [mulai, akhir], sebagai bahan menyetel RASIO_VOLUME."""
    rasio = rasio_energi(energi)
    if not rasio:
        return {}
    langkah = energi.step
    nilai = [r for i, r in enumerate(rasio)
             if mulai <= i * langkah + langkah / 2 <= akhir and (ucapan is None or ucapan(i * langkah + langkah / 2))]
    if not nilai:
        return {}
    urut = sorted(nilai)
    persen = lambda q: urut[min(len(urut) - 1, int(q * len(urut)))]          # noqa: E731
    return {"jumlah": len(nilai), "p50": persen(0.50), "p90": persen(0.90), "p99": persen(0.99), "maks": urut[-1],
            "lebih_14": sum(r >= 1.4 for r in nilai), "lebih_16": sum(r >= 1.6 for r in nilai),
            "lebih_18": sum(r >= 1.8 for r in nilai), "lebih_22": sum(r >= 2.2 for r in nilai)}


def peristiwa_volume(energi, ucapan=None) -> list:
    """[(awal, akhir, "volume")] saat energi melonjak jauh di atas biasanya. energi = EnergyProfile."""
    langkah, nilai = getattr(energi, "step", None), getattr(energi, "values", None)
    if not _valid(langkah) or langkah <= 0 or not isinstance(nilai, (list, tuple)) or not nilai:
        return []
    if not all(_valid(v) and v >= 0 for v in nilai):
        return []
    n = len(nilai)
    sisi = max(1, int(round(JENDELA_BASIS_VOLUME / langkah)) // 2)
    min_bin = max(1, int(round(DURASI_VOLUME_MIN / langkah)))
    tanda = []
    for i in range(n):
        basis = _median(nilai[max(0, i - sisi): i + sisi + 1])
        ok = nilai[i] >= LANTAI_VOLUME and basis > 0 and nilai[i] >= RASIO_VOLUME * basis
        if ok and ucapan is not None:
            ok = bool(ucapan(i * langkah + langkah / 2))
        tanda.append(ok)
    hasil, mulai = [], None
    for i, t in enumerate(tanda + [False]):
        if t and mulai is None:
            mulai = i
        elif not t and mulai is not None:
            if i - mulai >= min_bin:
                hasil.append((mulai * langkah, i * langkah, "volume"))
            mulai = None
    return hasil


def _bentuk_selang(peristiwa, mulai: float, akhir: float) -> list:
    """Peristiwa -> selang zoom [(awal, akhir, alasan)] dalam rentang klip, dengan semua batas diterapkan."""
    selang = []
    for a, b, alasan in sorted(peristiwa):
        awal = a - AWAL_ZOOM
        ujung = max(b + TAHAN_ZOOM, awal + DURASI_ZOOM_MIN)
        if selang and awal <= selang[-1][1]:
            selang[-1] = (selang[-1][0], max(selang[-1][1], ujung), selang[-1][2] | {alasan})
        else:
            selang.append((awal, ujung, {alasan}))
    hasil, terakhir_akhir, total = [], -1e18, 0.0
    batas_total = FRAKSI_ZOOM_MAKS * (akhir - mulai)
    for a, b, alasan in selang:
        b = min(b, a + DURASI_ZOOM_MAKS)
        a, b = max(a, mulai), min(b, akhir)
        if b - a < DURASI_SISA_MIN or a - terakhir_akhir < JARAK_ZOOM_MIN:
            continue
        if total + (b - a) > batas_total + 1e-9:
            continue
        hasil.append((round(a, 3), round(b, 3), "+".join(sorted(alasan))))
        terakhir_akhir, total = b, total + (b - a)
    return hasil


def cari_penekanan(kata, mulai: float, akhir: float, energi=None, ucapan=None) -> list:
    """[(awal, akhir, alasan)] di dalam [mulai, akhir]. kata dan energi boleh None (pemicu itu dilewati)."""
    if not (_valid(mulai) and _valid(akhir)) or mulai < 0 or akhir <= mulai:
        raise ValueError("mulai harus >= 0 dan akhir harus lebih besar dari mulai")
    dalam = lambda a, b: b >= mulai and a <= akhir                       # noqa: E731
    peristiwa = [p for p in peristiwa_emosi(kata) if dalam(p[0], p[1])]
    if energi is not None:
        peristiwa += [p for p in peristiwa_volume(energi, ucapan) if dalam(p[0], p[1])]
    return _bentuk_selang(peristiwa, mulai, akhir)


def selang_penekanan(kata, mulai: float, akhir: float, energi=None, ucapan=None) -> list:
    """Hanya selang waktunya: [(awal, akhir)]."""
    return [(a, b) for a, b, _ in cari_penekanan(kata, mulai, akhir, energi, ucapan)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diagnosis: kapan zoom penekanan akan terjadi.")
    ap.add_argument("media")
    ap.add_argument("--mulai", type=float, required=True)
    ap.add_argument("--akhir", type=float, required=True)
    ap.add_argument("--kata", default=None, help="kata.json dari core.transcribe")
    arg = ap.parse_args(argv)
    try:
        from .audio import hitung_energi
        from .pembicara import ada_ucapan
        from .transcribe import dari_json
        kata = dari_json(Path(arg.kata).read_text(encoding="utf-8")) if arg.kata else None
        energi = hitung_energi(arg.media, LANGKAH_ENERGI)
        hasil = cari_penekanan(kata, arg.mulai, arg.akhir, energi, ada_ucapan(kata) if kata is not None else None)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    st = statistik_volume(energi, arg.mulai, arg.akhir, ada_ucapan(kata) if kata is not None else None)
    total = sum(b - a for a, b, _ in hasil)
    print(f"Zoom penekanan : {len(hasil)} kali, total {total:.1f} dtk dari {arg.akhir - arg.mulai:.0f} dtk "
          f"({total / (arg.akhir - arg.mulai):.0%}; batas {FRAKSI_ZOOM_MAKS:.0%})")
    for a, b, alasan in hasil:
        print(f"    {a:7.1f} - {b:7.1f} dtk  ({alasan})")
    if st:
        print(f"Rasio energi terhadap sekitarnya ({st['jumlah']} nilai saat ada ucapan, tiap {LANGKAH_ENERGI} dtk):")
        print(f"    median {st['p50']:.2f} | 90% {st['p90']:.2f} | 99% {st['p99']:.2f} | maks {st['maks']:.2f}  "
              f"(pemicu saat ini >= {RASIO_VOLUME})")
        print(f"    jumlah nilai >=1,4x: {st['lebih_14']} | >=1,6x: {st['lebih_16']} | "
              f">=1,8x: {st['lebih_18']} | >=2,2x: {st['lebih_22']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
