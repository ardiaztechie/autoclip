"""Pengujian core/selection.py. Jalankan dari folder proyek:  python -m pytest tests/test_selection.py -v"""
import copy
import itertools
import random

import pytest

from core.models import Candidate, ScoredCandidate, Sentence, Word
from core.selection import (JARAK_MIN, OVERLAP_MAKS, pilih_klip, select_top_n)


def kand(mulai, akhir, skor):
    """ScoredCandidate minimal: hanya start, end, dan score yang dipakai seleksi."""
    return ScoredCandidate(Candidate([Sentence([Word("x.", mulai, akhir)])]), 0.0, 0.0, 0.0, 0.0, skor)


def awal(hasil):
    return [k.start for k in hasil]


# ---------------------------------------------------------------- aturan dasar
def test_skor_tertinggi_dipilih_lebih_dulu():
    # Hanya satu slot: yang tertinggi menang walau muncul terakhir di masukan
    data = [kand(0, 30, 70), kand(100, 130, 80), kand(200, 230, 90)]
    assert awal(select_top_n(data, 1)) == [200]


def test_overlap_melebihi_batas_ditolak():
    # overlap 22 dtk dari klip terpendek 40 dtk = 55%
    hasil = pilih_klip([kand(12, 52, 91), kand(30, 70, 88)], 2)
    assert awal(hasil.terpilih) == [12]
    assert "55%" in hasil.ditolak[0][1]


def test_overlap_tepat_20_persen_diterima():
    # A 0-50, B 40-100: overlap 10 dtk dibagi klip terpendek (50 dtk) = 20% tepat
    assert awal(select_top_n([kand(0, 50, 90), kand(40, 100, 80)], 2)) == [0, 40]


def test_overlap_sedikit_di_atas_20_persen_ditolak():
    # overlap 11 dtk dari 50 dtk = 22%
    assert awal(select_top_n([kand(0, 50, 90), kand(39, 99, 80)], 2)) == [0]


def test_overlap_dibagi_klip_terpendek_bukan_klip_panjang():
    # Klip pendek 20 dtk di dalam klip 100 dtk. Dibagi klip panjang = 20% (lolos), dibagi
    # klip pendek = 100% (benar: ditolak).
    assert awal(select_top_n([kand(0, 100, 90), kand(40, 60, 80)], 2)) == [0]


def test_jarak_kurang_dari_minimum_ditolak():
    # Tidak overlap, selisih mulai 19,9 dtk < 20
    assert awal(select_top_n([kand(0, 10, 90), kand(19.9, 29.9, 80)], 2)) == [0]


def test_jarak_tepat_20_detik_diterima():
    assert awal(select_top_n([kand(0, 10, 90), kand(20, 30, 80)], 2)) == [0, 20]


def test_kandidat_tanpa_overlap_dan_jarak_cukup_dipilih():
    assert awal(select_top_n([kand(0, 30, 90), kand(100, 130, 80)], 2)) == [0, 100]


def test_aturan_celah_menolak_overlap_sekecil_apa_pun():
    # Pada aturan "celah" jarak diukur dari akhir klip awal ke mulai klip berikut
    data = [kand(0, 30, 90), kand(29, 59, 80)]                 # overlap 1/30 = 3%
    assert len(select_top_n(data, 2, aturan_jarak="mulai")) == 2          # selisih mulai 29 >= 20, overlap 3% <= 20%
    assert len(select_top_n(data, 2, aturan_jarak="celah")) == 1          # celah -1 dtk < 20


def test_aturan_celah_batas_tepat_dan_di_bawah():
    assert len(select_top_n([kand(0, 30, 90), kand(50, 80, 80)], 2, aturan_jarak="celah")) == 2     # celah 20
    assert len(select_top_n([kand(0, 30, 90), kand(49.9, 79.9, 80)], 2, aturan_jarak="celah")) == 1


# ---------------------------------------------------------------- hasil dan jumlah
def test_hasil_diurutkan_menurut_waktu_mulai():
    data = [kand(200, 230, 90), kand(0, 30, 80), kand(100, 130, 70)]
    assert awal(select_top_n(data, 3)) == [0, 100, 200]


def test_jumlah_hasil_tidak_melebihi_n():
    data = [kand(i * 100, i * 100 + 30, 50 + i) for i in range(10)]
    for n in (0, 1, 3, 9, 10, 25):
        assert len(select_top_n(data, n)) == min(n, 10)


def test_kandidat_lebih_sedikit_dari_n():
    data = [kand(0, 30, 90), kand(100, 130, 80)]
    assert len(select_top_n(data, 5)) == 2


def test_masukan_kosong():
    hasil = pilih_klip([], 3)
    assert hasil.terpilih == [] and hasil.ditolak == [] and hasil.indeks_terpilih == []


def test_semua_bertabrakan_hasil_kurang_dari_n():
    data = [kand(0, 30, 90), kand(5, 35, 80), kand(10, 40, 70)]
    hasil = pilih_klip(data, 3)
    assert awal(hasil.terpilih) == [0]
    assert [i for i, _ in hasil.ditolak] == [1, 2]


