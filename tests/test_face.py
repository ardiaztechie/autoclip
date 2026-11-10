"""Pengujian core/face.py. Logika jalur diuji tanpa video; deteksi nyata hanya bila model dan video tersedia.

Jalankan: python -m pytest tests/test_face.py -v
Tes nyata: set AUTOCLIP_VIDEO_UJI ke video berwajah (dan berkas model YuNet harus ada).
"""
import os

import pytest

from core import face as F
from core.face import Kotak


def wajah(cx, cy, ukuran=100, skor=0.9):
    return Kotak(cx - ukuran / 2, cy - ukuran / 2, ukuran, ukuran, skor)


# ---------------------------------------------------------------- ukuran jendela
@pytest.mark.parametrize("rasio,hasil", [("9:16", (202, 360)), ("1:1", (360, 360)), ("4:5", (288, 360))])
def test_ukuran_potong_dari_bingkai_lebar(rasio, hasil):
    assert F.ukuran_potong(640, 360, rasio) == hasil


def test_ukuran_potong_dari_bingkai_tegak():
    assert F.ukuran_potong(360, 640, "1:1") == (360, 360)      # lebar penuh, tinggi dipangkas
    assert F.ukuran_potong(360, 640, "9:16") == (360, 640)


def test_ukuran_potong_selalu_genap_dan_muat():
    for w, h in [(641, 361), (1919, 1081), (333, 777)]:
        for r in F.RASIO_VALID:
            pw, ph = F.ukuran_potong(w, h, r)
            assert pw % 2 == 0 and ph % 2 == 0 and pw <= w and ph <= h


@pytest.mark.parametrize("args", [(640, 360, "16:9"), (0, 360, "1:1"), (640, 1, "1:1"), (640.0, 360, "1:1")])
def test_ukuran_potong_tidak_valid(args):
    with pytest.raises(ValueError):
        F.ukuran_potong(*args)


# ---------------------------------------------------------------- memilih wajah
def test_pilih_wajah_terbesar_bila_belum_ada_sebelumnya():
    a, b = wajah(100, 100, 50), wajah(400, 100, 120)
    assert F.pilih_wajah([a, b]) is b


def test_pilih_wajah_terdekat_dengan_sebelumnya():
    a, b = wajah(100, 100, 50), wajah(400, 100, 120)
    assert F.pilih_wajah([a, b], sebelumnya=(110, 100)) is a


def test_pilih_wajah_kosong():
    assert F.pilih_wajah([]) is None


# ---------------------------------------------------------------- jalur
def deteksi_tetap(cx, n=30, cy=180, langkah=0.2):
    return [(round(i * langkah, 3), [wajah(cx, cy)]) for i in range(n)]


def test_jalur_mengikuti_wajah_ke_kanan_dan_tetap_di_dalam_bingkai():
    j = F.bangun_jalur(deteksi_tetap(520, 40), 640, 360, "9:16")
    xs = [p[1] for p in j.titik]
    assert xs[-1] > xs[0] + 50
    assert all(0 <= x <= 640 - j.lebar_potong for x in xs)
    assert all(p[2] == 0 for p in j.titik)            # 9:16 dari 16:9: tinggi penuh, y tidak bergerak
    assert j.persen_berwajah == 1.0


def test_jalur_tanpa_wajah_tinggal_di_tengah():
    deteksi = [(i * 0.2, []) for i in range(10)]
    j = F.bangun_jalur(deteksi, 640, 360, "9:16")
    tengah = (640 - j.lebar_potong) / 2
    assert all(p[1] == pytest.approx(tengah, abs=0.01) for p in j.titik) and j.persen_berwajah == 0.0


