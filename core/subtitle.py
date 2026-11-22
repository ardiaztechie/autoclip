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


def buat_ass(kata, mulai: float, akhir: float, lebar: int, tinggi: int, *, font: str = FONT_BAWAAN) -> str:
    """Isi berkas ASS untuk klip [mulai, akhir] (detik pada video asal), berukuran keluaran lebar x tinggi.

    Mengembalikan teks ASS lengkap; bila tidak ada kata di rentang itu, tetap ASS valid tanpa baris dialog.
    """
    if not (_valid(mulai) and _valid(akhir)) or mulai < 0 or akhir <= mulai:
        raise ValueError("mulai harus >= 0 dan akhir harus lebih besar dari mulai")
    if not (isinstance(lebar, int) and isinstance(tinggi, int)) or lebar < 2 or tinggi < 2:
        raise ValueError("lebar dan tinggi harus bilangan bulat >= 2")
    font = _aman(font or FONT_BAWAAN).replace(",", " ")
    ukuran = max(8, int(round(lebar * UKURAN_FONT)))
    margin_v = int(round(tinggi * MARGIN_BAWAH))
    margin_h = int(round(lebar * 0.05))
    kepala = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {lebar}\nPlayResY: {tinggi}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Utama,{font},{ukuran},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(2, ukuran // 14)},0,2,{margin_h},{margin_h},{margin_v},1\n\n"
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
        teks = _aman(" ".join(w.text.strip() for w in b))
        isi.append(f"Dialogue: 0,{_waktu_ass(awal - mulai)},{_waktu_ass(selesai - mulai)},Utama,,0,0,0,,{teks}")
    return kepala + "\n".join(isi) + ("\n" if isi else "")
