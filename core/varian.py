"""varian.py: pembentukan calon clip dengan BEBERAPA PANJANG per titik awal (perbaikan B, EKSPERIMENTAL).

Masalah yang diatasi (terukur pada tiga video uji): build_candidates hanya mengambil
`per_start` titik akhir pertama setelah batas bawah, jadi klip menumpuk di 20-35 dtk
dan versi 40-60 dtk dari gagasan yang sama tidak pernah menjadi calon.

Cara kerja mode ini:
  1. Untuk tiap kalimat awal, rentang [min_sec, max_sec] dibagi menjadi `jumlah_band`
     pita durasi yang sama lebar (mis. 20-30, 30-40, 40-50, 50-60 dtk).
  2. Di tiap pita dipilih SATU titik akhir kalimat dengan "kualitas batas" tertinggi
     (seri: yang lebih pendek). Hasilnya paling banyak `jumlah_band` calon per awal.
  3. Calon yang memuat jeda antar kalimat > jeda_maks_calon tidak dibuat (aturan A).
  4. Opsional `toleransi_sec`: titik akhir sampai max_sec + toleransi boleh dipakai
     HANYA bila kualitas batasnya >= q_toleransi, sebagai satu calon ekstra.

Kualitas batas (0..1) mengukur seberapa "tuntas" sebuah kalimat sebagai titik akhir.
Seluruh bobot, daftar kata, dan ambang di sini adalah HIPOTESIS yang belum diuji dan
tidak berasal dari literatur. Kualitas batas hanya memilih titik akhir; skor klip
(Hook, Flow, Value, Trend) dan seleksi TIDAK diubah.

Jeda dinilai RELATIF terhadap sebaran jeda video itu sendiri (peringkat persentil),
karena pada tiga video uji jeda yang sama bermakna berbeda (median jeda antar kalimat
0,28 / 0,90 / 0,34 dtk).

Cara mencoba: python -m core.pipeline kata.json --mode-calon varian
"""
from __future__ import annotations

from .models import Candidate, Sentence
from .segments import JEDA_MAKS_CALON_BAWAAN

# --- Parameter eksperimental --------------------------------------------------
JUMLAH_BAND_BAWAAN = 4
Q_TOLERANSI_BAWAAN = 0.8
BOBOT_BATAS = {"tanda": 0.35, "jeda": 0.35, "gantung": 0.15, "lanjut": 0.15}

# Tanda baca yang dianggap penutup tegas (elipsis tidak, sejalan dengan scoring Flow).
TANDA_TEGAS = (".", "?", "!")

# Kata yang bila berada di AKHIR kalimat menandakan kalimat menggantung (bahasa Indonesia).
KATA_GANTUNG = frozenset({
    "yang", "dan", "atau", "tapi", "tetapi", "karena", "dengan", "untuk", "dari", "ke", "di",
    "pada", "dalam", "bahwa", "sebagai", "seperti", "kalau", "jika", "ketika", "supaya", "agar",
    "sehingga", "jadi", "terus", "lalu",
})

# Kata yang bila MEMBUKA kalimat berikutnya menandakan gagasan sebelumnya masih berlanjut.
KATA_LANJUT = frozenset({
    "dan", "tapi", "tetapi", "karena", "makanya", "sehingga", "soalnya", "terus", "lalu",
    "kemudian", "jadi", "atau", "namun", "sedangkan", "padahal", "apalagi",
})


def _bersih(teks: str) -> str:
    return teks.strip().strip(".,!?…;:\"'()").lower()


def _persentil_tengah(nilai: float, semua: list[float]) -> float:
    """Peringkat persentil 0..1 (nilai seri dihitung setengah)."""
    if not semua:
        return 0.0
    kurang = sum(1 for x in semua if x < nilai)
    sama = sum(1 for x in semua if x == nilai)
    return (kurang + 0.5 * sama) / len(semua)