def test_wajah_hilang_ditahan_lalu_kembali_ke_tengah():
    deteksi = deteksi_tetap(560, 20) + [(4.0 + i * 0.2, []) for i in range(60)]
    j = F.bangun_jalur(deteksi, 640, 360, "9:16", tahan=1.0)
    x_saat_hilang = j.titik[19][1]
    assert j.titik[22][1] >= x_saat_hilang - 5                 # masih ditahan sesaat
    # berhenti begitu masuk zona mati (5% lebar jendela), jadi sisa selisih <= zona itu
    assert abs(j.titik[-1][1] - (640 - j.lebar_potong) / 2) <= F.ZONA_MATI * j.lebar_potong + 0.5


def test_zona_mati_meredam_getaran_kecil():
    # wajah bergetar +-3 px; dengan zona mati jalur tidak ikut bergetar
    deteksi = [(i * 0.2, [wajah(320 + (3 if i % 2 else -3), 180)]) for i in range(40)]
    j = F.bangun_jalur(deteksi, 640, 360, "9:16")
    xs = [p[1] for p in j.titik]
    assert max(xs) - min(xs) < 1.0


def test_gerak_per_sampel_dibatasi_alpha():
    j = F.bangun_jalur(deteksi_tetap(600, 5), 640, 360, "1:1", alpha=0.25)
    xs = [p[1] for p in j.titik]
    assert all(b - a <= 0.25 * 640 for a, b in zip(xs, xs[1:]))


def test_pada_interpolasi_dan_ujung():
    j = F.Jalur([(0.0, 10.0, 0.0), (2.0, 30.0, 4.0)], 100, 100, 640, 360, "1:1", 1.0)
    assert j.pada(1.0) == (20.0, 2.0)
    assert j.pada(-5) == (10.0, 0.0) and j.pada(99) == (30.0, 4.0)
    assert F.Jalur([], 1, 1, 1, 1, "1:1", 0.0).pada(1.0) == (0.0, 0.0)


@pytest.mark.parametrize("kw", [{"alpha": 0}, {"alpha": 1.5}, {"zona_mati": -1}, {"tahan": -1}])
def test_parameter_jalur_tidak_valid(kw):
    with pytest.raises(ValueError):
        F.bangun_jalur(deteksi_tetap(320, 3), 640, 360, "9:16", **kw)


def test_deteksi_kosong_menghasilkan_jalur_kosong():
    j = F.bangun_jalur([], 640, 360, "9:16")
    assert j.titik == [] and j.persen_berwajah == 0.0


# ---------------------------------------------------------------- masukan salah
def test_video_tidak_ada(tmp_path):
    with pytest.raises(FileNotFoundError):
        F.deteksi_video(tmp_path / "x.mp4", 0, 5)


def test_rentang_waktu_salah(tmp_path):
    with pytest.raises(ValueError):
        F.deteksi_video(tmp_path / "x.mp4", 5, 5)
    with pytest.raises(ValueError):
        F.deteksi_video(tmp_path / "x.mp4", float("nan"), 5)


def test_model_tidak_ada(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        F.deteksi_video(v, 0, 5, path_model=tmp_path / "tidak_ada.onnx")


def test_terminal_gagal_dengan_kode_1(tmp_path, capsys):
    assert F.main([str(tmp_path / "x.mp4"), "--mulai", "0", "--akhir", "5"]) == 1
    assert "[GAGAL]" in capsys.readouterr().out


# ---------------------------------------------------------------- nyata (opsional)
@pytest.mark.skipif(not (os.getenv("AUTOCLIP_VIDEO_UJI") and F.jalur_model().is_file()),
                    reason="butuh AUTOCLIP_VIDEO_UJI dan berkas model YuNet")
def test_deteksi_nyata():
    deteksi, w, h, fps = F.deteksi_video(os.environ["AUTOCLIP_VIDEO_UJI"], 0, 5)
    assert deteksi and w > 0 and h > 0 and fps > 0
    j = F.bangun_jalur(deteksi, w, h, "9:16")
    assert all(0 <= p[1] <= w - j.lebar_potong for p in j.titik)
