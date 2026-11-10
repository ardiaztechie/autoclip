"""scoring.py: memberi nilai pada calon clip.

Bagian 1 (file ini): skor Hook dan Flow, validasi data, dan rincian per indikator.
Bagian 2 (file ini): skor Value dan Trend.
Bagian 3 (file ini): penggabungan menjadi skor akhir 0-100.

PRINSIP
  - Setiap skor bernilai 0.0 sampai 1.0 (makin tinggi makin baik).
  - Semua angka, bobot, dan ambang di file ini adalah NILAI AWAL yang akan diuji
    dan disetel pada tahap pengujian skripsi. Bukan standar baku.
  - Metode berbasis aturan dan pencocokan kata. Ia mengukur CIRI permukaan teks dan
    waktu bicara. Ia TIDAK memahami makna, konteks, atau emosi sebuah kalimat.
  - Data yang tidak layak dinilai menghasilkan skor 0.0 dan valid=False pada rincian
    (lihat validasi_calon). Nol dipilih supaya data buruk tidak pernah mendapat skor
    "tengah" yang terlihat wajar. Karena 0.0 pada Hook juga bisa muncul dari data
    sah, pemanggil harus membuang calon tidak valid LEBIH DULU memakai validasi_calon().

Cara mencoba tanpa video (data contoh bawaan):
    python -m core.scoring
"""
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, replace

from .models import TANDA_AKHIR, Candidate, EnergyProfile, ScoredCandidate, Sentence, Word

# ===========================================================================
# PARAMETER (nilai awal, dapat diuji)
# ===========================================================================

# --- Pemecah teks -----------------------------------------------------------
POLA_KATA = re.compile(r"[\w'-]+", re.UNICODE)    # ikut menangkap "hati-hati"
TANDA_TUTUP = "\"'”’)]}"                           # boleh menempel setelah tanda akhir
TANDA_TEPI_KATA = ".,?!;:…\"'“”‘’()[]{}-"          # dibuang di tepi kata saat pencocokan

# --- HOOK -------------------------------------------------------------------
# Kata pemancing dipilih karena fungsi retorisnya (menimbulkan rasa penasaran,
# mengajukan pertanyaan, memperingatkan, mengajak, menegaskan). Kata yang di
# percakapan biasa lebih sering berfungsi sebagai kata sambung/partikel sengaja
# DIKECUALIKAN karena berisiko menaikkan skor tanpa alasan:
#   kok, cara, coba, sebenarnya : sangat umum di kalimat biasa
#   pernah  : sudah terwakili tanda tanya
#   salah   : muncul pada "salah satu" (sangat umum)
# Pencocokan memakai token utuh dan tidak membedakan huruf besar/kecil.
KATA_HOOK_PER_KATEGORI = {
    "penasaran":  frozenset({"ternyata", "faktanya", "bayangkan", "uniknya", "rahasia"}),
    "pertanyaan": frozenset({"kenapa", "mengapa", "bagaimana", "tahukah"}),
    "informasi":  frozenset({"alasan", "tips", "fakta", "begini"}),
    "peringatan": frozenset({"awas", "hati-hati", "jangan", "bahaya", "stop"}),
    "kejutan":    frozenset({"mengejutkan", "gila"}),
    "ajakan":     frozenset({"simak", "perhatikan", "ingat"}),
    "penegasan":  frozenset({"wajib", "penting", "serius"}),
    "inggris":    frozenset({"secret", "never", "why", "how", "truth", "mistake",
                             "imagine", "warning", "actually", "biggest"}),
}
KATA_HOOK = frozenset().union(*KATA_HOOK_PER_KATEGORI.values())
FRASA_HOOK = ("tidak disangka", "tak disangka")     # frasa dua kata

POIN_HOOK = {"tanda_tanya": 0.30, "angka": 0.20, "kata_pemancing": 0.30, "panjang": 0.20}
BATAS_PEMBUKA_PENDEK = 15      # kata: poin penuh
BATAS_PEMBUKA_SEDANG = 25      # kata: setengah poin
POIN_PANJANG_SEDANG = 0.10

# --- FLOW -------------------------------------------------------------------
BOBOT_FLOW = {"tempo": 0.40, "jeda": 0.30, "pengisi": 0.15, "lengkap": 0.15}

TEMPO_IDEAL = (2.0, 3.5)       # kata per detik (parameter awal, bukan standar universal)
TEMPO_NOL_BAWAH = 0.5          # di bawah ini skor tempo 0
TEMPO_NOL_ATAS = 6.0           # di atas ini skor tempo 0

JEDA_PANJANG = 1.0             # detik. Jeda antar kata di atas ini dianggap jeda panjang
FAKTOR_JEDA = 4.0              # skor jeda 0 bila jeda panjang mencapai 1/FAKTOR_JEDA durasi (25%)
JEDA_HITUNG_KELEBIHAN = True   # True : hanya waktu di atas JEDA_PANJANG yang dihitung (kontinu)
                               # False: seluruh jeda dihitung begitu melewati batas (perilaku lama)
TEMPO_TANPA_JEDA_PANJANG = True  # True : tempo dihitung tanpa jeda yang sudah dihukum indikator jeda
                                 # False: tempo dihitung dari seluruh durasi (perilaku lama)

# Kata pengisi. "um", "em", "er" sengaja tidak dimasukkan karena juga kata biasa di
# bahasa lain (Portugis "um"/"em", Jerman/Belanda "er"), sedangkan sistem ini
# multi-bahasa. "kayak", "gitu", "jadi", "sebenarnya" tidak dimasukkan karena fungsinya
# dalam kalimat tidak bisa dibedakan dari pemakaian biasa.
KATA_PENGISI = frozenset({"eh", "ehh", "eeh", "eee", "eem", "emm", "hm", "hmm",
                          "anu", "uh", "uhh", "umm", "err"})
FAKTOR_PENGISI = 10.0          # skor pengisi 0 bila kata pengisi mencapai 10% dari seluruh kata
SKOR_TANPA_TANDA_AKHIR = 0.6   # skor jika tanpa penutup tegas, termasuk elipsis

# --- Validasi ---------------------------------------------------------------
MAKS_MASALAH = 5               # jumlah pesan masalah yang dilaporkan

# Batas tumpang tindih antar kata. Kata berikutnya boleh mulai paling awal
# TOLERANSI_TUMPANG_TINDIH detik SEBELUM kata sebelumnya selesai.
#   sampai batas ini : dianggap derau timestamp, jedanya dihitung nol tanpa penalti
#   melewati batas   : dianggap data rusak, calon clip ditolak (valid=False)
# Alasan nilai awal 0,5: sekitar durasi satu kata pada 2,5 kata/detik (0,4 detik);
# tumpang tindih yang lebih panjang dari satu kata utuh tidak lagi wajar.
# CATATAN: ini nilai awal. Cek terhadap keluaran Whisper yang nyata, lalu setel.
TOLERANSI_TUMPANG_TINDIH = 0.5   # detik


