"""Tes aturan jeda_maks_calon pada core.segments.build_candidates.

Aturan: calon yang memuat jeda antar kalimat LEBIH PANJANG dari jeda_maks_calon
tidak dibuat. None = mati (perilaku lama).
"""
import pytest

from core.models import Word
from core.pipeline import jalankan_rantai, main as pipeline_main
from core.segments import JEDA_MAKS_CALON_BAWAAN, build_candidates, split_sentences

KALIMAT_DTK = 3.0      # tiap kalimat 8 kata, 3 detik
JEDA_ANTAR = 0.3


def _susun(blok):
    """blok = daftar (jumlah_kalimat, jeda_sebelum_blok_dtk). Mengembalikan list[Word]."""
    kata, t = [], 0.0
    for n_kalimat, jeda in blok:
        t += jeda
        for _ in range(n_kalimat):
            for i in range(8):
                awal = t + i * (KALIMAT_DTK / 8)
                akhir = awal + (KALIMAT_DTK / 8) * 0.9
                teks = "kata" + ("." if i == 7 else "")
                kata.append(Word(teks, round(awal, 3), round(akhir, 3)))
            t += KALIMAT_DTK + JEDA_ANTAR
    return kata


def _calon(blok, **kw):
    return build_candidates(split_sentences(_susun(blok)), **kw)


def _melintasi(c, awal, akhir):
    return c.start < awal and c.end > akhir


def _jeda_posisi(blok):
    """Awal dan akhir jeda panjang antara blok pertama dan kedua."""
    kata = _susun(blok)
    n1 = blok[0][0] * 8
    return kata[n1 - 1].end, kata[n1].start


BLOK_JEDA_30 = [(10, 0.0), (10, 30.0)]   # 10 kalimat, jeda 30 dtk, 10 kalimat


def test_nilai_bawaan_adalah_10_detik():
    assert JEDA_MAKS_CALON_BAWAAN == 10.0


def test_calon_tidak_melintasi_jeda_panjang():
    a, b = _jeda_posisi(BLOK_JEDA_30)
    calon = _calon(BLOK_JEDA_30, jeda_maks_calon=10)
    assert calon, "tetap harus ada calon di kedua sisi jeda"
    assert not any(_melintasi(c, a, b) for c in calon)


def test_perilaku_lama_masih_menghasilkan_calon_yang_melintasi():
    """Dengan None aturan mati; ini bukti tes di atas bisa gagal."""
    a, b = _jeda_posisi(BLOK_JEDA_30)
    calon = _calon(BLOK_JEDA_30, jeda_maks_calon=None, per_start=50)
    assert any(_melintasi(c, a, b) for c in calon)


def test_awal_tepat_setelah_jeda_panjang_tetap_dipakai():
    """Kalimat pertama setelah jeda panjang harus bisa menjadi awal calon (jeda ada DI BELAKANGNYA,
    bukan di dalam calon)."""
    kal = split_sentences(_susun(BLOK_JEDA_30))
    awal_setelah_jeda = kal[10].start
    calon = build_candidates(kal, jeda_maks_calon=10)
    assert any(abs(c.start - awal_setelah_jeda) < 1e-9 for c in calon)


def test_calon_sebelum_dan_sesudah_jeda_tetap_dibuat():
    a, b = _jeda_posisi(BLOK_JEDA_30)
    calon = _calon(BLOK_JEDA_30, jeda_maks_calon=10)
    assert any(c.end <= a + 1e-9 for c in calon)
    assert any(c.start >= b - 1e-9 for c in calon)


def test_jeda_tepat_di_batas_masih_boleh():
    """Aturannya 'lebih panjang dari', jadi jeda == batas lolos."""
    blok = [(5, 0.0), (5, 5.0)]                  # jeda antar kalimat sekitar 5 dtk
    kal = split_sentences(_susun(blok))
    jeda = kal[5].start - kal[4].end             # jeda terukur apa adanya
    assert 4.9 < jeda < 5.5
    tepat = _calon(blok, jeda_maks_calon=jeda, per_start=50)       # batas == jeda persis
    assert any(c.start < kal[4].end and c.end > kal[5].start for c in tepat)
    ada = _calon(blok, jeda_maks_calon=jeda + 1e-6, per_start=50)
    assert any(c.start < kal[4].end and c.end > kal[5].start for c in ada)
    tidak = _calon(blok, jeda_maks_calon=jeda - 0.01, per_start=50)
    assert not any(c.start < kal[4].end and c.end > kal[5].start for c in tidak)


def test_tanpa_jeda_panjang_hasil_sama_dengan_perilaku_lama():
    blok = [(40, 0.0)]       # tidak ada jeda panjang sama sekali
    a = _calon(blok, jeda_maks_calon=10)
    b = _calon(blok, jeda_maks_calon=None)
    assert [(c.start, c.end) for c in a] == [(c.start, c.end) for c in b]


def test_awal_yang_terhalang_jeda_tidak_membuat_calon_melewatinya():
    """Awal dekat jeda: satu-satunya calon sah mungkin tidak ada; tak boleh error."""
    blok = [(3, 0.0), (10, 30.0)]            # blok pertama hanya ~10 dtk
    calon = _calon(blok, jeda_maks_calon=10)
    a, b = _jeda_posisi(blok)
    assert not any(_melintasi(c, a, b) for c in calon)
    assert all(c.start >= b - 1e-9 for c in calon)


def test_nilai_tidak_valid_ditolak():
    kal = split_sentences(_susun([(10, 0.0)]))
    for buruk in (0, -1, -0.5):
        with pytest.raises(ValueError):
            build_candidates(kal, jeda_maks_calon=buruk)


def test_pembatas_per_start_dan_maks_sec_tidak_berubah():
    calon = _calon([(40, 0.0)], jeda_maks_calon=10, per_start=3)
    per_awal = {}
    for c in calon:
        per_awal[c.start] = per_awal.get(c.start, 0) + 1
    assert max(per_awal.values()) <= 3
    assert all(20 <= c.duration <= 60 for c in calon)


# --- rantai pipeline ---------------------------------------------------------
def test_rantai_membuang_calon_berjeda_panjang_dan_bisa_dimatikan():
    kata = _susun(BLOK_JEDA_30)
    a, b = _jeda_posisi(BLOK_JEDA_30)
    baru = jalankan_rantai(kata, n=3)                          # bawaan: aturan aktif
    lama = jalankan_rantai(kata, n=3, jeda_maks_calon=None)    # perilaku lama
    assert baru.jumlah_calon < lama.jumlah_calon
    assert not any(k.start < a and k.end > b for k in baru.klip)


def test_terminal_opsi_mati_sama_dengan_perilaku_lama(tmp_path, capsys):
    import json
    kata = _susun(BLOK_JEDA_30)
    berkas = tmp_path / "kata.json"
    berkas.write_text(json.dumps([{"w": k.text, "s": k.start, "e": k.end} for k in kata]), encoding="utf-8")
    assert pipeline_main([str(berkas), "--jeda-maks-calon", "0"]) == 0
    mati = capsys.readouterr().out
    assert pipeline_main([str(berkas)]) == 0
    hidup = capsys.readouterr().out
    assert mati != hidup           # jumlah calon berbeda, jadi keluaran berbeda
