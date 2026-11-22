"""metadata.py: judul, caption, dan hashtag untuk tiap klip (versi ATURAN: tanpa internet, tanpa LLM).

Semua berasal dari teks klip itu sendiri, dengan aturan sederhana:
  - JUDUL   : kalimat pertama klip, dipotong paling banyak MAKS_KATA_JUDUL kata.
  - HASHTAG : istilah paling khas di klip (memakai model IDF yang sama dengan komponen Value),
              tanpa kata umum dan kata pengisi.
  - CAPTION : kalimat-kalimat awal klip (paling banyak MAKS_HURUF_CAPTION huruf) + hashtag.

Batas jujur: ini bukan "pemahaman isi". Judul bisa kurang menarik atau terpotong di tengah gagasan,
dan hashtag hanya kata yang sering dan khas, bukan topik. Angka dan daftar kata umum di bawah adalah
EKSPERIMENTAL (tanpa dasar riset). Versi LLM (bila nanti dipakai) akan menggantikan fungsi buat_metadata
dan versi ini tetap menjadi cadangan yang selalu jalan.

Cara pakai (dari folder proyek, .venv aktif):
    python -m core.metadata storage/hasil/video/kata.json storage/hasil/video/klip.json --simpan storage/hasil/video/metadata.json
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from .scoring import KATA_PENGISI, _bersihkan_kata, _istilah, build_idf
from .segments import split_sentences
from .transcribe import dari_json

# --- Parameter eksperimental (belum punya dasar riset) -----------------------------------
MAKS_KATA_JUDUL = 12
MIN_KATA_POTONG_KOMA = 4        # potong di koma hanya bila judulnya masih sedikitnya sepanjang ini
MAKS_HURUF_CAPTION = 160
JUMLAH_HASHTAG = 5
MAKS_HURUF_HASHTAG = 20
TOLERANSI_WAKTU = 0.05          # detik, untuk mencocokkan kata dengan rentang klip
KATA_UMUM = frozenset("""
yang dan dari ini itu dengan untuk pada adalah karena jadi kalau kalo tapi tetapi atau bukan ada lebih
sudah udah akan juga saya aku kamu kita kami mereka dia gue gua gak nggak tidak banget sama terus lalu
sebagai dalam oleh bisa apa siapa kapan mana seperti sampai saat ketika kemudian maka agar supaya hanya
masih sangat lagi lah kan deh sih dong nih tuh gitu gini begitu begini sebuah para setiap semua beberapa
harus perlu mau punya dll kenapa mengapa bagaimana ternyata penting
pun selalu semakin bilang kalian anda sekali sekarang dulu nanti cuma kayak bahwa yaitu yakni meskipun
walaupun sebelum sesudah setelah tanpa antara hingga bila jika apabila selama sambil padahal memang justru
malah bahkan sering kadang belum mungkin ingin dapat boleh melakukan membuat dilakukan banyak sedikit
""".split())
_HANYA_HURUF = re.compile(r"[^\W\d_]+", re.UNICODE)


# ===========================================================================
# ALAT BANTU
# ===========================================================================
def kata_dalam_rentang(kata, mulai: float, akhir: float) -> list:
    """Kata yang seluruhnya berada di dalam [mulai, akhir] (dengan toleransi kecil)."""
    return [k for k in kata if k.start >= mulai - TOLERANSI_WAKTU and k.end <= akhir + TOLERANSI_WAKTU]


def _rapikan(teks: str) -> str:
    return re.sub(r"\s+", " ", teks).strip()


def _potong_kata(teks: str, maks_kata: int) -> tuple:
    """(teks terpotong, apakah terpotong)."""
    kata = teks.split()
    if len(kata) <= maks_kata:
        return teks, False
    return " ".join(kata[:maks_kata]), True


def _huruf_besar_awal(teks: str) -> str:
    return teks[:1].upper() + teks[1:] if teks else teks


# ===========================================================================
# JUDUL, HASHTAG, CAPTION
# ===========================================================================
def buat_judul(kalimat: list, maks_kata: int = MAKS_KATA_JUDUL) -> str:
    """Judul dari kalimat pertama. kalimat: list teks. Kosong bila tidak ada teks."""
    pertama = next((_rapikan(k) for k in kalimat if _rapikan(k)), "")
    if not pertama:
        return ""
    teks, terpotong = _potong_kata(pertama, maks_kata)
    if terpotong:                           # lebih rapi bila dipotong di koma terakhir yang cukup jauh
        kata = teks.split()
        for i in range(len(kata) - 1, MIN_KATA_POTONG_KOMA - 2, -1):
            if kata[i].endswith(","):
                teks, terpotong = " ".join(kata[:i + 1]), False
                break
    teks = teks.rstrip(" .,;:-…")           # tanda tanya dan seru dipertahankan
    return _huruf_besar_awal(teks) + ("…" if terpotong else "")


def pilih_hashtag(kalimat: list, model, jumlah: int = JUMLAH_HASHTAG) -> list:
    """Istilah paling khas di klip: porsi istilah x IDF, tanpa kata umum dan pengisi."""
    istilah = []
    for t in _istilah(" ".join(kalimat)):
        t = _bersihkan_kata(t)
        if (_HANYA_HURUF.fullmatch(t) and len(t) <= MAKS_HURUF_HASHTAG
                and t not in KATA_UMUM and t not in KATA_PENGISI):
            istilah.append(t)
    if not istilah:
        return []
    total = len(istilah)
    skor = {t: (c / total) * model.bobot(t) for t, c in Counter(istilah).items()}
    urut = sorted(skor.items(), key=lambda x: (-x[1], x[0]))[:max(0, jumlah)]
    return ["#" + t for t, _ in urut]


def buat_caption(kalimat: list, hashtag: list, maks_huruf: int = MAKS_HURUF_CAPTION) -> str:
    """Kalimat-kalimat awal (sampai batas huruf, dipotong di batas kata) lalu hashtag."""
    isi = ""
    for k in kalimat:
        k = _rapikan(k)
        if not k:
            continue
        calon = (isi + " " + k).strip()
        if len(calon) <= maks_huruf:
            isi = calon
            continue
        if not isi:                         # kalimat pertama sendiri terlalu panjang: potong di batas kata
            potong = calon[:maks_huruf].rsplit(" ", 1)[0].rstrip(" .,;:-…")
            isi = (potong or calon[:maks_huruf]) + "…"
        break
    isi = _huruf_besar_awal(isi.rstrip(" ,;:-"))
    tag = " ".join(hashtag)
    return (isi + ("\n\n" if isi and tag else "") + tag).strip()


# ===========================================================================
# SEMUA KLIP
# ===========================================================================
def buat_metadata(kata: list, klip: list, jumlah_hashtag: int = JUMLAH_HASHTAG) -> list:
    """kata: list[Word] seluruh video. klip: list dict dengan 'mulai' dan 'akhir'.
    Mengembalikan list dict {nomor, mulai, akhir, judul, caption, hashtag} (urutan sama dengan klip)."""
    model = build_idf(split_sentences(kata))
    hasil = []
    for i, k in enumerate(klip, 1):
        mulai, akhir = float(k["mulai"]), float(k["akhir"])
        kalimat = [s.text for s in split_sentences(kata_dalam_rentang(kata, mulai, akhir))]
        tag = pilih_hashtag(kalimat, model, jumlah_hashtag)
        hasil.append({"nomor": i, "mulai": mulai, "akhir": akhir, "judul": buat_judul(kalimat),
                      "caption": buat_caption(kalimat, tag), "hashtag": tag})
    return hasil


def _tampil(daftar: list) -> str:
    baris = []
    for m in daftar:
        baris += [f"#{m['nomor']}  {m['mulai']:.1f} - {m['akhir']:.1f} dtk",
                  f"    Judul   : {m['judul'] or '(kosong)'}",
                  f"    Hashtag : {' '.join(m['hashtag']) or '(tidak ada)'}",
                  f"    Caption : {m['caption'].splitlines()[0] if m['caption'] else '(kosong)'}", ""]
    return "\n".join(baris).rstrip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Judul, caption, dan hashtag per klip (versi aturan).")
    ap.add_argument("kata_json", help="berkas kata.json dari core.transcribe")
    ap.add_argument("klip_json", help="berkas klip.json dari core.pipeline --simpan")
    ap.add_argument("--hashtag", type=int, default=JUMLAH_HASHTAG, help=f"jumlah hashtag (bawaan {JUMLAH_HASHTAG})")
    ap.add_argument("--simpan", default=None, help="simpan hasil ke berkas JSON ini")
    arg = ap.parse_args(argv)
    try:
        kata = dari_json(Path(arg.kata_json).read_text(encoding="utf-8"))
        klip = json.loads(Path(arg.klip_json).read_text(encoding="utf-8"))
        if not isinstance(klip, list) or not all(isinstance(k, dict) and {"mulai", "akhir"} <= k.keys() for k in klip):
            raise ValueError("berkas klip harus berupa daftar yang tiap itemnya punya mulai dan akhir")
        hasil = buat_metadata(kata, klip, arg.hashtag)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    print(_tampil(hasil))
    if arg.simpan:
        tujuan = Path(arg.simpan)
        tujuan.parent.mkdir(parents=True, exist_ok=True)
        tujuan.write_text(json.dumps(hasil, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nMetadata disimpan ke: {tujuan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