# ===========================================================================
# ALAT BANTU
# ===========================================================================
def _token(teks: str) -> list[str]:
    return [t.casefold() for t in POLA_KATA.findall(teks)]


def _bersihkan_kata(teks: str) -> str:
    """Satu kata -> huruf kecil tanpa tanda baca di tepi (agar 'Eh,' sama dengan 'eh')."""
    return teks.casefold().strip().strip(TANDA_TEPI_KATA)


def _batasi(nilai: float, bawah: float = 0.0, atas: float = 1.0) -> float:
    """Menjaga nilai tetap di antara bawah dan atas."""
    return max(bawah, min(atas, nilai))


def _angka_valid(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _ditutup_tanda_akhir(teks: str) -> bool:
    """True bila teks berakhir dengan tanda akhir, bukan elipsis/titik berulang."""
    inti = teks.strip().rstrip(TANDA_TUTUP)
    # Elipsis menunjukkan ujaran menggantung, bukan penutupan yang tegas.
    if inti.endswith(("..", "…")):
        return False
    return inti.endswith(TANDA_AKHIR)


# ===========================================================================
# VALIDASI DATA
# ===========================================================================
def validasi_calon(calon) -> list[str]:
    """Memeriksa apakah calon clip layak dinilai. Daftar kosong = layak.

    Dianggap TIDAK layak (tidak bisa dinilai dengan andal):
      - tidak ada kalimat, atau ada kalimat tanpa kata
      - teks kata bukan teks, atau timestamp kosong / bukan angka / NaN / tak hingga
      - timestamp negatif, atau kata berakhir sebelum dimulai
      - kata tidak berurutan (waktu mulai mundur)
      - tumpang tindih antar kata melebihi TOLERANSI_TUMPANG_TINDIH
      - durasi calon clip nol atau negatif

    Dianggap WAJAR (bukan kesalahan):
      - tumpang tindih antar kata sampai TOLERANSI_TUMPANG_TINDIH (kata berikut mulai
        sebelum kata sebelumnya selesai). Jedanya dihitung nol, tanpa penalti.

    Kelayakan durasi minimum (misalnya 20 detik) adalah tugas build_candidates,
    bukan tugas modul skoring.
    """
    kalimat = getattr(calon, "sentences", None)
    if not isinstance(kalimat, (list, tuple)) or len(kalimat) == 0:
        return ["calon clip tidak memiliki kalimat"]

    masalah: list[str] = []
    kata_semua: list = []
    for i, k in enumerate(kalimat, start=1):
        daftar = getattr(k, "words", None)
        if not isinstance(daftar, (list, tuple)) or len(daftar) == 0:
            masalah.append(f"kalimat ke-{i} tidak memiliki kata")
        else:
            kata_semua.extend(daftar)
    if masalah:
        return masalah[:MAKS_MASALAH]

    for j, w in enumerate(kata_semua, start=1):
        mulai, akhir = getattr(w, "start", None), getattr(w, "end", None)
        if not isinstance(getattr(w, "text", None), str):
            masalah.append(f"kata ke-{j} tidak memiliki teks")
        if not (_angka_valid(mulai) and _angka_valid(akhir)):
            masalah.append(f"timestamp kata ke-{j} kosong atau bukan angka yang valid")
        elif mulai < 0 or akhir < 0:
            masalah.append(f"timestamp kata ke-{j} negatif")
        elif akhir < mulai:
            masalah.append(f"kata ke-{j} berakhir sebelum dimulai")
    if masalah:
        return masalah[:MAKS_MASALAH]

    for j, (a, b) in enumerate(zip(kata_semua, kata_semua[1:]), start=2):
        if b.start < a.start:
            masalah.append(f"kata ke-{j} dimulai lebih awal dari kata sebelumnya (tidak berurutan)")
        elif a.end - b.start > TOLERANSI_TUMPANG_TINDIH + 1e-9:
            masalah.append(f"kata ke-{j} tumpang tindih {a.end - b.start:.2f} detik dengan kata sebelumnya "
                           f"(batas {TOLERANSI_TUMPANG_TINDIH:g} detik)")
    if masalah:
        return masalah[:MAKS_MASALAH]

    if kata_semua[-1].end - kata_semua[0].start <= 0:
        masalah.append("durasi calon clip nol atau negatif")
    return masalah


# ===========================================================================
# HOOK: apakah pembukaannya memiliki ciri pembukaan yang kuat?
# ===========================================================================
@dataclass(frozen=True)
class RincianHook:
    skor: float
    valid: bool = True
    masalah: tuple = ()
    poin_tanda_tanya: float = 0.0
    poin_angka: float = 0.0
    poin_kata_pemancing: float = 0.0
    poin_panjang: float = 0.0
    kata_ditemukan: tuple = ()
    jumlah_kata_pembuka: int = 0


def hook_detail(calon: Candidate) -> RincianHook:
    """Menilai KALIMAT PERTAMA calon clip. Rinciannya per indikator.

    Indikator dan poin awal:
      tanda tanya      0,30  ada "?"
      angka            0,20  ada angka (digit)
      kata pemancing   0,30  ada kata/frasa dari KATA_HOOK / FRASA_HOOK
      panjang pembuka  0,20  maks 15 kata; 0,10 bila maks 25 kata; selain itu 0

    Keterbatasan: ini mengukur ciri permukaan pembukaan, bukan daya tarik semantik.
    Kalimat dengan "ternyata" belum tentu lebih menarik daripada yang tanpa kata itu.
    """
    masalah = validasi_calon(calon)
    if masalah:
        return RincianHook(skor=0.0, valid=False, masalah=tuple(masalah))

    pembuka = calon.sentences[0]
    teks = pembuka.text
    token = _token(teks)
    teks_token = " " + " ".join(token) + " "

    ditemukan = sorted(set(token) & KATA_HOOK)
    ditemukan += [f for f in FRASA_HOOK if f" {f} " in teks_token]

    poin_tanya = POIN_HOOK["tanda_tanya"] if "?" in teks else 0.0
    poin_angka = POIN_HOOK["angka"] if any(h.isdecimal() for h in teks) else 0.0
    poin_pancing = POIN_HOOK["kata_pemancing"] if ditemukan else 0.0

    jumlah = len(pembuka.words)
    if jumlah <= BATAS_PEMBUKA_PENDEK:
        poin_panjang = POIN_HOOK["panjang"]
    elif jumlah <= BATAS_PEMBUKA_SEDANG:
        poin_panjang = POIN_PANJANG_SEDANG
    else:
        poin_panjang = 0.0

    skor = _batasi(poin_tanya + poin_angka + poin_pancing + poin_panjang)
    return RincianHook(skor, True, (), poin_tanya, poin_angka, poin_pancing,
                       poin_panjang, tuple(ditemukan), jumlah)


def hook_score(calon: Candidate) -> float:
    return hook_detail(calon).skor


# ===========================================================================
# FLOW: apakah pembicaraannya lancar dan enak diikuti?
# ===========================================================================
@dataclass(frozen=True)
class RincianFlow:
    skor: float
    valid: bool = True
    masalah: tuple = ()
    tempo: float = 0.0              # kata per detik (sesuai pengaturan TEMPO_TANPA_JEDA_PANJANG)
    skor_tempo: float = 0.0
    jeda_dinilai: float = 0.0       # detik jeda panjang yang dihitung
    skor_jeda: float = 0.0
    jumlah_pengisi: int = 0
    skor_pengisi: float = 0.0
    skor_lengkap: float = 0.0


def _jeda_dinilai(kata) -> float:
    """Total detik jeda panjang. Jeda negatif (tumpang tindih) dihitung nol."""
    total = 0.0
    for a, b in zip(kata, kata[1:]):
        jeda = max(0.0, b.start - a.end)
        if jeda > JEDA_PANJANG:
            total += (jeda - JEDA_PANJANG) if JEDA_HITUNG_KELEBIHAN else jeda
    return total


def flow_detail(calon: Candidate) -> RincianFlow:
    """Menilai kelancaran dari empat indikator, lalu menggabungkannya.

    Bobot awal: tempo 40%, jeda 30%, pengisi 15%, kelengkapan 15%.

    Indikator dibuat saling lepas: waktu jeda panjang dikeluarkan dari perhitungan
    tempo (TEMPO_TANPA_JEDA_PANJANG) supaya jeda tidak dihukum dua kali.

    Keterbatasan: tanda baca penutup belum tentu berarti pembicara sudah selesai
    secara makna. Daftar kata pengisi bergantung pada apa yang dituliskan Whisper.
    """
    masalah = validasi_calon(calon)
    if masalah:
        return RincianFlow(skor=0.0, valid=False, masalah=tuple(masalah))

    kata = calon.words
    durasi = calon.duration
    jeda = _jeda_dinilai(kata)

    # 1) Tempo
    waktu_bicara = durasi - jeda if TEMPO_TANPA_JEDA_PANJANG else durasi
    waktu_bicara = max(waktu_bicara, 1e-6)          # pengaman numerik
    tempo = len(kata) / waktu_bicara
    if TEMPO_IDEAL[0] <= tempo <= TEMPO_IDEAL[1]:
        skor_tempo = 1.0
    elif tempo < TEMPO_IDEAL[0]:
        skor_tempo = _batasi((tempo - TEMPO_NOL_BAWAH) / (TEMPO_IDEAL[0] - TEMPO_NOL_BAWAH))
    else:
        skor_tempo = _batasi((TEMPO_NOL_ATAS - tempo) / (TEMPO_NOL_ATAS - TEMPO_IDEAL[1]))

    # 2) Jeda panjang
    skor_jeda = 1.0 - _batasi((jeda / durasi) * FAKTOR_JEDA)

    # 3) Kata pengisi
    pengisi = sum(1 for k in kata if _bersihkan_kata(k.text) in KATA_PENGISI)
    skor_pengisi = 1.0 - _batasi((pengisi / len(kata)) * FAKTOR_PENGISI)

    # 4) Kalimat terakhir ditutup tanda akhir yang tegas (bukan elipsis)
    skor_lengkap = 1.0 if _ditutup_tanda_akhir(kata[-1].text) else SKOR_TANPA_TANDA_AKHIR

    skor = _batasi(BOBOT_FLOW["tempo"] * skor_tempo + BOBOT_FLOW["jeda"] * skor_jeda
                   + BOBOT_FLOW["pengisi"] * skor_pengisi + BOBOT_FLOW["lengkap"] * skor_lengkap)
    return RincianFlow(skor, True, (), tempo, skor_tempo, jeda, skor_jeda,
                       pengisi, skor_pengisi, skor_lengkap)


def flow_score(calon: Candidate) -> float:
    return flow_detail(calon).skor


# ===========================================================================
# BAGIAN 2: VALUE dan TREND
# ===========================================================================
# --- Parameter VALUE ---------------------------------------------------------
PANJANG_MIN_ISTILAH = 3        # token lebih pendek dari ini tidak dihitung sebagai istilah
MIN_KALIMAT_IDF = 10           # korpus lebih kecil dari ini: IDF tidak andal, Value tidak dihitung
JUMLAH_ISTILAH_TERATAS = 3     # berapa istilah penyumbang terbesar yang dilaporkan

# --- Parameter TREND ---------------------------------------------------------
BOBOT_TREND = {"energi": 0.70, "penanda": 0.30}
FAKTOR_PENANDA = 10.0          # skor penanda 1 bila penanda mencapai 10% dari jumlah kata
TOLERANSI_CAKUPAN_ENERGI = 1.0  # langkah. Calon boleh berakhir paling jauh sebesar ini di luar profil

# Penanda emosi/penekanan. Seperti daftar lain, ini nilai awal yang dapat disetel dan
# hanya mencocokkan kata permukaan (tidak memahami konteks atau sarkasme).
KATA_EMOSI = frozenset({
    "wow", "wah", "astaga", "gila", "hebat", "keren", "parah", "mengerikan", "menakjubkan",
    "sedih", "marah", "kesal", "kecewa", "bangga", "takut", "kaget", "benci", "bahagia",
    "amazing", "incredible", "crazy", "love", "hate", "terrible", "awesome",
})
FRASA_EMOSI = ("luar biasa", "ya ampun")


def _normalisasi_minmax(nilai: list[float]) -> list[float]:
    """Skala ulang ke 0..1 antar calon. Kosong -> []; semua sama atau hanya satu -> 0.5."""
    if not nilai:
        return []
    bawah, atas = min(nilai), max(nilai)
    if atas - bawah <= 1e-12:
        return [0.5] * len(nilai)
    return [(x - bawah) / (atas - bawah) for x in nilai]


# ===========================================================================
# VALUE: seberapa kaya istilah khas pada calon dibanding seluruh video?
# ===========================================================================
@dataclass(frozen=True)
class ModelIDF:
    """IDF per istilah, dihitung dari seluruh kalimat video (satu kalimat = satu dokumen)."""
    idf: dict
    jumlah_kalimat: int
    memadai: bool
    idf_baru: float                 # IDF untuk istilah yang tidak ada di korpus

    def bobot(self, istilah: str) -> float:
        return self.idf.get(istilah, self.idf_baru)


@dataclass(frozen=True)
class RincianValue:
    skor: float                     # 0..1, sudah dinormalisasi antar calon
    valid: bool = True
    masalah: tuple = ()
    nilai_mentah: float = 0.0       # sebelum normalisasi (rata-rata IDF tertimbang frekuensi)
    jumlah_istilah: int = 0
    istilah_teratas: tuple = ()


def _istilah(teks: str) -> list[str]:
    """Token yang dihitung sebagai istilah: cukup panjang dan bukan angka murni."""
    return [t for t in _token(teks) if len(t) >= PANJANG_MIN_ISTILAH and not t.isdigit()]


def _kalimat_teks(kalimat):
    """Teks sebuah kalimat, atau None bila datanya tidak berbentuk kalimat berisi kata."""
    try:
        kata = getattr(kalimat, "words", None)
        if not isinstance(kata, (list, tuple)):
            return None
        teks = [w.text for w in kata if isinstance(getattr(w, "text", None), str)]
    except Exception:  # noqa: BLE001  objek rusak (properti melempar error) dianggap bukan kalimat
        return None
    return " ".join(teks) if teks else None


def build_idf(kalimat) -> ModelIDF:
    """Membangun model IDF dari seluruh kalimat video. Data sampah dilewati, bukan error."""
    df: Counter = Counter()
    n = 0
    try:
        daftar = list(kalimat)
    except TypeError:
        daftar = []
    for k in daftar:
        teks = _kalimat_teks(k)
        if teks is None:
            continue
        n += 1
        df.update(set(_istilah(teks)))
    idf = {t: math.log((1 + n) / (1 + d)) + 1.0 for t, d in df.items()}
    return ModelIDF(idf, n, n >= MIN_KALIMAT_IDF, math.log(1 + n) + 1.0)


def _value_mentah(calon: Candidate, model: ModelIDF):
    """Sum(tf x idf) dengan tf = porsi istilah terhadap seluruh token istilah calon.

    Memakai porsi (bukan jumlah mentah) dan bukan top-N supaya panjang calon tidak
    mengubah nilai: pola kalimat yang sama menghasilkan nilai yang sama pada 5 maupun 20 kalimat.
    """
    token: list[str] = []
    for k in calon.sentences:
        token += _istilah(_kalimat_teks(k) or "")
    if not token:
        return 0.0, 0, ()
    total = len(token)
    sumbangan = {t: (c / total) * model.bobot(t) for t, c in Counter(token).items()}
    teratas = sorted(sumbangan.items(), key=lambda x: (-x[1], x[0]))[:JUMLAH_ISTILAH_TERATAS]
    return sum(sumbangan.values()), total, tuple(t for t, _ in teratas)


def value_scores(calon_list, model: ModelIDF) -> list[RincianValue]:
    """Skor Value untuk SEKUMPULAN calon (dinormalisasi min-max antar calon yang valid).

    Karena dinormalisasi antar kandidat, skor menyatakan peringkat relatif dalam satu
    video, bukan kualitas mutlak, dan berubah bila kumpulan kandidatnya berubah.
    Calon tidak valid, atau korpus terlalu kecil, menghasilkan skor 0.0 dan valid=False.

    Keterbatasan: mengukur keragaman istilah, bukan kebenaran atau manfaat isi. Pengulangan
    satu kata langka dapat menaikkan nilai. Tokenisasi per spasi tidak cocok untuk bahasa
    tanpa spasi (Mandarin, Jepang, Thai).
    """
    daftar = list(calon_list)
    hasil: list = [None] * len(daftar)
    idx, mentah = [], []
    for i, c in enumerate(daftar):
        masalah = validasi_calon(c)
        if masalah:
            hasil[i] = RincianValue(0.0, False, tuple(masalah))
        elif not model.memadai:
            hasil[i] = RincianValue(0.0, False, (
                f"korpus terlalu kecil untuk IDF ({model.jumlah_kalimat} kalimat, minimal {MIN_KALIMAT_IDF})",))
        else:
            nilai, jumlah, teratas = _value_mentah(c, model)
            hasil[i] = RincianValue(0.0, True, (), nilai, jumlah, teratas)
            idx.append(i)
            mentah.append(nilai)
    for i, skor in zip(idx, _normalisasi_minmax(mentah)):
        hasil[i] = replace(hasil[i], skor=_batasi(skor))
    return hasil


# ===========================================================================
# TREND: seberapa bertenaga suara dan seberapa banyak penanda emosi pada calon?
# ===========================================================================
@dataclass(frozen=True)
class RincianTrend:
    skor: float
    valid: bool = True
    masalah: tuple = ()
    energi_tersedia: bool = False
    rasio_energi: float = 0.0       # energi rata-rata calon / energi rata-rata seluruh video
    skor_energi: float = 0.0        # rasio dinormalisasi min-max antar calon
    jumlah_penanda: int = 0
    skor_penanda: float = 0.0
    penanda_ditemukan: tuple = ()


def _masalah_energi(profil) -> list[str]:
    """Memeriksa profil energi. Daftar kosong = layak dipakai."""
    langkah = getattr(profil, "step", None)
    nilai = getattr(profil, "values", None)
    if not _angka_valid(langkah) or langkah <= 0:
        return ["langkah (step) profil energi bukan angka positif yang valid"]
    if not isinstance(nilai, (list, tuple)) or len(nilai) == 0:
        return ["profil energi kosong"]
    for i, x in enumerate(nilai, start=1):
        if not _angka_valid(x) or x < 0:
            return [f"nilai energi ke-{i} bukan angka valid atau negatif"]
    total = sum(nilai)
    if not math.isfinite(total):
        return ["jumlah energi tak hingga"]
    if total <= 0:
        return ["energi seluruh video nol (tidak ada pembanding)"]
    return []


def _rata_energi(profil, mulai: float, akhir: float):
    """Rata-rata energi tertimbang waktu pada mulai..akhir, atau None bila di luar cakupan.

    Tiap nilai mewakili rentang [i*step, (i+1)*step). Lebih akurat daripada
    EnergyProfile.mean yang membulatkan indeks.
    """
    langkah, nilai = profil.step, profil.values
    if akhir > len(nilai) * langkah + langkah * TOLERANSI_CAKUPAN_ENERGI + 1e-9:
        return None
    awal_i = max(0, int(mulai // langkah))
    akhir_i = min(len(nilai) - 1, int(akhir // langkah))
    jumlah = bobot = 0.0
    for i in range(awal_i, akhir_i + 1):
        tumpang = min(akhir, (i + 1) * langkah) - max(mulai, i * langkah)
        if tumpang > 0:
            jumlah += nilai[i] * tumpang
            bobot += tumpang
    return jumlah / bobot if bobot > 0 else None


def _penanda(calon: Candidate):
    """Menghitung penanda emosi: kata mengandung '!' (sekali per kata) + kata/frasa emosi."""
    jumlah, ditemukan = 0, []
    for w in calon.words:
        if "!" in w.text:
            jumlah += 1
            ditemukan.append("!")
        bersih = _bersihkan_kata(w.text)
        if bersih in KATA_EMOSI:
            jumlah += 1
            ditemukan.append(bersih)
    teks_token = " " + " ".join(_token(calon.text)) + " "
    for f in FRASA_EMOSI:
        n = len(re.findall(rf"(?= {re.escape(f)} )", teks_token))
        jumlah += n
        ditemukan += [f] * n
    return jumlah, tuple(ditemukan)


def trend_scores(calon_list, energi=None) -> list[RincianTrend]:
    """Skor Trend untuk SEKUMPULAN calon.

    skor = 0,70 x skor_energi + 0,30 x skor_penanda
      skor_energi  : rasio energi calon terhadap rata-rata video, min-max antar calon
      skor_penanda : min(1, (penanda / jumlah kata) x 10)

    energi=None : hanya penanda yang dipakai (energi_tersedia=False). Skornya TIDAK
                  setara skala dengan versi lengkap, jadi jangan dicampur dalam satu peringkat.
    Profil energi rusak, atau calon di luar cakupan profil, menghasilkan skor 0.0, valid=False.

    Keterbatasan: energi RMS juga naik karena tepuk tangan atau musik, bukan hanya
    isi yang menarik. Min-max dapat melebarkan selisih kecil menjadi 0..1 bila semua
    calon sebenarnya mirip. Penanda hanya mencocokkan kata permukaan.
    """
    daftar = list(calon_list)
    masalah_profil = _masalah_energi(energi) if energi is not None else []
    hasil: list = [None] * len(daftar)
    idx, rasio, tempat = [], [], {}
    rata_video = None
    if energi is not None and not masalah_profil:
        rata_video = sum(energi.values) / len(energi.values)

    for i, c in enumerate(daftar):
        masalah = validasi_calon(c)
        if masalah:
            hasil[i] = RincianTrend(0.0, False, tuple(masalah))
            continue
        if masalah_profil:
            hasil[i] = RincianTrend(0.0, False, ("profil energi bermasalah: " + masalah_profil[0],))
            continue
        jumlah, ditemukan = _penanda(c)
        skor_p = _batasi((jumlah / len(c.words)) * FAKTOR_PENANDA)
        if energi is None:
            hasil[i] = RincianTrend(skor_p, True, (), False, 0.0, 0.0, jumlah, skor_p, ditemukan)
            continue
        rata = _rata_energi(energi, c.start, c.end)
        if rata is None:
            hasil[i] = RincianTrend(0.0, False, ("calon berada di luar cakupan profil energi",))
            continue
        idx.append(i)
        rasio.append(rata / rata_video)
        tempat[i] = (jumlah, skor_p, ditemukan)

    for i, r, skor_e in zip(idx, rasio, _normalisasi_minmax(rasio)):
        jumlah, skor_p, ditemukan = tempat[i]
        skor = _batasi(BOBOT_TREND["energi"] * skor_e + BOBOT_TREND["penanda"] * skor_p)
        hasil[i] = RincianTrend(skor, True, (), True, r, skor_e, jumlah, skor_p, ditemukan)
    return hasil


# ---------------------------------------------------------------------------
# Data contoh untuk demo Value dan Trend
# ---------------------------------------------------------------------------
_KORPUS_DEMO = (
    "Fotosintesis mengubah cahaya matahari menjadi energi kimia melalui klorofil daun.",
    "Inflasi memengaruhi daya beli dan suku bunga pasar modal secara bertahap.",
    "Nutrisi atlet muda menentukan stamina, pemulihan otot, dan prestasi pertandingan.",
    "Irama gamelan menuntun harmoni lagu daerah pada upacara adat.",
    "Pajak usaha kecil diatur regulasi khusus dengan tarif final tertentu.",
    "Candi peninggalan kerajaan kuno menyimpan prasasti sejarah yang berharga.",
    "Sensor presisi pada mesin pintar mendeteksi getaran sebelum komponen rusak.",
    "Rempah nusantara membentuk cita rasa kuliner dan perdagangan maritim dunia.",
    "Arsitektur rumah tropis memakai ventilasi silang untuk menurunkan suhu ruangan.",
    "Astronomi mempelajari galaksi, bintang, dan nebula di langit malam.",
    "Kita dan yang itu kita dan yang itu.",
    "Kita dan yang itu kita dan yang itu lagi.",
)


def _kalimat_waktu(teks: str, mulai: float, kecepatan: float = 2.5) -> Sentence:
    langkah = 1.0 / kecepatan
    return Sentence([Word(t, round(mulai + i * langkah, 3), round(mulai + i * langkah + langkah * 0.9, 3))
                     for i, t in enumerate(teks.split())])


def _calon_waktu(teks: str, mulai: float, kecepatan: float = 2.5) -> Candidate:
    return Candidate([_kalimat_waktu(teks, mulai, kecepatan)])


def _rangkai_kalimat(daftar_teks, mulai: float = 0.0, jeda: float = 0.3) -> list:
    hasil, t = [], mulai
    for teks in daftar_teks:
        k = _kalimat_waktu(teks, t)
        hasil.append(k)
        t = k.end + jeda
    return hasil


# ===========================================================================
# BAGIAN 3: SKOR AKHIR 0-100
# ===========================================================================
# Bobot awal (dari dokumen rencana). Nilai awal yang akan disetel pada pengujian.
BOBOT_AKHIR = {"hook": 0.30, "flow": 0.25, "value": 0.25, "trend": 0.20}

# Batas huruf nilai (skor akhir 0-100). Hanya label bantu tampilan, bukan standar baku.
BATAS_HURUF = (("A", 80.0), ("B", 65.0), ("C", 50.0))   # di bawah batas terakhir = "D"


def nilai_huruf(skor: float) -> str:
    """Label huruf dari skor akhir 0-100."""
    for huruf, batas in BATAS_HURUF:
        if skor >= batas:
            return huruf
    return "D"


@dataclass(frozen=True)
class HasilPenilaian:
    dinilai: list                   # list[ScoredCandidate], urutan sama dengan masukan
    ditolak: list                   # list[(nomor_masukan, alasan)], nomor mulai dari 0
    indeks_dinilai: list            # nomor masukan tiap calon pada `dinilai`


def nilai_calon(calon_list, model: ModelIDF, energi=None) -> HasilPenilaian:
    """Menilai sekumpulan calon dan MEMBUANG yang tidak layak LEBIH DULU.

    Urutan kerja (penting karena Value dan Trend dinormalisasi antar calon):
      1. buang calon tidak valid (validasi_calon)
      2. buang calon di luar cakupan profil energi, atau semua calon bila profil energi rusak
      3. hitung ulang Value dan Trend hanya pada calon yang tersisa
      4. skor akhir = 100 x (0,30 Hook + 0,25 Flow + 0,25 Value + 0,20 Trend)

    Calon yang dibuang dicatat beserta alasannya, tidak diberi skor "tengah".
    energi=None berarti Trend hanya dari penanda emosi (skala tidak setara; jangan dicampur
    dengan hasil yang memakai profil energi).
    """
    daftar = list(calon_list)
    ditolak: list = []
    layak: list = []                                   # (nomor, calon)
    for i, c in enumerate(daftar):
        masalah = validasi_calon(c)
        if masalah:
            ditolak.append((i, tuple(masalah)))
        else:
            layak.append((i, c))

    # Tahap 2: tapis dengan Trend, lalu normalisasi ulang tanpa yang dibuang
    rt = trend_scores([c for _, c in layak], energi)
    sisa = []
    for (i, c), r in zip(layak, rt):
        if r.valid:
            sisa.append((i, c))
        else:
            ditolak.append((i, tuple(r.masalah)))
    rt = trend_scores([c for _, c in sisa], energi)
    rv = value_scores([c for _, c in sisa], model)

    dinilai, indeks = [], []
    for (i, c), v, t in zip(sisa, rv, rt):
        if not v.valid:
            ditolak.append((i, tuple(v.masalah)))
            continue
        h, f = hook_score(c), flow_score(c)
        skor = 100.0 * (BOBOT_AKHIR["hook"] * h + BOBOT_AKHIR["flow"] * f
                        + BOBOT_AKHIR["value"] * v.skor + BOBOT_AKHIR["trend"] * t.skor)
        dinilai.append(ScoredCandidate(c, h, f, v.skor, t.skor, _batasi(skor, 0.0, 100.0)))
        indeks.append(i)
    ditolak.sort(key=lambda x: x[0])
    return HasilPenilaian(dinilai, ditolak, indeks)


def score_candidates(calon_list, model: ModelIDF, energi=None) -> list:
    """Hanya daftar ScoredCandidate (tanpa catatan penolakan). Lihat nilai_calon()."""
    return nilai_calon(calon_list, model, energi).dinilai


# ===========================================================================
# DEMO: python -m core.scoring
# ===========================================================================
def _calon_dari_kata(kata: list) -> Candidate:
    return Candidate([Sentence(kata)])


def _calon_contoh(teks: str, kecepatan: float = 2.5, jeda: dict | None = None) -> Candidate:
    """Satu calon clip (satu kalimat) dari teks. jeda = {nomor_kata: detik} sebelum kata itu."""
    jeda = jeda or {}
    langkah = 1.0 / kecepatan
    waktu = 0.0
    kata_kata = []
    for i, token in enumerate(teks.split()):
        waktu += jeda.get(i, 0.0)
        kata_kata.append(Word(token, round(waktu, 3), round(waktu + langkah * 0.9, 3)))
        waktu += langkah
    return _calon_dari_kata(kata_kata)


def _demo() -> int:
    biasa = " ".join(["kata"] * 19 + ["kata."])
    ok_semua = True

    # ---------------- HOOK ----------------
    print("HOOK: poin per indikator")
    print(f"  {'kasus':<34}{'tanya':>6}{'angka':>7}{'pancing':>9}{'panjang':>9}{'TOTAL':>8}   kata ditemukan")
    panjang_30 = "Kenapa rahasia " + " ".join(["kata"] * 27) + " ini?"
    kasus_hook = [
        ("Pembukaan kuat", "Tahukah kamu 3 rahasia sukses yang jarang dibahas?"),
        ("Cukup menarik", "Kenapa orang selalu salah soal uang?"),
        ("Datar", "Hari ini kami akan membahas hal biasa."),
        ("Hanya angka", "Hari ini kita bahas 5 hal biasa."),
        ("Hanya kata pemancing", "Ternyata hal ini jarang dibahas orang."),
        ("Tanpa tanda tanya", "Ada 3 rahasia sukses yang jarang dibahas."),
        ("Terlalu panjang (30 kata)", panjang_30),
        ("Frasa 'tidak disangka'", "Tidak disangka hasilnya sebagus ini."),
        ("'salah satu' (bukan pemancing)", "Salah satu cara terbaik adalah ini."),
    ]
    h = {}
    for nama, teks in kasus_hook:
        r = hook_detail(_calon_contoh(teks))
        h[nama] = r
        print(f"  {nama:<34}{r.poin_tanda_tanya:>6.2f}{r.poin_angka:>7.2f}{r.poin_kata_pemancing:>9.2f}"
              f"{r.poin_panjang:>9.2f}{r.skor:>8.2f}   {', '.join(r.kata_ditemukan)}")

    # ---------------- FLOW ----------------
    print("\nFLOW: skor per indikator (0-1)")
    print(f"  {'kasus':<36}{'kata/dtk':>9}{'tempo':>7}{'jeda(dtk)':>10}{'jeda':>6}{'pengisi':>8}{'lengkap':>8}{'TOTAL':>7}")
    kasus_flow = [
        ("Normal (akhir titik)", _calon_contoh(biasa)),
        ("Normal (akhir tanda tanya)", _calon_contoh(biasa[:-1] + "?")),
        ("Tempo terlalu cepat (6,5)", _calon_contoh(biasa, kecepatan=6.5)),
        ("Tempo terlalu lambat (0,6)", _calon_contoh(biasa, kecepatan=0.6)),
        ("Jeda 0,8 detik (di bawah batas)", _calon_contoh(biasa, jeda={10: 0.8})),
        ("Jeda 1,2 detik (sedikit di atas)", _calon_contoh(biasa, jeda={10: 1.2})),
        ("Satu jeda panjang (3 detik)", _calon_contoh(biasa, jeda={10: 3.0})),
        ("Tiga jeda panjang (3 detik)", _calon_contoh(biasa, jeda={4: 3.0, 9: 3.0, 14: 3.0})),
        ("Banyak kata pengisi (5 'eh')", _calon_contoh(" ".join(["eh"] * 5 + ["kata"] * 14 + ["kata."]))),
        ("Akhir tanpa tanda baca", _calon_contoh(biasa[:-1])),
        ("Akhir titik tiga (...)", _calon_contoh(biasa[:-1] + "...")),
        ("Akhir elipsis tunggal (…)", _calon_contoh(biasa[:-1] + "…")),
        ("Akhir tanda tanya tetap lengkap", _calon_contoh(biasa[:-1] + "?")),
    ]
    f = {}
    for nama, calon in kasus_flow:
        r = flow_detail(calon)
        f[nama] = r
        print(f"  {nama:<36}{r.tempo:>9.2f}{r.skor_tempo:>7.2f}{r.jeda_dinilai:>10.2f}{r.skor_jeda:>6.2f}"
              f"{r.skor_pengisi:>8.2f}{r.skor_lengkap:>8.2f}{r.skor:>7.2f}")

    # ---------------- VALIDASI ----------------
    print("\nVALIDASI: data bermasalah tidak boleh membuat program berhenti")
    print(f"  {'kasus':<40}{'valid':>6}{'hook':>7}{'flow':>7}   masalah pertama")
    wajar = _calon_dari_kata([Word("kata", 0.0, 0.5), Word("lagi.", 0.45, 1.0)])
    tol = TOLERANSI_TUMPANG_TINDIH
    nama_batas = f"Tumpang tindih {tol:g} dtk (tepat batas)"
    nama_lewat = f"Tumpang tindih {tol + 0.1:g} dtk (melebihi)"
    batas = _calon_dari_kata([Word("kata", 10.0, 11.0), Word("lagi.", round(11.0 - tol, 6), 12.0)])
    lewat = _calon_dari_kata([Word("kata", 10.0, 11.0), Word("lagi.", round(11.0 - tol - 0.1, 6), 12.0)])
    kasus_valid = [
        ("Calon tanpa kalimat", Candidate([])),
        ("Kalimat tanpa kata", Candidate([Sentence([])])),
        ("Durasi nol", _calon_dari_kata([Word("Halo.", 5.0, 5.0)])),
        ("Timestamp kosong (None)", _calon_dari_kata([Word("Halo.", None, None)])),
        ("Timestamp NaN", _calon_dari_kata([Word("Halo.", float("nan"), 1.0)])),
        ("Timestamp negatif", _calon_dari_kata([Word("Halo.", -1.0, 0.5)])),
        ("Berakhir sebelum mulai", _calon_dari_kata([Word("Halo.", 2.0, 1.0)])),
        ("Kata tidak berurutan", _calon_dari_kata([Word("a", 5.0, 5.4), Word("b.", 1.0, 1.4)])),
        ("Tumpang tindih kecil (wajar)", wajar),
        (nama_batas, batas),
        (nama_lewat, lewat),
    ]
    v = {}
    for nama, calon in kasus_valid:
        rh, rf = hook_detail(calon), flow_detail(calon)
        v[nama] = (rh, rf)
        pertama = rh.masalah[0] if rh.masalah else "-"
        print(f"  {nama:<40}{('ya' if rh.valid else 'TIDAK'):>6}{rh.skor:>7.2f}{rf.skor:>7.2f}   {pertama}")

    # ---------------- VALUE ----------------
    print("\nVALUE: kekayaan istilah (TF-IDF per kalimat), dinormalisasi antar calon")
    korpus = _rangkai_kalimat(_KORPUS_DEMO)
    model = build_idf(korpus)
    print(f"  korpus demo: {model.jumlah_kalimat} kalimat, IDF memadai: {'ya' if model.memadai else 'TIDAK'}")
    kasus_value = [
        ("Istilah beragam dan khas", Candidate([korpus[0], korpus[9]])),
        ("Kata umum berulang", Candidate([korpus[10], korpus[11]])),
        ("5 kalimat (pola A)", Candidate(_rangkai_kalimat(_KORPUS_DEMO[:5]))),
        ("20 kalimat (pola A diulang 4x)", Candidate(_rangkai_kalimat(_KORPUS_DEMO[:5] * 4))),
        ("Calon tanpa kalimat", Candidate([])),
    ]
    rv = dict(zip([n for n, _ in kasus_value], value_scores([c for _, c in kasus_value], model)))
    print(f"  {'kasus':<34}{'valid':>6}{'mentah':>9}{'skor':>7}   istilah teratas")
    for nama, r in rv.items():
        print(f"  {nama:<34}{('ya' if r.valid else 'TIDAK'):>6}{r.nilai_mentah:>9.3f}{r.skor:>7.2f}   "
              f"{', '.join(r.istilah_teratas) if r.valid else (r.masalah[0] if r.masalah else '-')}")
    rv_kecil = value_scores([kasus_value[0][1]], build_idf(korpus[:3]))[0]
    print(f"  Korpus hanya 3 kalimat -> valid={rv_kecil.valid}, skor={rv_kecil.skor:.2f}: {rv_kecil.masalah[0]}")

    # ---------------- TREND ----------------
    print("\nTREND: energi suara relatif video (70%) + penanda emosi (30%)")
    biasa50 = " ".join(["kata"] * 49 + ["kata."])
    emosi50 = " ".join(["Wow!", "Ini", "luar", "biasa,", "gila!", "keren!"] + ["kata"] * 43 + ["kata."])
    energi = EnergyProfile(step=1.0, values=[3.0 if 40 <= i < 60 else 1.0 for i in range(100)])
    kasus_trend = [
        ("Energi rendah (0-20 dtk)", _calon_waktu(biasa50, 0.0)),
        ("Energi tinggi (40-60 dtk)", _calon_waktu(biasa50, 40.0)),
        ("Energi rendah + penanda emosi", _calon_waktu(emosi50, 20.0)),
        ("Di luar cakupan profil (150 dtk)", _calon_waktu(biasa50, 150.0)),
    ]
    rt = dict(zip([n for n, _ in kasus_trend], trend_scores([c for _, c in kasus_trend], energi)))
    print(f"  {'kasus':<34}{'valid':>6}{'rasio':>7}{'energi':>8}{'penanda':>9}{'p.skor':>8}{'TOTAL':>7}")
    for nama, r in rt.items():
        print(f"  {nama:<34}{('ya' if r.valid else 'TIDAK'):>6}{r.rasio_energi:>7.2f}{r.skor_energi:>8.2f}"
              f"{r.jumlah_penanda:>9d}{r.skor_penanda:>8.2f}{r.skor:>7.2f}")
    tanpa_energi = trend_scores([c for _, c in kasus_trend[1:3]], None)
    print("  Tanpa profil energi (hanya penanda): "
          + ", ".join(f"skor {r.skor:.2f} (energi_tersedia={r.energi_tersedia})" for r in tanpa_energi))
    rusak = trend_scores([c for _, c in kasus_trend[:2]], EnergyProfile(step=1.0, values=[1.0, float("nan")]))
    print(f"  Profil energi rusak (NaN): valid={[r.valid for r in rusak]}, skor={[r.skor for r in rusak]}")

    # ---------------- SKOR AKHIR ----------------
    print("\nSKOR AKHIR 0-100: 0,30 Hook + 0,25 Flow + 0,25 Value + 0,20 Trend")
    kuat = Candidate(_rangkai_kalimat([
        "Tahukah kamu 3 rahasia fotosintesis yang luar biasa?",
        "Astronomi mempelajari galaksi, bintang, dan nebula di langit malam!"], mulai=40.0))
    datar = Candidate(_rangkai_kalimat([
        "Kita dan yang itu kita dan yang itu.",
        "Kita dan yang itu kita dan yang itu lagi."], mulai=0.0))
    kasus_akhir = [("Calon kuat (hook + energi tinggi)", kuat), ("Calon datar (energi rendah)", datar),
                   ("Calon tanpa kalimat", Candidate([])), ("Di luar cakupan profil (150 dtk)", _calon_waktu(biasa50, 150.0))]
    hp = nilai_calon([c for _, c in kasus_akhir], model, energi)
    nama_akhir = [n for n, _ in kasus_akhir]
    print(f"  {'kasus':<36}{'hook':>6}{'flow':>6}{'value':>7}{'trend':>7}{'SKOR':>7}  nilai")
    for i, s in zip(hp.indeks_dinilai, hp.dinilai):
        print(f"  {nama_akhir[i]:<36}{s.hook:>6.2f}{s.flow:>6.2f}{s.value:>7.2f}{s.trend:>7.2f}{s.score:>7.1f}  {nilai_huruf(s.score)}")
    for i, alasan in hp.ditolak:
        print(f"  {nama_akhir[i]:<36}DIBUANG: {alasan[0]}")
    kecil = nilai_calon([kuat, datar], build_idf(korpus[:3]), energi)
    print(f"  Korpus hanya 3 kalimat -> dinilai={len(kecil.dinilai)}, dibuang={len(kecil.ditolak)}")

    # ---------------- RINGKASAN ----------------
    def cek(keterangan: str, kondisi: bool) -> None:
        nonlocal ok_semua
        ok_semua &= kondisi
        print(f"  {keterangan:<70} {'ya' if kondisi else 'TIDAK'}")

    norm = f["Normal (akhir titik)"].skor
    print("\nRINGKASAN PEMERIKSAAN")
    cek("1. Hook kuat > cukup menarik > datar",
        h["Pembukaan kuat"].skor > h["Cukup menarik"].skor > h["Datar"].skor)
    cek("2. Tempo normal > terlalu cepat dan terlalu lambat",
        norm > f["Tempo terlalu cepat (6,5)"].skor and norm > f["Tempo terlalu lambat (0,6)"].skor)
    cek("3. Jeda panjang menurunkan skor Flow (normal > satu > tiga jeda)",
        norm > f["Satu jeda panjang (3 detik)"].skor > f["Tiga jeda panjang (3 detik)"].skor)
    cek("4. Kata pengisi menurunkan skor Flow",
        norm > f["Banyak kata pengisi (5 'eh')"].skor)
    cek("5. Akhir tanpa tanda baca mendapat penalti",
        norm > f["Akhir tanpa tanda baca"].skor)
    semua_skor = [x.skor for x in h.values()] + [x.skor for x in f.values()]
    semua_skor += [s.skor for pasangan in v.values() for s in pasangan]
    cek("6. Semua skor berada di antara 0 dan 1", all(0.0 <= s <= 1.0 for s in semua_skor))
    tidak_valid = [n for n in v if n not in ("Tumpang tindih kecil (wajar)", nama_batas)]
    cek("7. Data tidak valid: tidak crash, skor 0, ditandai tidak valid",
        all((not v[n][0].valid) and v[n][0].skor == 0.0 and v[n][1].skor == 0.0 for n in tidak_valid))
    cek("8. Tumpang tindih kecil dianggap wajar (valid, tanpa penalti jeda)",
        v["Tumpang tindih kecil (wajar)"][0].valid and v["Tumpang tindih kecil (wajar)"][1].jeda_dinilai == 0.0)
    cek("9. Jeda di bawah 1,0 detik tidak dihukum",
        f["Jeda 0,8 detik (di bawah batas)"].skor_jeda == 1.0)
    cek("10. Jumlah bobot Hook = 1 dan bobot Flow = 1",
        abs(sum(POIN_HOOK.values()) - 1.0) < 1e-9 and abs(sum(BOBOT_FLOW.values()) - 1.0) < 1e-9)
    cek("11. Tumpang tindih tepat di batas diterima, di atas batas ditolak",
        v[nama_batas][0].valid and not v[nama_lewat][0].valid)
    cek("12. Titik tiga/elipsis dianggap belum lengkap",
        f["Akhir titik tiga (...)"].skor_lengkap == SKOR_TANPA_TANDA_AKHIR
        and f["Akhir elipsis tunggal (…)"].skor_lengkap == SKOR_TANPA_TANDA_AKHIR)
    cek("13. Tanda tanya tetap dianggap lengkap",
        f["Akhir tanda tanya tetap lengkap"].skor_lengkap == 1.0)
    cek("14. Value: istilah beragam dan khas > kata umum berulang",
        rv["Istilah beragam dan khas"].skor > rv["Kata umum berulang"].skor)
    cek("15. Value tidak bias panjang (5 vs 20 kalimat, pola sama: nilai mentah sama)",
        abs(rv["5 kalimat (pola A)"].nilai_mentah - rv["20 kalimat (pola A diulang 4x)"].nilai_mentah) < 1e-9)
    cek("16. Value: data tidak valid dan korpus kecil -> skor 0, valid=False",
        (not rv["Calon tanpa kalimat"].valid) and rv["Calon tanpa kalimat"].skor == 0.0
        and (not rv_kecil.valid) and rv_kecil.skor == 0.0)
    cek("17. Trend: energi tinggi > energi rendah (penanda sama)",
        rt["Energi tinggi (40-60 dtk)"].skor > rt["Energi rendah (0-20 dtk)"].skor)
    cek("18. Trend: penanda emosi menaikkan skor (energi sama)",
        rt["Energi rendah + penanda emosi"].skor > rt["Energi rendah (0-20 dtk)"].skor)
    cek("19. Trend tanpa profil energi tetap jalan dan ditandai energi_tersedia=False",
        all(r.valid and (not r.energi_tersedia) and 0.0 <= r.skor <= 1.0 for r in tanpa_energi))
    cek("20. Trend: profil energi rusak -> semua tidak valid, skor 0, tidak crash",
        all((not r.valid) and r.skor == 0.0 for r in rusak))
    semua_vt = [r.skor for r in rv.values()] + [r.skor for r in rt.values()] + [r.skor for r in tanpa_energi]
    cek("21. Di luar cakupan ditolak; bobot Trend = 1; semua skor 0..1",
        (not rt["Di luar cakupan profil (150 dtk)"].valid) and abs(sum(BOBOT_TREND.values()) - 1.0) < 1e-9
        and all(0.0 <= s <= 1.0 for s in semua_vt))
    sk = {nama_akhir[i]: s for i, s in zip(hp.indeks_dinilai, hp.dinilai)}
    cek("22. Jumlah bobot skor akhir = 1", abs(sum(BOBOT_AKHIR.values()) - 1.0) < 1e-9)
    cek("23. Calon kuat bernilai lebih tinggi daripada calon datar",
        sk["Calon kuat (hook + energi tinggi)"].score > sk["Calon datar (energi rendah)"].score)
    cek("24. Calon tidak valid dan di luar cakupan dibuang (tercatat), tidak diberi skor",
        sorted(i for i, _ in hp.ditolak) == [2, 3] and len(hp.dinilai) == 2)
    cek("25. Semua skor akhir 0-100 dan sama dengan 100 x jumlah bobot x komponen",
        all(0.0 <= s.score <= 100.0 and abs(s.score - 100 * (BOBOT_AKHIR["hook"] * s.hook + BOBOT_AKHIR["flow"] * s.flow
            + BOBOT_AKHIR["value"] * s.value + BOBOT_AKHIR["trend"] * s.trend)) < 1e-9 for s in hp.dinilai))
    cek("26. Huruf nilai (100=A, 65=B, 0=D); korpus kecil dan masukan kosong tidak crash",
        nilai_huruf(100.0) == "A" and nilai_huruf(65.0) == "B" and nilai_huruf(0.0) == "D"
        and len(kecil.dinilai) == 0 and len(kecil.ditolak) == 2 and nilai_calon([], model).dinilai == [])
    return 0 if ok_semua else 1


if __name__ == "__main__":
    sys.exit(_demo())
