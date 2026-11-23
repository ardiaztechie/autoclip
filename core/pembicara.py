"""pembicara.py: pelacakan banyak wajah, penyaring foto diam, pembicara aktif, dan lonjakan gerak.

Menggantikan pilihan "satu wajah terbesar" di face.py untuk video berbanyak orang (debat, podcast).
Hasil akhirnya tetap berupa core.face.Jalur, jadi render.py memakainya tanpa perubahan besar.

Cara kerja (seluruhnya offline: video dianalisis dulu, baru keputusan diambil dari seluruh rentang):
  1. Video dianalisis tiap LANGKAH_ANALISIS detik: deteksi wajah (YuNet), tiap wajah diberi
     nomor jalur yang sama antar sampel, lalu diukur dua gerak:
       - gerak_wajah : selisih piksel pada daerah wajah (di koordinat tetap) antar sampel
       - gerak_mulut : selisih piksel pada daerah mulut (relatif terhadap kotak wajah)
     serta gerak seluruh bingkai (untuk pergantian kamera dan lonjakan gerak).
  2. Jalur wajah yang gerak_wajah-nya hampir nol sepanjang waktu dianggap FOTO/poster dan
     tidak pernah dipilih sebagai pembicara.
  3. Pembicara = wajah hidup dengan gerak mulut terbesar, hanya saat transkrip menunjukkan ada
     ucapan. Pindah pembicara butuh unggul beruntun dan jeda minimum agar tidak berkedip.
  4. Pergantian kamera (perubahan besar seluruh bingkai) mengatur ulang pelacakan dan boleh
     langsung berpindah.
  5. Gerakan mendadak BERSKALA TUBUH (orang jatuh, bergeser tiba-tiba, menerjang ke depan) membuat
     tampilan melebar sementara: seluruh bingkai tampil utuh dengan latar buram. Gerak kecil seperti
     tangan atau badan sedikit bergeser saat duduk TIDAK memicu. Dua pemicu: (a) luas area yang berubah
     drastis di bingkai, (b) kecepatan perpindahan atau pembesaran wajah (lebar wajah per detik).
  6. Pergantian pembicara berupa POTONG LANGSUNG, bukan geseran.
  7. Jendela TENANG: selama wajah pembicara masih di dalam "zona nyaman" (ZONA_NYAMAN) di sekitar
     tengah jendela, jendela diam sama sekali. Jendela hanya bergeser pelan, dan hanya sejauh yang
     perlu, bila wajah keluar dari zona itu. Gerak kepala atau tangan yang kecil tidak menggoyang tampilan.

  8. Zoom in penekanan (potong langsung): selang dari core.penekanan diteruskan ke jalur. Zoom
     berpusat pada wajah pembicara, tidak dilakukan saat tampilan melebar, dan dipotong di batas
     pergantian kamera. Selang tanpa wajah di dalamnya dibuang.

Keterbatasan: dua orang berbicara bersamaan sulit dipisahkan (hanya gerak bibir yang dipakai);
kepala menoleh, tangan menutup mulut, atau resolusi rendah (mulut hanya beberapa piksel)
menurunkan ketepatan. Seluruh angka di bawah adalah nilai AWAL YANG BELUM DIUJI. Ketepatan
terhadap label manual diukur dengan opsi --label (lihat ketepatan()).

Cara pakai dari terminal:
    python -m core.pembicara video.mp4 --mulai 10 --akhir 70 --rasio 9:16 --kata kata.json --gambar-dir storage/uji/pb
"""
import argparse
import bisect
import json
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .penekanan import DURASI_SISA_MIN, FAKTOR_ZOOM
from .face import (NAPAS_MIN, AMBANG_YAKIN, LEBAR_DETEKSI_MAKS, TAHAN_TANPA_WAJAH, ALPHA_HALUS, RASIO_VALID,
                   Jalur, Kotak, jalur_model, ukuran_potong)

# --- Nilai awal (eksperimental) ---------------------------------------------
LANGKAH_ANALISIS = 0.1        # detik antar sampel (lebih rapat dari face.py karena gerak bibir cepat)
IOU_MIN = 0.3                 # kemiripan kotak minimum agar dianggap wajah yang sama
JARAK_PUSAT_MAKS = 0.6        # atau pusat bergeser kurang dari 0,6 x lebar kotak
MAKS_HILANG = 5               # sampel; jalur dibuang bila wajahnya hilang selama ini
UKURAN_PATCH = 24             # petak (piksel) untuk membandingkan wajah dan mulut
HALUS_KOTAK = 0.5             # penghalusan kotak wajah sebelum petak diambil (mengurangi getar deteksi)
AMBANG_FOTO = 0.3             # median gerak_wajah (skala 0-255) di bawah ini => foto diam (sampel awal; setel dari angka nyata)
MIN_OBSERVASI_FOTO = 10       # sampel; jalur lebih pendek dari ini tidak dinilai (dianggap hidup)
AMBANG_POTONG = 30.0          # selisih rata-rata bingkai kecil (0-255) di atas ini => pergantian kamera
JENDELA_SKOR = 5              # sampel; gerak mulut dirata-rata dengan tetangganya (berpusat)
AMBANG_MULUT_MIN = 0.5        # gerak mulut di bawah ini tidak dihitung sebagai "berbicara"
MARGIN_UNGGUL = 1.15          # pesaing harus 15% lebih besar dari pembicara saat ini
UNGGUL_MIN = 0.8              # detik beruntun pesaing harus unggul sebelum pindah
TAHAN_PEMBICARA_MIN = 1.5     # detik minimum antar perpindahan
JEDA_UCAPAN = 0.2             # detik; kata dianggap "sedang diucapkan" sedikit di luar waktunya
AMBANG_PIKSEL_GERAK = 25.0    # selisih kecerahan (0-255) yang dihitung sebagai "piksel bergerak"
LUAS_LONJAKAN_MIN = 0.12      # pemicu (a): minimal 12% bingkai bergerak drastis ...
RASIO_LONJAKAN = 4.0          # ... dan lebih dari 4x luas gerak biasa di sekitarnya
KECEPATAN_WAJAH_MIN = 2.5     # pemicu (b): wajah berpindah/membesar >= 2,5 lebar-wajah per detik
JARAK_WAKTU_KECEPATAN = 0.3   # detik; pengamatan wajah yang lebih jarang dari ini tidak dibandingkan
DURASI_LONJAKAN_MIN = 0.3     # detik beruntun agar dihitung lonjakan (membuang kesalahan satu sampel)
AWAL_LEBAR = 0.2              # detik; tampilan melebar mulai sedikit SEBELUM gerakan agar awalnya terlihat
TAHAN_LEBAR = 0.5             # detik tampilan lebar dipertahankan setelah gerakan reda
JENDELA_BASIS = 5.0           # detik; lebar jendela untuk median pembanding luas gerak
SELANG_LEBAR_MIN = 1.5        # detik; tampilan lebar yang terlalu singkat diperpanjang sampai sepanjang ini
ZONA_CAMPURAN = 0.10          # gaya campuran: zona nyaman lebih sempit agar bingkai lebih hidup (perkiraan, perlu dinilai di klip nyata)
ZONA_NYAMAN = 0.20            # wajah boleh bergeser sejauh 20% ukuran jendela dari tengahnya tanpa jendela bergerak
TANPA_WAJAH_MIN = 0.8        # detik tanpa wajah hidup (gaya campuran) => tampilan lebar, bukan potongan kosong
TARGET_LEBAR_WAJAH = 0.35    # gaya campuran: wajah diusahakan selebar 35% jendela (perkiraan dari klip referensi)
MAKS_ZOOM_DASAR = 1.8        # batas zoom dasar; lebih dari ini gambar sumber terlalu diperbesar (buram)
AMBANG_ZOOM_DASAR = 1.08     # zoom dasar di bawah ini dianggap 1,0 (hindari zoom kecil yang naik turun)
HALUS_ZOOM_DASAR = 0.15      # penghalusan zoom dasar per sampel
ALPHA_CAMPURAN = 0.25        # gaya campuran: jendela mengikuti wajah lebih pelan (dan terus-menerus) agar terasa halus
AMBANG_REAKSI = 3.0          # gerak wajah (0-255) minimal pada lawan bicara agar dihitung reaksi (perkiraan, perlu disetel)
RASIO_REAKSI = 3.0           # ... dan minimal sekian kali gerak wajah biasa orang itu
DURASI_REAKSI_MIN = 0.6      # detik beruntun gerak besar sebelum dianggap reaksi
DURASI_REAKSI = (1.0, 2.0)   # detik: lama cut ke lawan bicara (paling sedikit, paling lama)
SELANG_REAKSI_MIN = 8.0      # detik minimum antar cut reaksi
POTONGAN_DURASI = (3.0, 5.0)   # detik: lama satu ukuran gambar sebelum potongan langsung berikutnya (perkiraan dari video referensi)
POTONGAN_UKURAN = (1.0, 1.45, 1.2, 1.65, 1.0, 1.35)   # urutan faktor ukuran (1,0 = jendela biasa; makin besar makin dekat), berulang
POTONGAN_LEBAR_WAJAH_MAKS = 0.62   # wajah tidak boleh lebih lebar dari 62% jendela setelah diperbesar (agar tidak terpotong)
POTONGAN_BEDA_MIN = 0.15      # dua potongan berurutan harus beda ukuran sekian, kalau tidak potongannya tidak terasa
POTONGAN_SEGMEN_MIN = 1.5     # detik; ukuran terakhir sebelum pergantian pembicara/akhir klip tidak boleh lebih pendek dari ini
POTONGAN_JENDELA_JEDA = 1.0   # detik; potongan digeser ke jeda antar kata terdekat dalam jarak ini (hindari memotong di tengah kata)
POTONGAN_JEDA_MIN = 0.1       # detik; jeda antar kata sekecil ini dianggap tempat napas
TOLERANSI_LABEL = 0.12        # selisih posisi x (0-1) yang masih dianggap cocok dengan label


