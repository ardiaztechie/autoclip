"""Pengujian core/audio.py dengan audio sintetis (tanpa video). Jalankan: python -m pytest tests/test_audio.py -v"""
import math
import wave

import numpy as np
import pytest

from core import audio as A
from core.models import EnergyProfile

LAJU = 16000


def tulis_wav(jalur, sinyal, laju=LAJU, kanal=1):
    data = (np.clip(sinyal, -1, 1) * 32767).astype("<i2")
    if kanal == 2:
        data = np.repeat(data[:, None], 2, axis=1).reshape(-1)
    with wave.open(str(jalur), "wb") as w:
        w.setnchannels(kanal)
        w.setsampwidth(2)
        w.setframerate(laju)
        w.writeframes(data.tobytes())
    return jalur


def sinus(amplitudo, detik, laju=LAJU, frek=440.0):
    t = np.arange(int(detik * laju)) / laju
    return amplitudo * np.sin(2 * math.pi * frek * t)


def test_rms_sinus_sesuai_teori(tmp_path):
    f = tulis_wav(tmp_path / "a.wav", sinus(0.5, 5))
    p = A.hitung_energi(f)
    assert isinstance(p, EnergyProfile) and p.step == 1.0 and len(p.values) == 5
    for v in p.values:
        assert v == pytest.approx(0.5 / math.sqrt(2), abs=0.005)


def test_bagian_keras_dan_pelan_terbedakan(tmp_path):
    f = tulis_wav(tmp_path / "b.wav", np.concatenate([sinus(0.1, 3), sinus(0.8, 2)]))
    v = A.hitung_energi(f).values
    assert len(v) == 5 and max(v[:3]) < min(v[3:])


def test_hening_mutlak_bernilai_nol(tmp_path):
    v = A.hitung_energi(tulis_wav(tmp_path / "h.wav", np.zeros(3 * LAJU))).values
    assert v == [0.0, 0.0, 0.0]


def test_sisa_akhir_tetap_dihitung(tmp_path):
    p = A.hitung_energi(tulis_wav(tmp_path / "c.wav", sinus(0.5, 2.5)))
    assert len(p.values) == 3
    assert p.values[2] == pytest.approx(0.5 / math.sqrt(2), abs=0.01)   # kantong separuh: RMS dari sampel yang ada


def test_stereo_dan_laju_lain_dibaca(tmp_path):
    # Penggabungan stereo -> mono oleh FFmpeg menjumlahkan kanal dengan bobot 1/akar2 per kanal,
    # jadi dua kanal identik terukur akar2 kali lebih keras. Skala absolut berbeda, tetapi Trend
    # memakai RASIO terhadap rata-rata video, sehingga selisih skala seragam tidak berpengaruh.
    f = tulis_wav(tmp_path / "s.wav", np.concatenate([sinus(0.2, 2, laju=44100), sinus(0.4, 2, laju=44100)]),
                  laju=44100, kanal=2)
    v = A.hitung_energi(f).values
    assert len(v) == 4
    assert v[2] / v[1] == pytest.approx(2.0, rel=0.02)


def test_langkah_lain(tmp_path):
    p = A.hitung_energi(tulis_wav(tmp_path / "d.wav", sinus(0.5, 4)), langkah=0.5)
    assert p.step == 0.5 and len(p.values) == 8


@pytest.mark.parametrize("langkah", [0, -1, float("nan"), float("inf"), None, True, "1"])
def test_langkah_tidak_valid(tmp_path, langkah):
    f = tulis_wav(tmp_path / "e.wav", sinus(0.5, 1))
    with pytest.raises(ValueError):
        A.hitung_energi(f, langkah)


def test_berkas_tidak_ada(tmp_path):
    with pytest.raises(FileNotFoundError):
        A.hitung_energi(tmp_path / "tidak_ada.wav")


def test_berkas_bukan_media(tmp_path):
    f = tmp_path / "teks.wav"
    f.write_bytes(b"ini bukan audio sama sekali")
    with pytest.raises(ValueError):
        A.hitung_energi(f)


def test_audio_tanpa_sampel(tmp_path):
    with pytest.raises(ValueError):
        A.hitung_energi(tulis_wav(tmp_path / "kosong.wav", np.zeros(0)))


def test_cocok_dengan_scoring(tmp_path):
    """Keluaran dapat dipakai langsung oleh trend_scores (rantai nyata)."""
    from core.models import Candidate, Sentence, Word
    from core.scoring import trend_scores
    p = A.hitung_energi(tulis_wav(tmp_path / "t.wav", np.concatenate([sinus(0.1, 30), sinus(0.8, 30)])))
    def calon(a, b):
        return Candidate([Sentence([Word("kata.", a, b)])])
    r = trend_scores([calon(0, 25), calon(35, 59)], p)
    assert all(x.valid for x in r) and r[1].skor > r[0].skor


def test_terminal(tmp_path, capsys):
    f = tulis_wav(tmp_path / "m.wav", sinus(0.5, 3))
    assert A.main([str(f)]) == 0
    assert "Jumlah nilai  : 3" in capsys.readouterr().out
    assert A.main([str(tmp_path / "x.wav")]) == 1
