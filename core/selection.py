"""selection.py: memilih Top-N calon clip dari hasil scoring.

Modul ini TIDAK menghitung ulang Hook, Flow, Value, atau Trend. Ia hanya memakai
skor akhir yang sudah ada pada ScoredCandidate (atribut start, end, score) dan
memilih maksimal N klip yang tidak saling berbenturan.

DEFINISI (nilai awal, dapat diubah lewat parameter)
  Overlap  : lama waktu yang dipakai bersama dua klip, dibagi durasi klip yang LEBIH PENDEK.
               overlap = max(0, min(akhir_a, akhir_b) - max(mulai_a, mulai_b)) / min(durasi_a, durasi_b)
             Dibagi klip yang lebih pendek agar klip pendek yang berada di dalam klip
             panjang dihitung 100% (bukan kecil karena dibagi total gabungan).
             Batas: overlap <= OVERLAP_MAKS (0,20) DITERIMA; di atasnya ditolak.
  Jarak    : ATURAN_JARAK = "mulai" (nilai awal): selisih waktu MULAI kedua klip.
               jarak = |mulai_a - mulai_b|          harus >= JARAK_MIN (20 detik)
             Alternatif "celah": dari AKHIR klip yang lebih awal ke MULAI klip berikutnya.
               jarak = max(mulai) - min(akhir)       (negatif bila overlap)
             Pada "celah", jarak >= 20 detik berarti klip tidak boleh overlap sama sekali,
             sehingga aturan overlap 20% praktis tidak berfungsi. Itu sebabnya nilai
             awalnya "mulai": kedua aturan tetap sama-sama berlaku.

ALGORITMA
  Greedy dengan penekanan tumpang tindih (mirip Non-Maximum Suppression):
    1. buang kandidat yang datanya tidak valid (dicatat beserta alasannya)
    2. urutkan menurut skor tertinggi; skor sama -> mulai paling awal -> akhir paling awal
       -> urutan masukan (hasil selalu sama untuk masukan yang sama)
    3. ambil kandidat satu per satu bila cocok dengan SEMUA klip yang sudah terpilih
    4. berhenti setelah N klip, lalu urutkan hasil menurut waktu mulai

Penanganan masukan (konsisten dengan scoring.py): DATA bermasalah tidak membuat program
berhenti, melainkan dicatat pada `ditolak`. PARAMETER yang salah (n, batas, aturan) adalah
kesalahan pemrograman, sehingga memunculkan ValueError agar tidak tersembunyi.

Tidak ada asumsi rentang skor: skor boleh angka hingga apa pun asal bukan NaN/tak hingga.
Timestamp harus angka hingga, tidak negatif, dan akhir > mulai. Kandidat asli tidak diubah.

Cara mencoba tanpa video:
    python -m core.selection
"""
import math
import operator
import sys
from dataclasses import dataclass

from .models import Candidate, ScoredCandidate, Sentence, Word

# ===========================================================================
# PARAMETER (nilai awal, dapat diuji dan disetel)
# ===========================================================================
OVERLAP_MAKS = 0.20          # bagian maksimal (0-1) dari klip terpendek yang boleh dipakai bersama
JARAK_MIN = 20.0             # detik
ATURAN_JARAK = "mulai"       # "mulai" (mulai-ke-mulai) atau "celah" (akhir-ke-mulai)
ATURAN_VALID = ("mulai", "celah")
_TOLERANSI = 1e-9            # menyerap galat pembulatan desimal pada perbandingan batas


@dataclass(frozen=True)
class HasilSeleksi:
    terpilih: list           # ScoredCandidate terpilih, diurutkan menurut waktu mulai
    ditolak: list            # [(nomor_masukan, alasan)], nomor mulai dari 0
    indeks_terpilih: list    # nomor masukan tiap klip pada `terpilih`


# ===========================================================================
# ALAT BANTU
# ===========================================================================
def _angka_valid(x) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:    # bilangan bulat terlalu besar untuk float
        return False


def _baca(kandidat):
    """(mulai, akhir, skor) bila kandidat layak dipakai, atau (None, alasan)."""
    try:
        mulai, akhir, skor = kandidat.start, kandidat.end, kandidat.score
    except Exception:  # noqa: BLE001  objek bukan kandidat atau propertinya gagal dibaca
        return None, "bukan kandidat ber-skor (start, end, atau score tidak bisa dibaca)"
    if not (_angka_valid(mulai) and _angka_valid(akhir)):
        return None, "timestamp kosong atau bukan angka yang valid"
    if mulai < 0 or akhir < 0:
        return None, "timestamp negatif"
    if akhir <= mulai:
        return None, "durasi nol atau negatif (akhir tidak setelah mulai)"
    if not _angka_valid(skor):
        return None, "skor bukan angka yang valid"
    return (float(mulai), float(akhir), float(skor)), None


