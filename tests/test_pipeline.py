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


def test_rantai_dengan_energi(tmp_path, capsys):
    import math
    import wave

    import numpy as np
    kata = kata_sintetis(600)                              # sekitar 240 dtk
    t = np.arange(250 * 16000) / 16000
    sinyal = (0.1 + 0.7 * (t > 120)) * np.sin(2 * math.pi * 300 * t)
    wav = tmp_path / "a.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((sinyal * 32767).astype("<i2").tobytes())
    masuk = tmp_path / "kata.json"
    masuk.write_text(ke_json(kata), encoding="utf-8")
    assert P.main([str(masuk), "--media", str(wav)]) == 0
    assert "dengan energi suara" in capsys.readouterr().out
    assert P.main([str(masuk), "--media", str(tmp_path / "tidak_ada.wav")]) == 1


def test_rentang_durasi_dapat_diatur_dan_bawaan_20_60():
    kata = kata_sintetis(1500)                                  # sekitar 10 menit
    bawaan = P.jalankan_rantai(kata, n=5)
    assert all(20 <= k.end - k.start <= 60 + 5 for k in bawaan.klip)
    panjang = P.jalankan_rantai(kata, n=5, min_detik=60, maks_detik=120)
    assert panjang.klip and all(k.end - k.start >= 60 - 1e-6 for k in panjang.klip)


@pytest.mark.parametrize("min_d,maks_d", [(0, 60), (-5, 60), (60, 20)])
def test_rentang_durasi_salah(min_d, maks_d):
    with pytest.raises(ValueError):
        P.jalankan_rantai(kata_sintetis(100), min_detik=min_d, maks_detik=maks_d)


# --- jumlah klip otomatis dan preset durasi (eksperimental) ---
def test_jumlah_klip_otomatis():
    from core.pipeline import jumlah_klip_otomatis
    assert jumlah_klip_otomatis(1540) == 20      # 1540 / 75
    assert jumlah_klip_otomatis(74) == 1         # minimal 1
    assert jumlah_klip_otomatis(150) == 2
    assert jumlah_klip_otomatis(0) == 1
    assert jumlah_klip_otomatis(600, 60) == 10


def test_tingkat_jumlah_berurutan():
    from core.pipeline import TINGKAT_JUMLAH, jumlah_klip_otomatis
    n = {k: jumlah_klip_otomatis(1500, v) for k, v in TINGKAT_JUMLAH.items()}
    assert n["jarang"] < n["sedang"] < n["rapat"]


def test_jumlah_klip_otomatis_tak_valid():
    import pytest
    from core.pipeline import jumlah_klip_otomatis
    with pytest.raises(ValueError):
        jumlah_klip_otomatis(100, 0)
    with pytest.raises(ValueError):
        jumlah_klip_otomatis(-1)


def test_preset_durasi():
    from core.pipeline import PRESET_DURASI
    assert PRESET_DURASI["sedang"] == (30.0, 60.0)
    assert PRESET_DURASI["otomatis"] == (30.0, 60.0)
    assert all(a < b for a, b in PRESET_DURASI.values())
