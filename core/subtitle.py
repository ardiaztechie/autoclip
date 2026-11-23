"""subtitle.py: membuat subtitle (format ASS) dari kata bertimestamp untuk satu klip.

Kata (core.models.Word) yang jatuh di dalam rentang klip dikelompokkan menjadi baris pendek,
lalu ditulis sebagai berkas ASS yang dibakar ke video oleh render.py (filter `ass` FFmpeg/libass).
Waktu subtitle dihitung relatif terhadap awal klip.

Teks subtitle persis seperti keluaran Whisper. Kesalahan dengar Whisper ikut terbawa; tidak ada
koreksi otomatis di sini.

Seluruh angka di bagian "Nilai awal" adalah nilai AWAL YANG BELUM DIUJI (eksperimental).
Font diambil dari sistem (bawaan Arial di Windows). Ganti lewat parameter `font`.
"""
import math

# --- Nilai awal (eksperimental) ---------------------------------------------
MAKS_KATA = 5                 # kata paling banyak per baris tampil
MAKS_HURUF = 24               # huruf paling banyak per baris tampil (termasuk spasi)
JEDA_PEMISAH = 0.6            # detik; jeda antar kata sebesar ini memulai baris baru
TAHAN_AKHIR = 0.3             # detik; baris terakhir sebelum jeda dibiarkan tampil sedikit lebih lama
UKURAN_FONT = 0.058           # tinggi font = 5,8% lebar keluaran
MARGIN_BAWAH = 0.14           # jarak dari tepi bawah = 14% tinggi keluaran
TANDA_PEMISAH = (".", "?", "!", "…", ",")
FONT_BAWAAN = "Arial"

# --- Gaya tampilan (pilihan di editor) ----------------------------------------
# Warna ASS berformat &HAABBGGRR (urutan biru-hijau-merah, bukan RGB). Semua nilai ini masih tebakan visual.
GAYA = {
    # nama: (warna teks, warna garis/kotak, tebal, kotak?, warna sorot atau None, tebal garis relatif, bayangan)
    "klasik": ("&H00FFFFFF", "&H00000000", -1, False, None, 1.0, 0),
    "kuning": ("&H0000FFFF", "&H00000000", -1, False, None, 1.3, 0),
    "kotak": ("&H00FFFFFF", "&H40000000", -1, True, None, 1.0, 0),
    "sorot": ("&H00FFFFFF", "&H00000000", -1, False, "&H0000D7FF", 1.0, 0),
    "minimal": ("&H00FFFFFF", "&H00000000", 0, False, None, 0.5, 1),
}
GAYA_BAWAAN = "klasik"
# Animasi saat baris subtitle muncul: awalan tag ASS di depan teks baris. "muncul" = membesar sebentar (pop), "pudar" = fade-in.
ANIMASI = {"tanpa": "", "muncul": "{\\fscx70\\fscy70\\t(0,130,\\fscx100\\fscy100)}", "pudar": "{\\fad(140,0)}"}
POSISI = ("bawah", "tengah", "atas")
UKURAN = {"kecil": 0.8, "sedang": 1.0, "besar": 1.25}
MARGIN_ATAS = 0.10            # jarak dari tepi atas = 10% tinggi keluaran (posisi "atas")