def _rasio_overlap(a, b) -> float:
    """Overlap dibagi durasi klip yang lebih pendek. a dan b = (mulai, akhir, skor)."""
    bersama = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    terpendek = min(a[1] - a[0], b[1] - b[0])
    return bersama / terpendek


def _jarak(a, b, aturan: str) -> float:
    if aturan == "mulai":
        return abs(a[0] - b[0])
    return max(a[0], b[0]) - min(a[1], b[1])


def _alasan_bentrok(a, b, overlap_maks: float, jarak_min: float, aturan: str):
    """Alasan penolakan bila a dan b berbenturan, atau None bila cocok."""
    rasio = _rasio_overlap(a, b)
    if rasio > overlap_maks + _TOLERANSI:
        return (f"overlap {rasio:.0%} melebihi batas {overlap_maks:.0%} "
                f"dengan klip terpilih {b[0]:g}-{b[1]:g} dtk")
    jarak = _jarak(a, b, aturan)
    if jarak < jarak_min - _TOLERANSI:
        nama = "selisih mulai" if aturan == "mulai" else "celah"
        return (f"{nama} {jarak:g} dtk kurang dari minimum {jarak_min:g} dtk "
                f"dengan klip terpilih {b[0]:g}-{b[1]:g} dtk")
    return None


def _periksa_parameter(n, overlap_maks, jarak_min, aturan_jarak) -> int:
    if isinstance(n, bool):
        raise ValueError("n harus bilangan bulat >= 0, bukan bool")
    try:
        n = operator.index(n)
    except TypeError:
        raise ValueError(f"n harus bilangan bulat >= 0, diterima: {n!r}") from None
    if n < 0:
        raise ValueError(f"n harus >= 0, diterima: {n}")
    if not _angka_valid(overlap_maks) or not 0.0 <= overlap_maks <= 1.0:
        raise ValueError(f"overlap_maks harus angka antara 0 dan 1, diterima: {overlap_maks!r}")
    if not _angka_valid(jarak_min) or jarak_min < 0:
        raise ValueError(f"jarak_min harus angka >= 0, diterima: {jarak_min!r}")
    if aturan_jarak not in ATURAN_VALID:
        raise ValueError(f"aturan_jarak harus salah satu dari {ATURAN_VALID}, diterima: {aturan_jarak!r}")
    return n


# ===========================================================================
# SELEKSI
# ===========================================================================
def pilih_klip(scored, n: int, *, overlap_maks: float = OVERLAP_MAKS,
               jarak_min: float = JARAK_MIN, aturan_jarak: str = ATURAN_JARAK) -> HasilSeleksi:
    """Memilih maksimal n klip terbaik yang tidak berbenturan, beserta catatan penolakan.

    `ditolak` berisi kandidat yang datanya tidak valid dan kandidat yang berbenturan dengan
    klip yang sudah terpilih. Kandidat yang tidak sempat diperiksa karena n sudah terpenuhi
    tidak dicatat. Hasil `terpilih` berurutan menurut waktu mulai.
    """
    n = _periksa_parameter(n, overlap_maks, jarak_min, aturan_jarak)
    try:
        daftar = list(scored)
    except TypeError:
        daftar = []

    ditolak: list = []
    layak: list = []                                   # (nomor, (mulai, akhir, skor))
    for i, kandidat in enumerate(daftar):
        data, alasan = _baca(kandidat)
        if alasan:
            ditolak.append((i, alasan))
        else:
            layak.append((i, data))

    # Skor tertinggi dulu; seri diputus mulai, akhir, lalu nomor masukan (deterministik)
    urutan = sorted(layak, key=lambda x: (-x[1][2], x[1][0], x[1][1], x[0]))
    terpilih: list = []
    for i, data in urutan:
        if len(terpilih) >= n:
            break
        alasan = None
        for _, lain in terpilih:
            alasan = _alasan_bentrok(data, lain, overlap_maks, jarak_min, aturan_jarak)
            if alasan:
                break
        if alasan:
            ditolak.append((i, alasan))
        else:
            terpilih.append((i, data))

    terpilih.sort(key=lambda x: (x[1][0], x[1][1], x[0]))     # urut waktu
    ditolak.sort(key=lambda x: x[0])
    return HasilSeleksi([daftar[i] for i, _ in terpilih], ditolak, [i for i, _ in terpilih])