def test_skor_sama_deterministik_mulai_paling_awal_menang():
    data = [kand(50, 80, 80), kand(0, 30, 80), kand(25, 55, 80)]
    # Seri: mulai 0 dulu, lalu 25 (selisih 25, overlap 5/30=17%: diterima)
    for urutan in itertools.permutations(data):
        assert awal(select_top_n(list(urutan), 2)) == [0, 25]


def test_hasil_sama_untuk_urutan_masukan_acak():
    rnd = random.Random(5)
    data = [kand(s, s + rnd.randint(20, 60), float(rnd.randint(0, 5) * 10)) for s in range(0, 900, 13)]
    acuan = [(k.start, k.end) for k in select_top_n(data, 6)]
    for _ in range(20):
        rnd.shuffle(data)
        assert [(k.start, k.end) for k in select_top_n(data, 6)] == acuan


# ---------------------------------------------------------------- data tidak valid
@pytest.mark.parametrize("rusak", [
    kand(float("nan"), 30, 90),            # mulai NaN
    kand(0, float("inf"), 90),             # akhir tak hingga
    kand(None, 30, 90),                    # mulai kosong
    kand(-5, 30, 90),                      # negatif
    kand(30, 30, 90),                      # durasi nol
    kand(40, 30, 90),                      # akhir sebelum mulai
    kand(0, 30, float("nan")),             # skor NaN
    kand(0, 30, None),                     # skor kosong
    kand(0, 30, True),                     # skor bool
    kand(0, 10 ** 400, 90),                # bilangan terlalu besar untuk float
    ScoredCandidate(Candidate([]), 0, 0, 0, 0, 50.0),   # kandidat tanpa kalimat
    None, "bukan kandidat", 42, object(),
])
def test_data_tidak_valid_ditolak_tanpa_crash(rusak):
    baik = kand(100, 130, 70)
    hasil = pilih_klip([rusak, baik], 2)
    assert awal(hasil.terpilih) == [100]
    assert [i for i, _ in hasil.ditolak] == [0]


def test_masukan_bukan_daftar_dianggap_kosong():
    assert pilih_klip(None, 3).terpilih == []
    assert pilih_klip(12345, 3).terpilih == []


@pytest.mark.parametrize("n", [-1, 2.5, "3", None, True])
def test_n_tidak_valid_memunculkan_value_error(n):
    with pytest.raises(ValueError):
        pilih_klip([kand(0, 30, 90)], n)


@pytest.mark.parametrize("kw", [{"overlap_maks": -0.1}, {"overlap_maks": 1.5}, {"overlap_maks": float("nan")},
                                {"jarak_min": -1}, {"jarak_min": None}, {"aturan_jarak": "lain"}])
def test_parameter_tidak_valid_memunculkan_value_error(kw):
    with pytest.raises(ValueError):
        pilih_klip([kand(0, 30, 90)], 1, **kw)


# ---------------------------------------------------------------- tidak mengubah data asli
def test_seleksi_tidak_mengubah_data_asli():
    data = [kand(200, 230, 60), kand(0, 30, 90), kand(10, 40, 80), kand(100, 130, 70)]
    salinan = copy.deepcopy(data)
    urutan_objek = list(data)
    hasil = select_top_n(data, 3)
    assert data == salinan                                  # nilai tiap kandidat sama
    assert all(a is b for a, b in zip(data, urutan_objek))  # daftar tidak diurut ulang
    assert all(any(h is d for d in data) for h in hasil)    # hasil = objek asli, bukan salinan yang berubah


# ---------------------------------------------------------------- sifat umum
def test_pasangan_terpilih_tidak_pernah_melanggar_aturan():
    rnd = random.Random(1)
    data = [kand(s, s + rnd.randint(20, 60), rnd.random() * 100) for s in rnd.sample(range(0, 1200, 7), 60)]
    hasil = select_top_n(data, 8)
    for a, b in itertools.combinations(hasil, 2):
        bersama = max(0.0, min(a.end, b.end) - max(a.start, b.start))
        assert bersama / min(a.end - a.start, b.end - b.start) <= OVERLAP_MAKS + 1e-9
        assert abs(a.start - b.start) >= JARAK_MIN - 1e-9


# ---------------------------------------------------------------- integrasi dengan scoring
def test_integrasi_dengan_hasil_scoring():
    """Rantai nyata: kalimat -> calon -> skor -> seleksi (tanpa mengubah scoring)."""
    from core.models import EnergyProfile
    from core.scoring import build_idf, score_candidates
    from core.segments import build_candidates, split_sentences

    kata, t = [], 0.0
    for i in range(400):
        kata.append(Word(f"kata{i % 37}" + ("." if i % 9 == 8 else ""), round(t, 3), round(t + 0.35, 3)))
        t += 0.4
    kalimat = split_sentences(kata)
    calon = build_candidates(kalimat)
    skor = score_candidates(calon, build_idf(kalimat), EnergyProfile(1.0, [1.0 + (i % 7) for i in range(int(t) + 2)]))
    assert skor, "scoring seharusnya menghasilkan kandidat"
    hasil = select_top_n(skor, 3)
    assert 1 <= len(hasil) <= 3
    assert awal(hasil) == sorted(awal(hasil))
