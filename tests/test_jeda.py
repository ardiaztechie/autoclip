"""Pengujian core/jeda.py. Jalankan: python -m pytest tests/test_jeda.py -v"""
import pytest

from core import jeda as J

KATA = [{"w": "a", "s": 1.0, "e": 1.5}, {"w": "b", "s": 3.0, "e": 3.4}, {"w": "c", "s": 3.5, "e": 4.0}]


def test_hitung_buang_awal_tengah_akhir_dengan_sisa():
    assert J.hitung_buang(KATA, 0.0, 6.0, 0.6) == [(0.0, 0.9), (1.6, 2.9), (4.1, 6.0)]


def test_ambang_besar_hanya_lubang_panjang():
    assert J.hitung_buang(KATA, 0.0, 6.0, 1.5) == [(1.6, 2.9)] or J.hitung_buang(KATA, 0.0, 6.0, 1.5) == [(1.6, 2.9), (4.1, 6.0)]
    assert J.hitung_buang(KATA, 0.0, 6.0, 2.5) == []


def test_tanpa_kata_tidak_ada_yang_dibuang_dan_ambang_dibatasi():
    assert J.hitung_buang([], 0, 10) == []
    assert J.hitung_buang(KATA, 0.0, 6.0, 0.0) != []          # ambang 0 dinaikkan ke batas aman, tidak membuang antar-kata rapat
    assert J.hitung_buang([{"w": "x", "s": 1.0, "e": 1.1}, {"w": "y", "s": 1.15, "e": 1.3}], 1.0, 1.3, 0.0) == []


def test_selaraskan_ke_batas_frame_dan_gabung_yang_bersentuhan():
    s = J.selaraskan([(1.01, 2.02), (2.03, 2.5)], 30)
    assert all(abs(a * 30 - round(a * 30)) < 1e-6 and abs(b * 30 - round(b * 30)) < 1e-6 for a, b in s)
    assert len(s) == 1
    assert J.selaraskan([(1.01, 1.02)], 30) == []


def test_geser_waktu_dan_petakan_kata():
    buang = [(1.6, 2.9)]
    assert J.geser_waktu(1.0, buang) == 1.0 and J.geser_waktu(2.0, buang) == 1.6 and abs(J.geser_waktu(3.0, buang) - 1.7) < 1e-9
    peta = J.petakan_kata(KATA, buang)
    assert [round(k["s"], 2) for k in peta] == [1.0, 1.7, 2.2]
    assert J.petakan_kata([{"w": "z", "s": 2.0, "e": 2.5}], buang) == []       # kata di dalam lubang hilang


def test_filter_suara():
    assert J.filter_suara([], 0) is None
    f = J.filter_suara([(2.0, 3.0)], 1.0)
    assert "between(t,1.000000,2.000000)" in f and "asetpts=N/SR/TB" in f


def test_gabung_menyatukan_dan_memotong_ke_rentang():
    assert J.gabung([(1, 2), (5, 6)], [(1.5, 3), (0, 0.5)], mulai=1, akhir=5.5) == [(1, 3), (5, 5.5)]
    assert J.gabung([], []) == []


def test_petakan_kata_menerima_objek_word_seperti_di_terminal_render():
    from core.models import Word
    peta = J.petakan_kata([Word("a", 1.0, 1.5), Word("b", 3.0, 3.4), Word("z", 2.0, 2.5)], [(1.6, 2.9)])
    assert [(w.text, round(w.start, 2), round(w.end, 2)) for w in peta] == [("a", 1.0, 1.5), ("b", 1.7, 2.1)]
