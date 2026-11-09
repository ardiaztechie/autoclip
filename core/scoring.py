"""scoring.py: memberi nilai pada calon clip.

Bagian 1 (file ini): skor Hook dan Flow, validasi data, dan rincian per indikator.
Bagian 2 (menyusul) : skor Value dan Trend.
Bagian 3 (menyusul) : penggabungan menjadi skor akhir 0-100.

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
from dataclasses import dataclass

from .models import TANDA_AKHIR, Candidate, Sentence, Word

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
    return 0 if ok_semua else 1


if __name__ == "__main__":
    sys.exit(_demo())
