"""Pengujian core/pipeline.py (data sintetis, tanpa Whisper). Jalankan: python -m pytest tests/test_pipeline.py -v"""
import json

import pytest

from core import pipeline as P
from core.models import Word
from core.transcribe import ke_json


def kata_sintetis(jumlah=600):
    kata, t = [], 0.0
    for i in range(jumlah):
        kata.append(Word(f"kata{i % 41}" + ("." if i % 9 == 8 else ""), round(t, 3), round(t + 0.35, 3)))
        t += 0.4
    return kata


def test_rantai_menghasilkan_klip_sesuai_aturan():
    h = P.jalankan_rantai(kata_sintetis(), n=3)
    assert h.jumlah_kata == 600 and h.jumlah_kalimat > 0 and h.jumlah_calon >= h.jumlah_dinilai > 0
    assert 1 <= len(h.klip) <= 3
    assert [k.start for k in h.klip] == sorted(k.start for k in h.klip)
    assert h.energi_dipakai is False
    for k in h.klip:
        assert 0 <= k.score <= 100


def test_kata_kosong_tidak_crash():
    h = P.jalankan_rantai([], n=3)
    assert h.klip == [] and h.jumlah_calon == 0


def test_terminal_menyimpan_json(tmp_path, capsys):
    masuk = tmp_path / "kata.json"
    masuk.write_text(ke_json(kata_sintetis()), encoding="utf-8")
    keluar = tmp_path / "out" / "klip.json"
    assert P.main([str(masuk), "--n", "2", "--simpan", str(keluar)]) == 0
    data = json.loads(keluar.read_text(encoding="utf-8"))
    assert 1 <= len(data) <= 2 and {"mulai", "akhir", "skor", "teks"} <= data[0].keys()
    assert "HANYA penanda emosi" in capsys.readouterr().out


def test_terminal_berkas_tidak_ada(tmp_path, capsys):
    assert P.main([str(tmp_path / "x.json")]) == 1
    assert "[GAGAL]" in capsys.readouterr().out


def test_terminal_json_rusak(tmp_path, capsys):
    f = tmp_path / "rusak.json"
    f.write_text("bukan json", encoding="utf-8")
    assert P.main([str(f)]) == 1