@dataclass(frozen=True)
class Pengamatan:
    id: int
    kotak: Kotak                 # koordinat piksel bingkai asli
    gerak_mulut: object = None   # float, atau None bila belum ada pembanding
    gerak_wajah: object = None


@dataclass(frozen=True)
class Sampel:
    t: float
    wajah: tuple = ()
    potong: bool = False         # pergantian kamera tepat pada sampel ini
    luas_gerak: float = 0.0      # 0-1: porsi bingkai yang berubah drastis dibanding sampel sebelumnya


@dataclass
class Laporan:
    foto: dict = field(default_factory=dict)         # id jalur -> posisi x rata-rata (0-1)
    median_gerak: dict = field(default_factory=dict)  # id jalur -> median gerak_wajah
    pergantian: list = field(default_factory=list)   # [(waktu, id, posisi_x)]
    potongan: list = field(default_factory=list)     # [waktu]
    lonjakan: list = field(default_factory=list)     # [(awal, akhir)]
    pembicara_x: list = field(default_factory=list)  # [(waktu, posisi_x atau None)] metode baru
    terbesar_x: list = field(default_factory=list)   # [(waktu, posisi_x atau None)] metode lama (terbesar)
    statistik_gerak: dict = field(default_factory=dict)  # bahan menyetel ambang lonjakan


# ===========================================================================
# PELACAK IDENTITAS WAJAH
# ===========================================================================
def _iou(a: Kotak, b: Kotak) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    irisan = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    gabungan = a.luas + b.luas - irisan
    return irisan / gabungan if gabungan > 0 else 0.0


def _kemiripan(a: Kotak, b: Kotak) -> float:
    iou = _iou(a, b)
    if iou >= IOU_MIN:
        return iou
    d = math.hypot(a.pusat[0] - b.pusat[0], a.pusat[1] - b.pusat[1])
    batas = JARAK_PUSAT_MAKS * max(a.w, b.w)
    return 0.05 * (1 - d / batas) if batas > 0 and d < batas else 0.0


class PelacakWajah:
    """Memberi nomor tetap pada wajah yang sama dari sampel ke sampel (pencocokan serakah)."""

    def __init__(self, maks_hilang: int = MAKS_HILANG):
        self.maks_hilang = maks_hilang
        self._jalur: dict = {}
        self._terakhir = 0

    def reset(self):
        self._jalur.clear()

    def perbarui(self, kotak_list) -> list:
        pasangan = []
        for i, k in enumerate(kotak_list):
            for id_, j in self._jalur.items():
                s = _kemiripan(k, j["kotak"])
                if s > 0:
                    pasangan.append((s, i, id_))
        pasangan.sort(key=lambda p: (-p[0], p[1], p[2]))
        hasil, dipakai = [None] * len(kotak_list), set()
        for _, i, id_ in pasangan:
            if hasil[i] is None and id_ not in dipakai:
                hasil[i] = id_
                dipakai.add(id_)
        for i in range(len(kotak_list)):
            if hasil[i] is None:
                self._terakhir += 1
                hasil[i] = self._terakhir
        for i, k in enumerate(kotak_list):
            self._jalur[hasil[i]] = {"kotak": k, "hilang": 0}
        for id_ in list(self._jalur):
            if id_ not in hasil:
                self._jalur[id_]["hilang"] += 1
                if self._jalur[id_]["hilang"] > self.maks_hilang:
                    del self._jalur[id_]
        return hasil


# ===========================================================================
# LOGIKA KEPUTUSAN (murni, tanpa video)
# ===========================================================================
def _banyak(detik: float, langkah: float) -> int:
    return max(1, int(round(detik / langkah)))


def _median(nilai):
    n = sorted(nilai)
    if not n:
        return 0.0
    m = len(n) // 2
    return n[m] if len(n) % 2 else (n[m - 1] + n[m]) / 2


