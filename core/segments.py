"""segments.py: memecah kata menjadi kalimat, lalu menyusun calon clip.

Dua tugas di file ini:
  1. split_sentences : daftar kata  -> daftar kalimat
  2. build_candidates: daftar kalimat -> daftar calon clip (20-60 detik)

Cara mencoba tanpa video (data contoh bawaan):
    python -m core.segments
"""
from .models import TANDA_AKHIR, Candidate, Sentence, Word


def split_sentences(words: list[Word], jeda_maks: float = 0.8) -> list[Sentence]:
    """Memecah kata menjadi kalimat.

    Sebuah kalimat berakhir bila:
      - kata terakhirnya ditutup tanda baca akhir (. ? ! …), atau
      - ada jeda lebih dari `jeda_maks` detik sebelum kata berikutnya.
    Aturan jeda penting karena transkripsi tidak selalu memberi tanda baca.
    """
    kalimat: list[Sentence] = []
    sedang_disusun: list[Word] = []

    for i, kata in enumerate(words):
        sedang_disusun.append(kata)
        kata_berikut = words[i + 1] if i + 1 < len(words) else None

        berakhir_tanda_baca = kata.text.rstrip().endswith(TANDA_AKHIR)
        jeda_panjang = kata_berikut is not None and (kata_berikut.start - kata.end) > jeda_maks
        kata_terakhir = kata_berikut is None

        if berakhir_tanda_baca or jeda_panjang or kata_terakhir:
            kalimat.append(Sentence(sedang_disusun))
            sedang_disusun = []

    return kalimat


def build_candidates(
    sentences: list[Sentence],
    min_sec: float = 20,
    max_sec: float = 60,
    per_start: int = 3,
) -> list[Candidate]:
    """Menyusun calon clip dari kalimat-kalimat berurutan.

    Untuk tiap kalimat yang dijadikan awal, kalimat berikutnya ditambahkan satu
    per satu. Begitu durasi mencapai `min_sec` terbentuk satu calon clip. Ini
    diulang sampai `per_start` calon, atau sampai durasi melewati `max_sec`.

    Awal dan akhir calon clip selalu batas kalimat, jadi clip tidak terpotong
    di tengah kalimat.
    """
    if min_sec > max_sec:
        raise ValueError("min_sec tidak boleh lebih besar dari max_sec")

    hasil: list[Candidate] = []
    for awal in range(len(sentences)):
        terambil = 0
        for akhir in range(awal, len(sentences)):
            durasi = sentences[akhir].end - sentences[awal].start
            if durasi > max_sec:
                break
            if durasi >= min_sec:
                hasil.append(Candidate(sentences[awal:akhir + 1]))
                terambil += 1
                if terambil >= per_start:
                    break
    return hasil


# --------------------------------------------------------------------------
# Demo: dijalankan dengan  python -m core.segments
# --------------------------------------------------------------------------
def _kata_contoh(n_kalimat: int = 30, kata_per_kalimat: int = 8,
                 kecepatan: float = 2.5, jeda: float = 0.3) -> list[Word]:
    """Membuat transkrip tiruan: kalimat-kalimat sama panjang dengan jeda kecil."""
    langkah = 1.0 / kecepatan
    waktu = 0.0
    kata_kata: list[Word] = []
    for k in range(n_kalimat):
        for j in range(kata_per_kalimat):
            teks = f"kata{k}_{j}" if j < kata_per_kalimat - 1 else f"akhir{k}."
            kata_kata.append(Word(teks, round(waktu, 3), round(waktu + langkah * 0.9, 3)))
            waktu += langkah
        waktu += jeda
    return kata_kata


if __name__ == "__main__":
    kata_kata = _kata_contoh()
    kalimat = split_sentences(kata_kata)
    calon = build_candidates(kalimat)

    awal_kalimat = {s.start for s in kalimat}
    akhir_kalimat = {s.end for s in kalimat}
    durasi_ok = all(20 <= c.duration <= 60 for c in calon)
    batas_ok = all(c.start in awal_kalimat and c.end in akhir_kalimat for c in calon)

    print(f"Jumlah kata        : {len(kata_kata)}")
    print(f"Jumlah kalimat     : {len(kalimat)}")
    print(f"Jumlah calon clip  : {len(calon)}")
    print("Tiga calon pertama :")
    for c in calon[:3]:
        print(f"  {c.start:6.1f} s - {c.end:6.1f} s  (durasi {c.duration:4.1f} s)")
    print(f"Semua berdurasi 20-60 detik        : {'ya' if durasi_ok else 'TIDAK'}")
    print(f"Semua dipotong di batas kalimat    : {'ya' if batas_ok else 'TIDAK'}")