def select_top_n(scored, n: int, *, overlap_maks: float = OVERLAP_MAKS,
                 jarak_min: float = JARAK_MIN, aturan_jarak: str = ATURAN_JARAK) -> list:
    """Hanya daftar klip terpilih (urut waktu). Lihat pilih_klip() untuk catatan penolakan."""
    return pilih_klip(scored, n, overlap_maks=overlap_maks, jarak_min=jarak_min,
                      aturan_jarak=aturan_jarak).terpilih


# ===========================================================================
# DEMO: python -m core.selection
# ===========================================================================
def _kand(mulai, akhir, skor) -> ScoredCandidate:
    """ScoredCandidate minimal untuk demo dan pengujian seleksi."""
    return ScoredCandidate(Candidate([Sentence([Word("x.", mulai, akhir)])]), 0.0, 0.0, 0.0, 0.0, skor)


def _demo() -> int:
    ok_semua = True
    data = [
        (12, 52, 91.0), (30, 70, 88.5), (48, 90, 84.0), (100, 135, 80.2), (120, 160, 79.0),
        (200, 240, 77.5), (215, 250, 74.0), (300, 340, 72.0), (330, 370, 70.0), (420, 460, 65.0),
    ]
    kandidat = [_kand(*d) for d in data]
    kandidat.insert(3, _kand(float("nan"), 50.0, 99.0))        # data rusak
    kandidat.insert(6, _kand(80.0, 80.0, 98.0))                 # durasi nol
    N = 4

    hasil = pilih_klip(kandidat, N)
    print(f"SIMULASI TOP-{N}: {len(kandidat)} kandidat, overlap maks {OVERLAP_MAKS:.0%}, "
          f"jarak min {JARAK_MIN:g} dtk (aturan: {ATURAN_JARAK})")
    print(f"  {'no':>3}{'mulai':>8}{'akhir':>8}{'skor':>8}   keputusan")
    pilih = set(hasil.indeks_terpilih)
    alasan = dict(hasil.ditolak)
    for i, k in enumerate(kandidat):
        if i in pilih:
            ket = "DIPILIH"
        elif i in alasan:
            ket = "ditolak: " + alasan[i]
        else:
            ket = f"tidak diperiksa (sudah {N} klip)"
        print(f"  {i:>3}{k.start:>8g}{k.end:>8g}{k.score:>8.1f}   {ket}")
    print("\n  Hasil urut waktu:", ", ".join(f"{k.start:g}-{k.end:g}" for k in hasil.terpilih))

    def cek(keterangan: str, kondisi: bool) -> None:
        nonlocal ok_semua
        ok_semua &= kondisi
        print(f"  {keterangan:<70} {'ya' if kondisi else 'TIDAK'}")

    print("\nRINGKASAN PEMERIKSAAN")
    mulai_terpilih = [k.start for k in hasil.terpilih]
    cek("1. Hasil tidak lebih dari N dan urut menurut waktu mulai",
        len(hasil.terpilih) <= N and mulai_terpilih == sorted(mulai_terpilih))
    cek("2. Kandidat skor tertinggi yang valid (91,0) terpilih",
        any(k.score == 91.0 for k in hasil.terpilih))
    cek("3. Kandidat overlap 55% (skor 88,5) ditolak", any("55%" in a for _, a in hasil.ditolak))
    cek("4. Data rusak (NaN, durasi nol) ditolak tanpa membuat program berhenti",
        sum(1 for _, a in hasil.ditolak if "timestamp" in a or "durasi" in a) == 2)
    cek("5. Overlap kecil 10% (48-90 terhadap 12-52) diterima", 48.0 in mulai_terpilih)
    ok_aturan = all(
        _alasan_bentrok((a.start, a.end, a.score), (b.start, b.end, b.score), OVERLAP_MAKS, JARAK_MIN, ATURAN_JARAK) is None
        for x, a in enumerate(hasil.terpilih) for b in hasil.terpilih[x + 1:])
    cek("6. Setiap pasangan terpilih memenuhi aturan overlap dan jarak", ok_aturan)
    cek("7. Hasil sama bila urutan masukan diacak",
        [(k.start, k.end) for k in select_top_n(list(reversed(kandidat)), N)]
        == [(k.start, k.end) for k in hasil.terpilih])
    return 0 if ok_semua else 1


if __name__ == "__main__":
    sys.exit(_demo())