def ada_ucapan(kata, jeda: float = JEDA_UCAPAN):
    """Fungsi t -> bool. kata=None berarti ucapan dianggap selalu ada (tanpa gerbang)."""
    if kata is None:
        return lambda t: True
    selang = sorted((k.start - jeda, k.end + jeda) for k in kata
                    if isinstance(getattr(k, "start", None), (int, float)) and
                    isinstance(getattr(k, "end", None), (int, float)) and k.end >= k.start)
    gabung = []
    for a, b in selang:
        if gabung and a <= gabung[-1][1]:
            gabung[-1][1] = max(gabung[-1][1], b)
        else:
            gabung.append([a, b])
    awal = [g[0] for g in gabung]

    def _ada(t):
        i = bisect.bisect_right(awal, t) - 1
        return i >= 0 and t <= gabung[i][1]
    return _ada


def klasifikasi_foto(sampel, ambang: float = AMBANG_FOTO, min_obs: int = MIN_OBSERVASI_FOTO):
    """Mengembalikan (himpunan id foto, {id: median gerak_wajah}) dari seluruh sampel."""
    gerak: dict = {}
    for s in sampel:
        for p in s.wajah:
            if p.gerak_wajah is not None:
                gerak.setdefault(p.id, []).append(p.gerak_wajah)
    med = {i: _median(v) for i, v in gerak.items() if len(v) >= min_obs}
    return {i for i, m in med.items() if m < ambang}, med


def _skor_mulut(sampel, jendela: int = JENDELA_SKOR) -> list:
    """Per sampel: {id: rata-rata gerak_mulut di sekitar sampel itu}."""
    per_id: dict = {}
    for i, s in enumerate(sampel):
        for p in s.wajah:
            if p.gerak_mulut is not None:
                per_id.setdefault(p.id, {})[i] = p.gerak_mulut
    sisi = jendela // 2
    hasil = []
    for i, s in enumerate(sampel):
        d = {}
        for p in s.wajah:
            nilai = [per_id.get(p.id, {}).get(j) for j in range(i - sisi, i + sisi + 1)]
            nilai = [x for x in nilai if x is not None]
            if nilai:
                d[p.id] = sum(nilai) / len(nilai)
        hasil.append(d)
    return hasil


def pilih_pembicara(sampel, foto, ucapan=None, *, langkah: float = LANGKAH_ANALISIS) -> list:
    """Id pembicara (atau None) untuk tiap sampel. Foto tidak pernah dipilih."""
    ucapan = ucapan or (lambda t: True)
    skor = _skor_mulut(sampel)
    unggul_min = _banyak(UNGGUL_MIN, langkah)
    tahan_min = _banyak(TAHAN_PEMBICARA_MIN, langkah)
    hasil = [None] * len(sampel)
    saat_ini, kandidat, hitung, terakhir_pindah, hilang = None, None, 0, -10 ** 9, 0
    awal_adegan = 0
    for i, s in enumerate(sampel):
        if s.potong:
            _isi_awal(hasil, awal_adegan, i)
            awal_adegan = i
            saat_ini, kandidat, hitung, terakhir_pindah, hilang = None, None, 0, -10 ** 9, 0
        hidup = {p.id for p in s.wajah if p.id not in foto}
        if saat_ini is not None:
            hilang = 0 if saat_ini in hidup else hilang + 1
            if hilang > MAKS_HILANG:
                saat_ini, kandidat, hitung = None, None, 0
        sk = {k: v for k, v in skor[i].items() if k in hidup}
        if sk and ucapan(s.t):
            terbaik = max(sk, key=lambda k: (sk[k], -k))
            if sk[terbaik] >= AMBANG_MULUT_MIN:
                if saat_ini is None:
                    saat_ini, terakhir_pindah, kandidat, hitung = terbaik, i, None, 0
                elif terbaik != saat_ini:
                    if sk[terbaik] >= MARGIN_UNGGUL * sk.get(saat_ini, 0.0):
                        hitung = hitung + 1 if kandidat == terbaik else 1
                        kandidat = terbaik
                        if hitung >= unggul_min and i - terakhir_pindah >= tahan_min:
                            # analisis offline: pindah dimundurkan ke awal masa unggul (tanpa jeda tunggu)
                            for j in range(i - hitung + 1, i):
                                hasil[j] = terbaik
                            saat_ini, terakhir_pindah, kandidat, hitung = terbaik, i - hitung + 1, None, 0
                    else:
                        kandidat, hitung = None, 0
                else:
                    kandidat, hitung = None, 0
        hasil[i] = saat_ini
    _isi_awal(hasil, awal_adegan, len(sampel))
    return hasil


def tambah_reaksi(sampel, pembicara, foto, *, langkah: float = LANGKAH_ANALISIS, ambang: float = AMBANG_REAKSI,
                  rasio: float = RASIO_REAKSI) -> list:
    """Cut singkat ke lawan bicara yang tiba-tiba bergerak/berekspresi (tertawa, kaget), lalu kembali.

    Lawan bicara = wajah hidup yang bukan pembicara dan bukan foto. Syarat: gerak wajahnya >= `ambang` dan
    >= `rasio` x gerak biasanya, beruntun >= DURASI_REAKSI_MIN. Cut berlangsung DURASI_REAKSI (1-2 dtk),
    tidak melewati pergantian kamera, dan ada jarak SELANG_REAKSI_MIN antar cut. Hanya perkiraan dari gerak
    wajah: gerakan menoleh bisa ikut terbaca, jadi batasnya sengaja ketat.
    """
    n = len(sampel)
    hasil = list(pembicara)
    nilai: dict = {}
    for s in sampel:
        for p in s.wajah:
            if p.gerak_wajah is not None:
                nilai.setdefault(p.id, []).append(p.gerak_wajah)
    biasa = {i: _median(v) for i, v in nilai.items()}
    if n == 0:
        return hasil
    minimal = _banyak(DURASI_REAKSI_MIN, langkah)
    pendek, panjang = _banyak(DURASI_REAKSI[0], langkah), _banyak(DURASI_REAKSI[1], langkah)
    jarak = _banyak(SELANG_REAKSI_MIN, langkah)
    kandidat = []                                                      # (awal, akhir_run, id)
    ids = {p.id for s in sampel for p in s.wajah if p.id not in foto}
    for id_ in ids:
        mulai = None
        for i in range(n + 1):
            ya = False
            if i < n:
                for p in sampel[i].wajah:
                    if (p.id == id_ and p.gerak_wajah is not None and pembicara[i] not in (None, id_)
                            and p.gerak_wajah >= max(ambang, rasio * biasa.get(id_, 0.0))):
                        ya = True
            if ya and mulai is None:
                mulai = i
            elif not ya and mulai is not None:
                if i - mulai >= minimal:
                    kandidat.append((mulai, i, id_))
                mulai = None
    terakhir = -10 ** 9
    for awal, akhir_run, id_ in sorted(kandidat):
        if awal - terakhir < jarak:
            continue
        akhir = min(max(akhir_run + _banyak(0.4, langkah), awal + pendek), awal + panjang, n)
        if any(sampel[k].potong for k in range(awal + 1, akhir)):
            akhir = next(k for k in range(awal + 1, akhir) if sampel[k].potong)
            if akhir - awal < pendek:
                continue
        if any(hasil[k] != pembicara[k] for k in range(awal, akhir)):
            continue
        if any(id_ not in {p.id for p in sampel[k].wajah} for k in range(awal, akhir)):
            continue
        for k in range(awal, akhir):
            hasil[k] = id_
        terakhir = akhir
    return hasil