def kualitas_batas(kalimat: list[Sentence]) -> list[float]:
    """Kualitas tiap kalimat sebagai TITIK AKHIR calon (0..1, indeks sama dengan `kalimat`).

    Komponen (bobot di BOBOT_BATAS, semuanya hipotesis):
      tanda   : kalimat ditutup . ? !  (1,0) atau tidak (0,0)
      jeda    : peringkat persentil jeda sesudah kalimat di antara semua jeda antar kalimat
                video ini (kalimat terakhir video = 1,0)
      gantung : kalimat TIDAK berakhir pada kata penghubung menggantung (1,0) atau ya (0,0)
      lanjut  : kalimat berikutnya TIDAK dibuka kata penerus gagasan (1,0) atau ya (0,0)
    """
    n = len(kalimat)
    jeda = [max(0.0, kalimat[i + 1].start - kalimat[i].end) for i in range(n - 1)]
    hasil: list[float] = []
    for i, k in enumerate(kalimat):
        tanda = 1.0 if k.words[-1].text.rstrip().endswith(TANDA_TEGAS) else 0.0
        j = _persentil_tengah(jeda[i], jeda) if i < n - 1 else 1.0
        gantung = 0.0 if _bersih(k.words[-1].text) in KATA_GANTUNG else 1.0
        lanjut = 1.0
        if i < n - 1 and _bersih(kalimat[i + 1].words[0].text) in KATA_LANJUT:
            lanjut = 0.0
        q = (BOBOT_BATAS["tanda"] * tanda + BOBOT_BATAS["jeda"] * j
             + BOBOT_BATAS["gantung"] * gantung + BOBOT_BATAS["lanjut"] * lanjut)
        hasil.append(q)
    return hasil


def build_candidates_varian(
    sentences: list[Sentence],
    min_sec: float = 20,
    max_sec: float = 60,
    jumlah_band: int = JUMLAH_BAND_BAWAAN,
    jeda_maks_calon: float | None = JEDA_MAKS_CALON_BAWAAN,
    toleransi_sec: float = 0.0,
    q_toleransi: float = Q_TOLERANSI_BAWAAN,
) -> list[Candidate]:
    """Menyusun calon clip dengan beberapa panjang per titik awal. Lihat docstring modul."""
    if min_sec > max_sec:
        raise ValueError("min_sec tidak boleh lebih besar dari max_sec")
    if not isinstance(jumlah_band, int) or isinstance(jumlah_band, bool) or jumlah_band < 1:
        raise ValueError("jumlah_band harus bilangan bulat >= 1")
    if jeda_maks_calon is not None and jeda_maks_calon <= 0:
        raise ValueError("jeda_maks_calon harus > 0 atau None")
    if toleransi_sec < 0:
        raise ValueError("toleransi_sec tidak boleh negatif")
    if not (0.0 <= q_toleransi <= 1.0):
        raise ValueError("q_toleransi harus di antara 0 dan 1")

    n = len(sentences)
    q = kualitas_batas(sentences)
    lebar = (max_sec - min_sec) / jumlah_band
    batas_atas = max_sec + toleransi_sec

    hasil: list[Candidate] = []
    for awal in range(n):
        terbaik: dict[int, tuple[float, float, int]] = {}     # band -> (q, -durasi, indeks akhir)
        for akhir in range(awal, n):
            if (jeda_maks_calon is not None and akhir > awal
                    and sentences[akhir].start - sentences[akhir - 1].end > jeda_maks_calon):
                break
            durasi = sentences[akhir].end - sentences[awal].start
            if durasi > batas_atas:
                break
            if durasi < min_sec:
                continue
            if durasi <= max_sec:
                band = min(jumlah_band - 1, int((durasi - min_sec) / lebar)) if lebar > 0 else 0
            else:
                if q[akhir] < q_toleransi:
                    continue
                band = jumlah_band                            # pita ekstra di atas max_sec
            calon = (q[akhir], -durasi, akhir)
            if band not in terbaik or calon[:2] > terbaik[band][:2]:
                terbaik[band] = calon
        for _, _, akhir in sorted(terbaik.values(), key=lambda t: t[2]):
            hasil.append(Candidate(sentences[awal:akhir + 1]))
    return hasil
