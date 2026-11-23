"""Memotong jeda (diam) dari klip: mencari bagian tanpa kata, lalu menggeser waktu kata dan subtitle setelah bagian itu dibuang.

Semua waktu dalam detik pada video SUMBER. Jeda dicari dari jarak antar kata di transkrip (tanpa analisis suara)."""
import math

AMBANG_MIN, AMBANG_MAKS, AMBANG_BAWAAN = 0.3, 3.0, 0.6
SISA_JEDA = 0.2        # jeda yang tetap disisakan di tiap lubang supaya ucapan tidak terdengar menempel


def hitung_buang(kata, mulai: float, akhir: float, ambang: float = AMBANG_BAWAAN, sisa: float = SISA_JEDA) -> list:
    """Daftar [(a, b)] bagian yang dibuang dari klip [mulai, akhir].

    Lubang = jarak antar dua kata (atau dari awal klip ke kata pertama, atau dari kata terakhir ke akhir klip) yang >= ambang.
    Dari tiap lubang disisakan `sisa` detik (setengah di tiap sisi; di awal/akhir klip disisakan setengahnya saja)."""
    ambang = max(float(ambang), sisa + 0.05)
    dalam = sorted((k for k in (kata or []) if k["e"] > mulai and k["s"] < akhir), key=lambda k: k["s"])
    if not dalam:
        return []
    hasil = []

    def lubang(a, b, sisi_awal, sisi_akhir):
        if b - a >= ambang:
            x, y = a + sisi_awal, b - sisi_akhir
            if y - x > 0.02:
                hasil.append((round(max(x, mulai), 3), round(min(y, akhir), 3)))

    lubang(mulai, dalam[0]["s"], 0.0, sisa / 2)
    for i in range(1, len(dalam)):
        lubang(dalam[i - 1]["e"], dalam[i]["s"], sisa / 2, sisa / 2)
    lubang(dalam[-1]["e"], akhir, sisa / 2, 0.0)
    return hasil


def selaraskan(buang, fps: float) -> list:
    """Menggeser tiap selang ke batas frame: frame k dibuang bila a <= k/fps < b  <=>  ceil(a*fps) <= k < ceil(b*fps).
    Dengan begitu suara (dibuang di [a', b')) dan gambar selalu sama panjang. Selang yang jadi kosong dibuang."""
    hasil = []
    for a, b in buang:
        ka, kb = math.ceil(a * fps - 1e-9), math.ceil(b * fps - 1e-9)
        if kb > ka:
            if hasil and ka <= hasil[-1][1]:
                hasil[-1] = (hasil[-1][0], max(hasil[-1][1], kb))
            else:
                hasil.append((ka, kb))
    return [(ka / fps, kb / fps) for ka, kb in hasil]


def total_buang(buang) -> float:
    return sum(b - a for a, b in buang)


def geser_waktu(t: float, buang) -> float:
    """Waktu t setelah semua selang `buang` (urut, tidak tumpang tindih) dibuang; t di dalam lubang jatuh ke awal lubang."""
    geser = 0.0
    for a, b in buang:
        if t >= b:
            geser += b - a
        elif t > a:
            geser += t - a
            break
        else:
            break
    return t - geser


def petakan_kata(kata, buang) -> list:
    """Kata dengan waktu yang sudah digeser. Menerima kamus {"w","s","e"} (kata.json) maupun core.models.Word.
    Kata yang seluruhnya jatuh di bagian terbuang dilewati."""
    from dataclasses import replace
    hasil = []
    for k in kata or []:
        if isinstance(k, dict):
            s, e = geser_waktu(k["s"], buang), geser_waktu(k["e"], buang)
            if e - s > 1e-6:
                hasil.append({**k, "s": s, "e": e})
        else:
            s, e = geser_waktu(k.start, buang), geser_waktu(k.end, buang)
            if e - s > 1e-6:
                hasil.append(replace(k, start=s, end=e))
    return hasil


def filter_suara(buang, t_awal: float) -> str | None:
    """Ekspresi aselect FFmpeg yang membuang selang (waktu relatif terhadap awal masukan = t_awal)."""
    if not buang:
        return None
    syarat = "+".join(f"between(t,{a - t_awal:.6f},{b - t_awal:.6f})" for a, b in buang)
    return f"aselect='not({syarat})',asetpts=N/SR/TB"


def gabung(*daftar, mulai: float = 0.0, akhir: float = math.inf) -> list:
    """Menyatukan beberapa daftar selang (mis. jeda otomatis + potongan manual) jadi satu daftar urut tanpa tumpang tindih,
    dipotong ke rentang [mulai, akhir]."""
    semua = sorted((max(float(a), mulai), min(float(b), akhir)) for d in daftar for a, b in d)
    hasil = []
    for a, b in semua:
        if b - a <= 1e-9:
            continue
        if hasil and a <= hasil[-1][1]:
            hasil[-1] = (hasil[-1][0], max(hasil[-1][1], b))
        else:
            hasil.append((a, b))
    return hasil