def _isi_awal(hasil, awal, akhir):
    """Dalam satu adegan, sampel awal yang belum punya pembicara diisi pembicara pertama adegan itu."""
    pertama = next((hasil[i] for i in range(awal, akhir) if hasil[i] is not None), None)
    if pertama is None:
        return
    for i in range(awal, akhir):
        if hasil[i] is not None:
            break
        hasil[i] = pertama


def kecepatan_wajah(sampel, foto=frozenset()) -> list:
    """Per sampel: kecepatan wajah tercepat (lebar-wajah per detik), dari perpindahan pusat atau
    perubahan lebar kotak dibanding pengamatan sebelumnya pada jalur yang sama. Foto diabaikan."""
    terakhir: dict = {}
    hasil = []
    for s in sampel:
        if s.potong:
            terakhir.clear()
        tertinggi = 0.0
        for p in s.wajah:
            if p.id in foto:
                continue
            lalu = terakhir.get(p.id)
            if lalu is not None:
                dt = s.t - lalu[0]
                if 0 < dt <= JARAK_WAKTU_KECEPATAN:
                    w = (lalu[1].w + p.kotak.w) / 2
                    if w > 0:
                        geser = math.hypot(p.kotak.pusat[0] - lalu[1].pusat[0],
                                           p.kotak.pusat[1] - lalu[1].pusat[1]) / w / dt
                        ubah = abs(p.kotak.w - lalu[1].w) / w / dt
                        tertinggi = max(tertinggi, geser, ubah)
            terakhir[p.id] = (s.t, p.kotak)
        hasil.append(tertinggi)
    return hasil


def deteksi_lonjakan(sampel, foto=frozenset(), *, langkah: float = LANGKAH_ANALISIS) -> list:
    """Selang waktu [(awal, akhir)] untuk gerakan mendadak berskala tubuh.

    Sampel ditandai bila (a) luas gerak >= LUAS_LONJAKAN_MIN dan > RASIO_LONJAKAN x luas biasa di
    sekitarnya, ATAU (b) kecepatan wajah >= KECEPATAN_WAJAH_MIN. Tanda harus beruntun minimal
    DURASI_LONJAKAN_MIN. Selang dimulai AWAL_LEBAR sebelum gerakan, ditahan TAHAN_LEBAR sesudahnya,
    dan diperpanjang sampai SELANG_LEBAR_MIN bila terlalu singkat.
    """
    n = len(sampel)
    if n == 0:
        return []
    luas = [s.luas_gerak for s in sampel]
    cepat = kecepatan_wajah(sampel, foto)
    sisi = _banyak(JENDELA_BASIS, langkah) // 2
    median_luas = _median(luas)
    tanda = []
    for i in range(n):
        if sampel[i].potong:
            tanda.append(False)
            continue
        basis = _median(luas[max(0, i - sisi): i + sisi + 1]) or median_luas
        a = luas[i] >= LUAS_LONJAKAN_MIN and luas[i] > RASIO_LONJAKAN * basis
        b = cepat[i] >= KECEPATAN_WAJAH_MIN
        tanda.append(a or b)
    selang, mulai = [], None
    for i, t in enumerate(tanda + [False]):
        if t and mulai is None:
            mulai = i
        elif not t and mulai is not None:
            if (i - mulai) * langkah >= DURASI_LONJAKAN_MIN - 1e-9:
                awal = max(0.0, sampel[mulai].t - AWAL_LEBAR)
                akhir = sampel[i - 1].t + TAHAN_LEBAR
                selang.append((awal, max(akhir, awal + SELANG_LEBAR_MIN)))
            mulai = None
    gabung = []
    for a, b in selang:
        if gabung and a <= gabung[-1][1]:
            gabung[-1] = (gabung[-1][0], max(gabung[-1][1], b))
        else:
            gabung.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in gabung]