def _valid(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def kata_dalam_klip(kata, mulai: float, akhir: float) -> list:
    """Kata yang seluruhnya berada di dalam [mulai, akhir]. Data rusak dilewati."""
    hasil = []
    for k in kata or []:
        teks = getattr(k, "text", None)
        s, e = getattr(k, "start", None), getattr(k, "end", None)
        if not isinstance(teks, str) or not teks.strip() or not (_valid(s) and _valid(e)) or e < s:
            continue
        if s >= mulai - 1e-9 and e <= akhir + 1e-9:
            hasil.append(k)
    return hasil


def kelompokkan(kata, *, maks_kata: int = MAKS_KATA, maks_huruf: int = MAKS_HURUF,
                jeda: float = JEDA_PEMISAH) -> list:
    """Membagi kata menjadi baris tampil. Setiap baris = daftar kata berurutan.

    Baris baru dimulai bila: sudah akhir kalimat/koma, jumlah kata atau huruf akan terlampaui,
    atau ada jeda panjang antar kata. Satu kata yang lebih panjang dari batas tetap menjadi barisnya sendiri.
    """
    if maks_kata < 1 or maks_huruf < 1 or jeda < 0:
        raise ValueError("maks_kata, maks_huruf harus >= 1 dan jeda tidak boleh negatif")
    baris, sekarang = [], []
    for k in kata:
        if sekarang:
            panjang = len(" ".join(w.text for w in sekarang + [k]))
            if (len(sekarang) >= maks_kata or panjang > maks_huruf or k.start - sekarang[-1].end >= jeda):
                baris.append(sekarang)
                sekarang = []
        sekarang.append(k)
        if k.text.rstrip().endswith(TANDA_PEMISAH):
            baris.append(sekarang)
            sekarang = []
    if sekarang:
        baris.append(sekarang)
    return baris


def _waktu_ass(detik: float) -> str:
    cs = int(round(max(detik, 0.0) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _aman(teks: str) -> str:
    """Menghindari karakter yang bermakna khusus di ASS."""
    return teks.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def buat_ass(kata, mulai: float, akhir: float, lebar: int, tinggi: int, *, font: str = FONT_BAWAAN,
             gaya: str = GAYA_BAWAAN, posisi: str = "bawah", ukuran: str = "sedang", animasi: str = "tanpa") -> str:
    """Isi berkas ASS untuk klip [mulai, akhir] (detik pada video asal), berukuran keluaran lebar x tinggi.

    gaya: salah satu kunci GAYA; posisi: bawah/tengah/atas; ukuran: kecil/sedang/besar. Bawaan (klasik, bawah, sedang)
    menghasilkan keluaran yang sama dengan sebelum ada pilihan gaya. Gaya "sorot" mewarnai kata yang sedang diucapkan.
    Mengembalikan teks ASS lengkap; bila tidak ada kata di rentang itu, tetap ASS valid tanpa baris dialog.
    """
    if not (_valid(mulai) and _valid(akhir)) or mulai < 0 or akhir <= mulai:
        raise ValueError("mulai harus >= 0 dan akhir harus lebih besar dari mulai")
    if not (isinstance(lebar, int) and isinstance(tinggi, int)) or lebar < 2 or tinggi < 2:
        raise ValueError("lebar dan tinggi harus bilangan bulat >= 2")
    if gaya not in GAYA:
        raise ValueError(f"gaya tidak dikenal: {gaya!r}")
    if posisi not in POSISI:
        raise ValueError(f"posisi tidak dikenal: {posisi!r}")
    if ukuran not in UKURAN:
        raise ValueError(f"ukuran tidak dikenal: {ukuran!r}")
    if animasi not in ANIMASI:
        raise ValueError(f"animasi tidak dikenal: {animasi!r}")
    awalan = ANIMASI[animasi]
    warna, garis, tebal, kotak, sorot, tebal_garis, bayangan = GAYA[gaya]
    font = _aman(font or FONT_BAWAAN).replace(",", " ")
    ukuran_px = max(8, int(round(lebar * UKURAN_FONT * UKURAN[ukuran])))
    if posisi == "bawah":
        perataan, margin_v = 2, int(round(tinggi * MARGIN_BAWAH))
    elif posisi == "atas":
        perataan, margin_v = 8, int(round(tinggi * MARGIN_ATAS))
    else:
        perataan, margin_v = 5, 0
    margin_h = int(round(lebar * 0.05))
    if kotak:                                  # BorderStyle 3: garis tepi menjadi kotak di belakang teks
        gaya_garis, tebal_px = 3, max(4, ukuran_px // 5)
    else:
        gaya_garis, tebal_px = 1, max(1 if tebal_garis < 1 else 2, int(round(ukuran_px // 14 * tebal_garis)))
    kepala = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {lebar}\nPlayResY: {tinggi}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Utama,{font},{ukuran_px},{warna},{warna},{garis},&H64000000,{tebal},0,0,0,100,100,0,0,{gaya_garis},"
        f"{tebal_px},{bayangan},{perataan},{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    baris = kelompokkan(kata_dalam_klip(kata, mulai, akhir))
    isi = []
    for i, b in enumerate(baris):
        awal = b[0].start
        if i + 1 < len(baris):
            berikut = baris[i + 1][0].start
            selesai = min(b[-1].end + TAHAN_AKHIR, berikut) if berikut - b[-1].end > 0 else b[-1].end
            selesai = max(selesai, b[-1].end)
        else:
            selesai = min(b[-1].end + TAHAN_AKHIR, akhir)
        if sorot is None:
            teks = _aman(" ".join(w.text.strip() for w in b))
            isi.append(f"Dialogue: 0,{_waktu_ass(awal - mulai)},{_waktu_ass(selesai - mulai)},Utama,,0,0,0,,{awalan}{teks}")
            continue
        # Sorot kata: satu peristiwa per kata; kata yang sedang diucapkan diberi warna sorot, sisanya warna biasa.
        teks_kata = [_aman(w.text.strip()) for w in b]
        for j, w in enumerate(b):
            dari = awal if j == 0 else w.start
            sampai = selesai if j == len(b) - 1 else b[j + 1].start
            if sampai <= dari:
                continue
            # Kembali ke warna biasa dengan \1c (bukan \r), supaya animasi awal baris tidak ikut terhapus.
            bagian = [f"{{\\1c{sorot}&}}{t}{{\\1c{warna}&}}" if n == j else t for n, t in enumerate(teks_kata)]
            depan = awalan if j == 0 else ""                      # animasi hanya saat baris muncul, bukan tiap kata
            isi.append(f"Dialogue: 0,{_waktu_ass(dari - mulai)},{_waktu_ass(sampai - mulai)},Utama,,0,0,0,,{depan}{' '.join(bagian)}")
    return kepala + "\n".join(isi) + ("\n" if isi else "")