def susun_jalur(sampel, pembicara, foto, lebar: int, tinggi: int, rasio: str = "9:16", *,
                selang_lebar=(), selang_zoom=(), faktor_zoom: float = FAKTOR_ZOOM,
                alpha: float = ALPHA_HALUS, zona_mati: float = ZONA_NYAMAN, tahan: float = TAHAN_TANPA_WAJAH,
                gaya: str = "lama", napas: bool = True, zoom_dasar: bool = False,
                potongan: bool = False, waktu_jeda=()):
    """Jalur jendela potong dari keputusan pembicara. Mengembalikan (Jalur, sasaran_x per sampel).

    potongan (gaya campuran): ukuran gambar berganti dengan potongan langsung tiap 3-5 detik (lihat susun_potongan);
    zoom penekanan dan zoom napas dimatikan agar tidak menumpuk dengan ukuran potongan.

    Pergantian pembicara atau kamera = LONCAT (dua titik berdekatan), bukan geseran.
    """
    wp, hp = ukuran_potong(lebar, tinggi, rasio)
    pusat_bingkai = (lebar / 2, tinggi / 2)
    cx, cy = pusat_bingkai
    titik, sasaran_x, ada = [], [], 0
    titik_zoom, ada_wajah, zx, zy = [], [], pusat_bingkai[0], pusat_bingkai[1]
    titik_mata, my, waktu_lompat, mata_lalu = [], None, [], None
    titik_dasar, dasar, lebar_wajah = [], 1.0, []
    terakhir_sasaran, t_terakhir, spk_lalu = None, None, None
    for s, spk in zip(sampel, pembicara):
        hidup = [p for p in s.wajah if p.id not in foto]
        sasaran, orang = None, None
        if spk is not None:
            orang = next((p for p in hidup if p.id == spk), None)
        elif hidup:
            orang = max(hidup, key=lambda p: p.kotak.luas)
        if orang is not None:
            sasaran = orang.kotak.pusat
            mata_lalu = orang.kotak.mata_y if orang.kotak.mata_y is not None else None
        if sasaran is not None:
            ada += 1
            terakhir_sasaran, t_terakhir = sasaran, s.t
        elif terakhir_sasaran is not None and s.t - t_terakhir <= tahan and not s.potong:
            sasaran = terakhir_sasaran
        else:
            sasaran = pusat_bingkai
        lompat = s.potong or (spk != spk_lalu and spk is not None and spk_lalu is not None) or not titik
        spk_lalu = spk if spk is not None else spk_lalu
        ada_wajah.append(bool(hidup) and sasaran is not pusat_bingkai)
        lebar_wajah.append(orang.kotak.w if orang is not None else None)
        if lompat and titik:
            waktu_lompat.append(s.t)
        if mata_lalu is not None and sasaran is not pusat_bingkai:
            my = mata_lalu if (lompat or my is None) else my + 0.4 * (mata_lalu - my)
            titik_mata.append((round(float(s.t), 3), round(my, 2)))
        if zoom_dasar and orang is not None:
            ideal = TARGET_LEBAR_WAJAH * wp / orang.kotak.w if orang.kotak.w > 0 else 1.0
            ideal = min(max(ideal, 1.0), MAKS_ZOOM_DASAR)
            ideal = 1.0 if ideal < AMBANG_ZOOM_DASAR else ideal
            dasar = ideal if (lompat or not titik_dasar) else dasar + HALUS_ZOOM_DASAR * (ideal - dasar)
        titik_dasar.append((round(float(s.t), 3), round(dasar, 3)))
        if lompat:
            zx, zy = sasaran
        else:
            zx, zy = zx + 0.4 * (sasaran[0] - zx), zy + 0.4 * (sasaran[1] - zy)
        titik_zoom.append((round(float(s.t), 3), round(zx, 2), round(zy, 2)))
        if lompat:
            if titik:
                titik.append((round(s.t - 0.001, 3), titik[-1][1], titik[-1][2]))
            cx, cy = sasaran
        else:
            # Zona nyaman: hanya selisih di LUAR zona yang dikejar, jadi jendela tidak bergerak untuk
            # gerak kecil dan tidak meloncat saat wajah akhirnya keluar zona.
            dx, dy = sasaran[0] - cx, sasaran[1] - cy
            zona_x, zona_y = zona_mati * wp, zona_mati * hp
            if abs(dx) > zona_x:
                cx += alpha * (dx - math.copysign(zona_x, dx))
            if abs(dy) > zona_y:
                cy += alpha * (dy - math.copysign(zona_y, dy))
        x = min(max(cx - wp / 2, 0.0), lebar - wp)
        y = min(max(cy - hp / 2, 0.0), tinggi - hp)
        titik.append((round(float(s.t), 3), round(x, 2), round(y, 2)))
        sasaran_x.append(sasaran[0] / lebar)
    persen = ada / len(sampel) if sampel else 0.0
    lebar_penuh = (wp, hp) == (lebar, tinggi)
    selang_lebar = () if lebar_penuh else tuple(selang_lebar)
    campuran = gaya == "campuran"
    if campuran and not lebar_penuh and sampel:        # tidak ada wajah: tampilkan seluruh bingkai, jangan tembok kosong
        langkah = (sampel[1].t - sampel[0].t) if len(sampel) > 1 else LANGKAH_ANALISIS
        kosong = selang_tanpa_wajah([s.t for s in sampel], ada_wajah, langkah)
        selang_lebar = _gabung_selang(tuple(selang_lebar) + tuple(kosong))
    zoom = ()
    pakai_potongan = bool(potongan) and campuran and not lebar_penuh and bool(sampel)
    if pakai_potongan:
        jadwal = susun_potongan([s.t for s in sampel], lebar_wajah, waktu_lompat + [s.t for s in sampel if s.potong],
                                waktu_jeda, wp, awal_acak=int(round(sampel[0].t * 1000)))
        titik_dasar = list(titik_dari_potongan(jadwal)) if any(f > 1.0005 for _, f in jadwal) else []
    if faktor_zoom and faktor_zoom > 1.0 and selang_zoom and not pakai_potongan:
        zoom = saring_zoom(selang_zoom, selang_lebar, [s.t for s in sampel if s.potong],
                           [s.t for s in sampel], ada_wajah)
    selang_napas = ()
    if campuran and napas and sampel and not lebar_penuh and not pakai_potongan:
        selang_napas = susun_napas(sampel[0].t, sampel[-1].t, tuple(selang_lebar) + zoom,
                                   [s.t for s in sampel if s.potong] + waktu_lompat,
                                   [s.t for s in sampel], ada_wajah)
    dasar_aktif = campuran and any(f > 1.0005 for _, f in titik_dasar)
    perlu_pusat = bool(zoom) or bool(selang_napas) or dasar_aktif
    return (Jalur(titik, wp, hp, lebar, tinggi, rasio, persen, selang_lebar, zoom,
                  float(faktor_zoom) if zoom else 1.0, tuple(titik_zoom) if perlu_pusat else (),
                  "campuran" if campuran else "lama", selang_napas,
                  tuple(titik_mata) if campuran and perlu_pusat else (),
                  tuple(titik_dasar) if dasar_aktif else ()), sasaran_x)


def selang_tanpa_wajah(waktu_sampel, ada_wajah, langkah: float = LANGKAH_ANALISIS,
                       minimal: float = TANPA_WAJAH_MIN) -> list:
    """Selang [(awal, akhir)] tempat tidak ada wajah hidup selama paling sedikit `minimal` detik.
    Selang dimulai di sampel pertama tanpa wajah (analisis offline, jadi boleh mundur)."""
    hasil, mulai = [], None
    n = len(waktu_sampel)
    for i in range(n + 1):
        kosong = i < n and not ada_wajah[i]
        if kosong and mulai is None:
            mulai = i
        elif not kosong and mulai is not None:
            akhir = waktu_sampel[i] if i < n else waktu_sampel[-1] + langkah
            if akhir - waktu_sampel[mulai] >= minimal - 1e-9:
                hasil.append((float(waktu_sampel[mulai]), float(akhir)))
            mulai = None
    return hasil


def _gabung_selang(selang) -> tuple:
    gabung = []
    for a, b in sorted((float(a), float(b)) for a, b in selang):
        if gabung and a <= gabung[-1][1]:
            gabung[-1] = (gabung[-1][0], max(gabung[-1][1], b))
        else:
            gabung.append((a, b))
    return tuple((round(a, 3), round(b, 3)) for a, b in gabung)


def titik_jeda(kata, mulai: float, akhir: float, jeda_min: float = POTONGAN_JEDA_MIN) -> list:
    """Waktu tengah jeda antar kata (>= jeda_min) di dalam [mulai, akhir]; tempat yang aman untuk potongan gambar."""
    urut = sorted((k for k in (kata or []) if k.end >= mulai and k.start <= akhir), key=lambda k: k.start)
    return [round((a.end + b.start) / 2, 3) for a, b in zip(urut, urut[1:]) if b.start - a.end >= jeda_min - 1e-9]


def susun_potongan(waktu_sampel, lebar_wajah, waktu_ganti, waktu_jeda, wp: float, *, durasi=POTONGAN_DURASI,
                   ukuran=POTONGAN_UKURAN, awal_acak: int = 0) -> list:
    """Jadwal ukuran gambar bergaya potong-langsung: [(waktu mulai, faktor)], faktor 1,0 = jendela biasa.

    Tiap 3-5 detik ukuran berganti dengan potongan langsung; pergantian pembicara/kamera (waktu_ganti) selalu
    jadi potongan; potongan digeser ke jeda antar kata terdekat. Faktor dibatasi agar wajah pembicara tidak lebih
    lebar dari POTONGAN_LEBAR_WAJAH_MAKS jendela, dan dua ukuran berurutan beda paling sedikit POTONGAN_BEDA_MIN.
    Acak diatur oleh awal_acak, jadi render ulang klip yang sama menghasilkan potongan yang sama."""
    if not waktu_sampel:
        return []
    rng = random.Random(awal_acak)
    mulai, akhir = float(waktu_sampel[0]), float(waktu_sampel[-1])
    batas = [mulai] + sorted(t for t in waktu_ganti if mulai + 0.5 < t < akhir - 0.5) + [akhir]
    potong = [mulai]
    for a, b in zip(batas, batas[1:]):                      # jadwal di dalam tiap bagian di antara pergantian alami
        if a != mulai:
            potong.append(a)
        kursor = a
        for _ in range(100):
            target = kursor + rng.uniform(*durasi)
            if target > b - POTONGAN_SEGMEN_MIN:
                break
            dekat = [j for j in waktu_jeda if abs(j - target) <= POTONGAN_JENDELA_JEDA and kursor + 1.0 < j < b - POTONGAN_SEGMEN_MIN]
            if waktu_jeda and dekat:
                target = min(dekat, key=lambda j: abs(j - target))
            elif waktu_jeda:                                # tidak ada jeda dekat: perpanjang ukuran ini sedikit
                kursor += 0.5
                continue
            potong.append(round(target, 3))
            kursor = target
    potong = sorted(set(round(t, 3) for t in potong))
    hasil, lalu, urut = [], None, 0
    for i, t0 in enumerate(potong):
        t1 = potong[i + 1] if i + 1 < len(potong) else akhir + 1e-9
        lebar = sorted(w for t, w in zip(waktu_sampel, lebar_wajah) if w and t0 - 1e-9 <= t <= t1)
        batas_wajah = POTONGAN_LEBAR_WAJAH_MAKS * wp / lebar[len(lebar) // 2] if lebar else MAKS_ZOOM_DASAR
        pilihan = None
        for k in range(len(ukuran)):                         # ukuran berikutnya dalam pola yang cukup beda dari yang lalu
            kandidat = min(ukuran[(urut + k) % len(ukuran)], batas_wajah, MAKS_ZOOM_DASAR)
            kandidat = 1.0 if kandidat < AMBANG_ZOOM_DASAR else kandidat
            if lalu is None or abs(kandidat - lalu) >= POTONGAN_BEDA_MIN:
                pilihan = kandidat
                urut += k + 1
                break
        if pilihan is None:                                  # semua terlalu mirip (wajah besar): ganti ke 1,0 / ukuran maksimum
            pilihan = 1.0 if lalu is not None and lalu > 1.0 else min(batas_wajah, MAKS_ZOOM_DASAR)
            pilihan = 1.0 if pilihan < AMBANG_ZOOM_DASAR else pilihan
            urut += 1
        hasil.append((t0, round(pilihan, 3)))
        lalu = pilihan
    return hasil


def titik_dari_potongan(potongan) -> tuple:
    """Jadwal [(waktu, faktor)] menjadi titik zoom dasar bertangga: tiap pergantian = dua titik berselisih 1 ms (potongan langsung)."""
    titik = []
    for i, (t, f) in enumerate(potongan):
        if i:
            titik.append((round(t - 0.001, 3), potongan[i - 1][1]))
        titik.append((round(t, 3), f))
    return tuple(titik)


def susun_napas(awal: float, akhir: float, terpakai, waktu_potong, waktu_sampel, ada_wajah) -> tuple:
    """Bagian tenang (di luar tampilan lebar dan zoom penekanan, tanpa pergantian kamera/pembicara di
    tengahnya) yang cukup panjang diberi zoom pelan. Arah bergantian: mendekat, menjauh, mendekat, ..."""
    bagian = saring_zoom([(awal, akhir)], terpakai, waktu_potong, waktu_sampel, ada_wajah)
    panjang = [(a, b) for a, b in bagian if b - a >= NAPAS_MIN - 1e-9]
    return tuple((a, b, 1 if i % 2 == 0 else -1) for i, (a, b) in enumerate(panjang))


def saring_zoom(selang_zoom, selang_lebar, waktu_potong, waktu_sampel, ada_wajah) -> tuple:
    """Merapikan selang zoom: buang bagian yang tumpang tindih tampilan lebar, pisahkan di pergantian
    kamera, dan buang potongan yang tidak punya wajah (paling sedikit setengah sampelnya) atau terlalu pendek."""
    bagian = [(float(a), float(b)) for a, b in selang_zoom if b > a]
    for c, d in selang_lebar:                                        # kurangi tampilan lebar
        baru = []
        for a, b in bagian:
            if b <= c or a >= d:
                baru.append((a, b))
                continue
            if a < c:
                baru.append((a, c))
            if b > d:
                baru.append((d, b))
        bagian = baru
    for tc in sorted(waktu_potong):                                  # pisahkan di pergantian kamera
        baru = []
        for a, b in bagian:
            if a < tc < b:
                baru += [(a, tc - 0.001), (tc, b)]
            else:
                baru.append((a, b))
        bagian = baru
    hasil = []
    for a, b in bagian:
        if b - a < DURASI_SISA_MIN - 1e-9:
            continue
        di_dalam = [ok for t, ok in zip(waktu_sampel, ada_wajah) if a - 1e-9 <= t <= b + 1e-9]
        if di_dalam and sum(di_dalam) / len(di_dalam) >= 0.5:
            hasil.append((round(a, 3), round(b, 3)))
    return tuple(hasil)


def ketepatan(garis_waktu, label, toleransi: float = TOLERANSI_LABEL) -> dict:
    """Ketepatan terhadap label manual.

    garis_waktu: [(waktu, posisi_x atau None)]. label: [{"mulai","akhir","x"}] dengan x = posisi tengah
    wajah pembicara sebagai pecahan lebar bingkai (0 kiri, 1 kanan). Cocok bila |x - label| <= toleransi.
    Posisi None dihitung salah.
    """
    if not isinstance(label, list):
        raise ValueError("label harus berupa daftar")
    total = cocok = 0
    for item in label:
        if not isinstance(item, dict) or not {"mulai", "akhir", "x"} <= item.keys():
            raise ValueError("tiap label harus punya mulai, akhir, x")
        for t, x in garis_waktu:
            if item["mulai"] <= t <= item["akhir"]:
                total += 1
                if x is not None and abs(x - item["x"]) <= toleransi:
                    cocok += 1
    return {"sampel": total, "cocok": cocok, "persen": (cocok / total) if total else 0.0}


# ===========================================================================
# ANALISIS VIDEO (butuh OpenCV, numpy, dan model YuNet)
# ===========================================================================
def _petak(gray, k: Kotak, bagian: str):
    import cv2
    h_img, w_img = gray.shape[:2]
    if bagian == "mulut":
        x, y, w, h = k.x + 0.2 * k.w, k.y + 0.6 * k.h, 0.6 * k.w, 0.4 * k.h
        ukuran = (UKURAN_PATCH, UKURAN_PATCH // 2)
    else:
        x, y, w, h = k.x, k.y, k.w, k.h
        ukuran = (UKURAN_PATCH, UKURAN_PATCH)
    x0, y0 = int(round(max(0.0, x))), int(round(max(0.0, y)))
    x1, y1 = int(round(min(float(w_img), x + w))), int(round(min(float(h_img), y + h)))
    if x1 - x0 < 4 or y1 - y0 < 2:
        return None
    return cv2.resize(gray[y0:y1, x0:x1], ukuran, interpolation=cv2.INTER_AREA).astype("float32")


def _halus(lama: Kotak, baru: Kotak, a: float = HALUS_KOTAK) -> Kotak:
    mata = baru.mata_y if lama.mata_y is None or baru.mata_y is None else lama.mata_y + a * (baru.mata_y - lama.mata_y)
    return Kotak(lama.x + a * (baru.x - lama.x), lama.y + a * (baru.y - lama.y),
                 lama.w + a * (baru.w - lama.w), lama.h + a * (baru.h - lama.h), baru.skor, mata)


def analisis_video(path_video, mulai: float, akhir: float, *, langkah: float = LANGKAH_ANALISIS,
                   path_model=None, ambang: float = AMBANG_YAKIN, pada_kemajuan=None):
    """Mengembalikan (daftar Sampel, lebar, tinggi, fps). pada_kemajuan(bagian 0..1) dipanggil tiap sampel (opsional)."""
    if not (math.isfinite(mulai) and math.isfinite(akhir)) or mulai < 0 or akhir <= mulai:
        raise ValueError("mulai harus >= 0 dan akhir harus lebih besar dari mulai")
    if not math.isfinite(langkah) or langkah <= 0:
        raise ValueError("langkah harus positif")
    jalur = Path(path_video)
    if not jalur.is_file():
        raise FileNotFoundError(f"Berkas tidak ditemukan: {jalur}")
    model = Path(path_model) if path_model else jalur_model()
    if not model.is_file():
        raise FileNotFoundError(f"Model YuNet tidak ditemukan: {model} (lihat petunjuk unduh di core/face.py)")
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise RuntimeError("opencv/numpy belum terpasang. Jalankan: pip install -r requirements.txt") from None

    cap = cv2.VideoCapture(str(jalur))
    try:
        if not cap.isOpened():
            raise ValueError(f"video tidak dapat dibuka: {jalur}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        lebar, tinggi = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not (fps and math.isfinite(fps) and fps > 0) or lebar <= 0 or tinggi <= 0:
            raise ValueError("fps atau ukuran video tidak terbaca")
        skala = min(1.0, LEBAR_DETEKSI_MAKS / lebar)
        dw, dh = max(1, int(round(lebar * skala))), max(1, int(round(tinggi * skala)))
        detektor = cv2.FaceDetectorYN.create(str(model), "", (dw, dh), ambang, 0.3, 5000)
        pelacak = PelacakWajah()
        keadaan: dict = {}          # id -> {"halus": Kotak, "mulut": array}
        hasil, gray_lalu, thumb_lalu = [], None, None

        cap.set(cv2.CAP_PROP_POS_FRAMES, int(mulai * fps))
        idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        berikutnya = mulai
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / fps
            idx += 1
            if t > akhir:
                break
            if t + 1e-9 < berikutnya:
                continue
            berikutnya += langkah
            kecil = cv2.resize(frame, (dw, dh)) if skala < 1.0 else frame
            gray = cv2.cvtColor(kecil, cv2.COLOR_BGR2GRAY)
            thumb = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype("float32")
            potong, luas_gerak = False, 0.0
            if thumb_lalu is not None:
                selisih = np.abs(thumb - thumb_lalu)
                if float(np.mean(selisih)) > AMBANG_POTONG:
                    potong = True
                else:
                    luas_gerak = float(np.mean(selisih > AMBANG_PIKSEL_GERAK))
            if potong:
                pelacak.reset()
                keadaan.clear()
            _, wajah = detektor.detect(kecil)
            kotak = [Kotak(float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[14]),
                           (float(r[5]) + float(r[7])) / 2)
                     for r in (wajah if wajah is not None else [])]
            ids = pelacak.perbarui(kotak)
            pengamatan = []
            for id_, k in zip(ids, kotak):
                st = keadaan.get(id_)
                halus = k if st is None else _halus(st["halus"], k)
                mulut = _petak(gray, halus, "mulut")
                if mulut is not None:
                    mulut = mulut - mulut.mean()
                gerak_mulut = gerak_wajah = None
                if st is not None and mulut is not None and st.get("mulut") is not None:
                    gerak_mulut = float(np.mean(np.abs(mulut - st["mulut"])))
                if gray_lalu is not None and st is not None:
                    a, b = _petak(gray, halus, "wajah"), _petak(gray_lalu, halus, "wajah")
                    if a is not None and b is not None:
                        gerak_wajah = float(np.mean(np.abs(a - b)))
                keadaan[id_] = {"halus": halus, "mulut": mulut}
                mata = None if halus.mata_y is None else halus.mata_y / skala
                pengamatan.append(Pengamatan(id_, Kotak(k.x / skala, k.y / skala, k.w / skala, k.h / skala, k.skor, mata),
                                             gerak_mulut, gerak_wajah))
            hasil.append(Sampel(round(t, 3), tuple(pengamatan), potong, luas_gerak))
            gray_lalu, thumb_lalu = gray, thumb
            if pada_kemajuan is not None:
                pada_kemajuan(min(1.0, max(0.0, (t - mulai) / (akhir - mulai))))
        return hasil, lebar, tinggi, fps
    finally:
        cap.release()


def lacak_pembicara(path_video, mulai: float, akhir: float, rasio: str = "9:16", *, kata=None, path_model=None,
                    selang_zoom=(), faktor_zoom: float = FAKTOR_ZOOM, gaya: str = "lama", napas: bool = True,
                    reaksi: bool = False, zoom_dasar: bool = False, pada_kemajuan=None, potongan: bool = False):
    """Alur lengkap: analisis -> foto -> pembicara -> lonjakan -> jalur. Mengembalikan (Jalur, Laporan)."""
    sampel, lebar, tinggi, _ = analisis_video(path_video, mulai, akhir, path_model=path_model,
                                              pada_kemajuan=pada_kemajuan)
    if not sampel:
        raise ValueError("tidak ada frame terbaca pada rentang waktu itu")
    foto, med = klasifikasi_foto(sampel)
    pembicara = pilih_pembicara(sampel, foto, ada_ucapan(kata) if kata is not None else None)
    if gaya == "campuran" and reaksi:                  # eksperimen: mati bawaan, pembicara tetap diutamakan
        pembicara = tambah_reaksi(sampel, pembicara, foto)
    lonjakan = deteksi_lonjakan(sampel, foto)
    jalur, sasaran_x = susun_jalur(sampel, pembicara, foto, lebar, tinggi, rasio, selang_lebar=lonjakan,
                                   selang_zoom=selang_zoom, faktor_zoom=faktor_zoom, gaya=gaya, napas=napas, zoom_dasar=zoom_dasar,
                                   potongan=potongan,
                                   waktu_jeda=titik_jeda(kata, sampel[0].t, sampel[-1].t) if kata is not None else (),
                                   zona_mati=ZONA_CAMPURAN if gaya == "campuran" else ZONA_NYAMAN,
                                   alpha=ALPHA_CAMPURAN if gaya == "campuran" else ALPHA_HALUS)

    luas = [x.luas_gerak for x in sampel]
    cepat = kecepatan_wajah(sampel, foto)
    lap = Laporan(median_gerak={i: round(m, 3) for i, m in med.items()}, lonjakan=lonjakan,
                  potongan=[s.t for s in sampel if s.potong],
                  statistik_gerak={"luas_median": round(_median(luas), 4), "luas_maks": round(max(luas), 4),
                                   "kecepatan_median": round(_median(cepat), 3), "kecepatan_maks": round(max(cepat), 3)})
    posisi = {}
    for s in sampel:
        for p in s.wajah:
            posisi.setdefault(p.id, []).append(p.kotak.pusat[0] / lebar)
    lap.foto = {i: round(sum(posisi[i]) / len(posisi[i]), 3) for i in foto if i in posisi}
    lalu = None
    for s, spk, sx in zip(sampel, pembicara, sasaran_x):
        if spk != lalu and spk is not None:
            lap.pergantian.append((s.t, spk, round(sx, 3)))
        if spk is not None:
            lalu = spk
        lap.pembicara_x.append((s.t, sx if spk is not None else None))
        terbesar = max(s.wajah, key=lambda p: p.kotak.luas) if s.wajah else None
        lap.terbesar_x.append((s.t, terbesar.kotak.pusat[0] / lebar if terbesar else None))
    return jalur, lap


# ===========================================================================
# TERMINAL
# ===========================================================================
def _simpan_gambar(video, jalur: Jalur, lap: Laporan, waktu_list, folder: Path):
    import cv2
    folder.mkdir(parents=True, exist_ok=True)
    jumlah = 0
    cap = cv2.VideoCapture(str(video))
    try:
        for t, nama in waktu_list:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            x, y = jalur.pada(t)
            cv2.rectangle(frame, (int(x), int(y)), (int(x + jalur.lebar_potong), int(y + jalur.tinggi_potong)),
                          (0, 0, 255), 3)
            cv2.putText(frame, f"{nama} t={t:.1f}s", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.imwrite(str(folder / f"{jumlah + 1:02d}_{nama}_{t:.1f}.jpg"), frame)
            jumlah += 1
    finally:
        cap.release()
    return jumlah


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pembicara aktif: analisis dan jalur jendela potong.")
    ap.add_argument("video")
    ap.add_argument("--mulai", type=float, required=True)
    ap.add_argument("--akhir", type=float, required=True)
    ap.add_argument("--rasio", default="9:16", choices=list(RASIO_VALID))
    ap.add_argument("--kata", default=None, help="kata.json dari core.transcribe (untuk gerbang ucapan)")
    ap.add_argument("--label", default=None, help="label.json: [{\"mulai\":..,\"akhir\":..,\"x\":0..1}]")
    ap.add_argument("--gambar-dir", default=None, help="folder untuk gambar pratinjau pada tiap pergantian")
    ap.add_argument("--simpan", default=None, help="simpan jalur ke berkas JSON")
    arg = ap.parse_args(argv)
    try:
        kata = None
        if arg.kata:
            from .transcribe import dari_json
            kata = dari_json(Path(arg.kata).read_text(encoding="utf-8"))
        jalur, lap = lacak_pembicara(arg.video, arg.mulai, arg.akhir, arg.rasio, kata=kata)
        label = json.loads(Path(arg.label).read_text(encoding="utf-8")) if arg.label else None
        hasil_label = (ketepatan(lap.pembicara_x, label), ketepatan(lap.terbesar_x, label)) if label else None
    except (OSError, ValueError, RuntimeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    print(f"Jendela potong     : {jalur.lebar_potong}x{jalur.tinggi_potong} (rasio {jalur.rasio})")
    print(f"Ada wajah hidup    : {jalur.persen_berwajah:.0%} dari sampel")
    print(f"Gerbang ucapan     : {'dari transkrip' if kata is not None else 'TIDAK dipakai (tanpa --kata)'}")
    print(f"Pergantian kamera  : {len(lap.potongan)}" + (f" (pada {', '.join(f'{t:.1f}' for t in lap.potongan[:10])} dtk)" if lap.potongan else ""))
    print(f"Wajah dianggap foto: {len(lap.foto)}" + "".join(f"\n    jalur {i}: posisi x {x:.2f}, median gerak {lap.median_gerak.get(i, 0):.2f}" for i, x in lap.foto.items()))
    hidup = {i: m for i, m in lap.median_gerak.items() if i not in lap.foto}
    if hidup:
        print("Median gerak wajah hidup (bandingkan dengan ambang foto "
              f"{AMBANG_FOTO}): " + ", ".join(f"jalur {i}={m:.2f}" for i, m in sorted(hidup.items())[:8]))
    print(f"Pergantian pembicara: {len(lap.pergantian)}")
    for t, i, x in lap.pergantian[:15]:
        print(f"    {t:6.1f} dtk -> jalur {i} (posisi x {x:.2f})")
    st = lap.statistik_gerak
    print(f"Lonjakan gerak     : {len(lap.lonjakan)}" + "".join(f"\n    {a:.1f} - {b:.1f} dtk (tampilan melebar)" for a, b in lap.lonjakan))
    print(f"    luas gerak: median {st['luas_median']:.1%}, maks {st['luas_maks']:.1%} (pemicu >= {LUAS_LONJAKAN_MIN:.0%}) | "
          f"kecepatan wajah: median {st['kecepatan_median']:.2f}, maks {st['kecepatan_maks']:.2f} "
          f"(pemicu >= {KECEPATAN_WAJAH_MIN}) lebar-wajah/dtk")
    if hasil_label:
        baru, lama = hasil_label
        print(f"Ketepatan (label)  : metode baru {baru['persen']:.0%} ({baru['cocok']}/{baru['sampel']}) | "
              f"wajah terbesar (lama) {lama['persen']:.0%} ({lama['cocok']}/{lama['sampel']})")
    if arg.simpan:
        tujuan = Path(arg.simpan)
        tujuan.parent.mkdir(parents=True, exist_ok=True)
        tujuan.write_text(json.dumps({"rasio": jalur.rasio, "lebar_potong": jalur.lebar_potong,
                                      "tinggi_potong": jalur.tinggi_potong, "titik": jalur.titik,
                                      "selang_lebar": list(jalur.selang_lebar)}), encoding="utf-8")
        print(f"Jalur disimpan     : {tujuan}")
    if arg.gambar_dir:
        waktu = [(t, "ganti") for t, _, _ in lap.pergantian[:8]] + [(a, "lebar") for a, _ in lap.lonjakan[:3]]
        n = _simpan_gambar(arg.video, jalur, lap, waktu, Path(arg.gambar_dir))
        print(f"Gambar pratinjau   : {n} berkas di {arg.gambar_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
