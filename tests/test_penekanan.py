"""Pengujian core/penekanan.py (kapan zoom in terjadi) dan penerapannya pada jalur dan render.

Jalankan: python -m pytest tests/test_penekanan.py -v
"""
import shutil

import numpy as np
import pytest

from core import penekanan as Z
from core import pembicara as P
from core.face import Jalur, Kotak
from core.models import EnergyProfile, Word


def kata_dari(teks, mulai=0.0, durasi=0.3, jeda=0.1):
    hasil, t = [], mulai
    for w in teks.split():
        hasil.append(Word(w, round(t, 3), round(t + durasi, 3)))
        t += durasi + jeda
    return hasil


def energi(nilai, langkah=0.25):
    return EnergyProfile(langkah, list(nilai))


# ---------------------------------------------------------------- pemicu emosi
def test_kata_emosi_frasa_dan_tanda_seru():
    k = [Word("itu", 0, 0.3), Word("Wow,", 1.0, 1.4), Word("luar", 2.0, 2.3), Word("biasa", 2.35, 2.7),
         Word("serius!", 3.0, 3.4), Word("biasa", 4.0, 4.3)]
    alasan = [a for _, _, a in Z.peristiwa_emosi(k)]
    assert alasan == ["wow", "luar biasa", "!"]


def test_kata_rusak_dan_kosong_tidak_membuat_crash():
    class Rusak:
        text, start, end = None, 1.0, 2.0
    assert Z.peristiwa_emosi([Rusak(), None, "x", Word("wow", float("nan"), 1.0)]) == []
    assert Z.peristiwa_emosi(None) == [] and Z.peristiwa_emosi([]) == []


# ---------------------------------------------------------------- pemicu volume
def profil(lonjakan_di=(), nilai_biasa=0.05, nilai_lonjak=0.20, n=120):
    v = [nilai_biasa] * n
    for i in lonjakan_di:
        v[i] = nilai_lonjak
    return energi(v)


def test_lonjakan_volume_terdeteksi_setelah_cukup_lama():
    hasil = Z.peristiwa_volume(profil(range(40, 44)))                 # 4 bin x 0,25 dtk = 1 dtk
    assert len(hasil) == 1 and hasil[0][:2] == (10.0, 11.0) and hasil[0][2] == "volume"


def test_volume_naik_sedikit_atau_sesaat_diabaikan():
    assert Z.peristiwa_volume(profil(range(40, 44), nilai_lonjak=0.07)) == []      # hanya 1,4x
    assert Z.peristiwa_volume(profil([40])) == []                                  # satu bin = 0,25 dtk < 0,4 dtk


def test_volume_di_bawah_lantai_hening_diabaikan():
    assert Z.peristiwa_volume(profil(range(40, 44), nilai_biasa=0.001, nilai_lonjak=0.008)) == []


def test_lonjakan_volume_dipagari_ucapan():
    ada = lambda t: not (10.0 <= t <= 11.0)        # saat lonjakan tidak ada yang berbicara (tepuk tangan)
    assert Z.peristiwa_volume(profil(range(40, 44)), ada) == []
    assert len(Z.peristiwa_volume(profil(range(40, 44)), lambda t: True)) == 1


def test_profil_energi_rusak_dilewati():
    for rusak in (None, EnergyProfile(0.25, []), EnergyProfile(-1, [0.1]), EnergyProfile(0.25, [0.1, float("nan")]),
                  EnergyProfile(0.25, [0.1, -1.0])):
        assert Z.peristiwa_volume(rusak) == []


def test_rasio_energi_dan_statistik():
    r = Z.rasio_energi(profil(range(40, 44)))
    assert max(r) == pytest.approx(4.0) and r[0] == pytest.approx(1.0)
    st = Z.statistik_volume(profil(range(40, 44)), 0, 30)
    assert st["maks"] == pytest.approx(4.0) and st["lebih_18"] == 4 and st["lebih_22"] == 4 and st["p50"] == pytest.approx(1.0)
    assert Z.statistik_volume(profil(range(40, 44)), 0, 30, lambda t: False) == {}      # tanpa ucapan: kosong
    assert Z.statistik_volume(None, 0, 30) == {} and Z.rasio_energi(EnergyProfile(0.25, [])) == []


def test_rasio_energi_hening_nol_bukan_pembagian_nol():
    assert Z.rasio_energi(energi([0.0] * 20)) == [0.0] * 20


# ---------------------------------------------------------------- bentuk selang dan batasnya
def test_selang_mencakup_awal_dan_tahan_serta_diperpanjang_ke_minimum():
    (a, b, alasan), = Z.cari_penekanan([Word("wow", 10.0, 10.2)], 0, 60)
    assert a == pytest.approx(10.0 - Z.AWAL_ZOOM) and b - a >= Z.DURASI_ZOOM_MIN - 1e-6 and alasan == "wow"


def test_zoom_tidak_lebih_lama_dari_maksimum():
    (a, b, _), = Z.cari_penekanan([Word("wow", 10.0, 14.0)], 0, 60)           # kata panjang 4 dtk
    assert b - a == pytest.approx(Z.DURASI_ZOOM_MAKS)


def test_jarak_minimum_antar_zoom_dan_urutan_waktu_dipertahankan():
    k = [Word("wow", 10.0, 10.2), Word("gila", 11.0, 11.2), Word("keren", 20.0, 20.2)]
    hasil = Z.cari_penekanan(k, 0, 60)
    assert [round(a) for a, _, _ in hasil] == [10, 20]            # "gila" terlalu dekat dengan zoom sebelumnya


def test_porsi_maksimum_zoom_dari_durasi_klip():
    # Klip 12 dtk: batas 35% = 4,2 dtk. Tiga kata emosi panjang (zoom 1,5 dtk tiap kali, berjarak cukup):
    # dua zoom = 3,0 dtk muat, yang ketiga (4,5 dtk) melampaui batas dan dibuang.
    k = [Word("wow", 1.0, 2.4), Word("wow", 4.6, 6.0), Word("wow", 8.2, 9.6)]
    hasil = Z.cari_penekanan(k, 0, 12)
    assert len(hasil) == 2 and sum(b - a for a, b, _ in hasil) <= Z.FRAKSI_ZOOM_MAKS * 12 + 1e-6


def test_zoom_dipotong_pada_batas_klip_dan_peristiwa_luar_klip_diabaikan():
    hasil = Z.cari_penekanan([Word("wow", 0.0, 0.2), Word("wow", 99.0, 99.2), Word("gila", 50.0, 50.2)], 0.0, 10.0)
    assert hasil == [] or all(0.0 <= a and b <= 10.0 for a, b, _ in hasil)
    assert all(a >= 0.0 for a, _, _ in hasil)
    assert not any(a > 10 for a, _, _ in hasil)


def test_gabungan_emosi_dan_volume_menjadi_satu_selang_dengan_dua_alasan():
    hasil = Z.cari_penekanan([Word("wow", 10.0, 10.3)], 0, 60, profil(range(40, 44)))
    assert len(hasil) == 1 and hasil[0][2] == "volume+wow"


def test_tanpa_sinyal_tidak_ada_zoom_dan_rentang_salah():
    assert Z.cari_penekanan(kata_dari("biasa saja tidak ada apa apa"), 0, 60) == []
    assert Z.cari_penekanan(None, 0, 60, None) == []
    for a, b in ((5, 5), (-1, 5), (float("nan"), 5)):
        with pytest.raises(ValueError):
            Z.cari_penekanan([], a, b)


# ---------------------------------------------------------------- penerapan pada jalur
def kotak(cx, ukuran=100):
    return Kotak(cx - ukuran / 2, 130, ukuran, ukuran, 0.9)


def sampel_dua(n=100, potong_di=(), tanpa_wajah=()):
    return [P.Sampel(round(i * 0.1, 3),
                     () if i in tanpa_wajah else (P.Pengamatan(1, kotak(300), 4.0, 5.0),),
                     i in potong_di, 0.0) for i in range(n)]


def jalur_zoom(selang, selang_lebar=(), **kw):
    s = sampel_dua(**kw)
    return P.susun_jalur(s, [1] * len(s), set(), 640, 360, "9:16", selang_lebar=selang_lebar, selang_zoom=selang)[0]


def test_zoom_diteruskan_ke_jalur_dengan_pusat_di_wajah():
    j = jalur_zoom([(3.0, 4.0)])
    assert j.selang_zoom == ((3.0, 4.0),) and j.faktor_zoom == Z.FAKTOR_ZOOM
    cx, cy = j.pusat_zoom(3.5)
    assert cx == pytest.approx(300, abs=1) and cy == pytest.approx(180, abs=1)


def test_zoom_tidak_bertumpuk_dengan_tampilan_lebar():
    j = jalur_zoom([(3.0, 5.0)], selang_lebar=[(4.0, 6.0)])
    assert j.selang_zoom == ((3.0, 4.0),)


def test_zoom_dipisah_di_pergantian_kamera():
    j = jalur_zoom([(3.0, 6.0)], potong_di={45})                           # kamera berganti di 4,5 dtk
    assert len(j.selang_zoom) == 2 and j.selang_zoom[0][1] < 4.5 <= j.selang_zoom[1][0]


def test_zoom_tanpa_wajah_dibuang():
    j = jalur_zoom([(3.0, 4.5)], tanpa_wajah=set(range(25, 55)))
    assert j.selang_zoom == () and j.titik_zoom == () and j.faktor_zoom == 1.0


def test_tanpa_selang_atau_faktor_satu_tidak_ada_zoom():
    assert jalur_zoom([]).selang_zoom == ()
    s = sampel_dua()
    j, _ = P.susun_jalur(s, [1] * len(s), set(), 640, 360, "9:16", selang_zoom=[(3, 4)], faktor_zoom=1.0)
    assert j.selang_zoom == ()


def test_pusat_zoom_tanpa_titik_memakai_tengah_jendela():
    j = Jalur([(0.0, 100.0, 0.0)], 200, 360, 640, 360, "9:16", 1.0, (), ((1.0, 2.0)), 1.25, ())
    assert j.pusat_zoom(1.5) == (200.0, 180.0)


# ---------------------------------------------------------------- render
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg tidak terpasang")
def test_zoom_terbakar_ke_video(tmp_path):
    import cv2
    from core import render as R
    # Video: kotak putih kecil (20x20) di tengah bingkai hitam; zoom 1,25x harus memperbesarnya
    sumber = tmp_path / "v.mp4"
    w = cv2.VideoWriter(str(sumber), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 180))
    for _ in range(90):
        f = np.zeros((180, 320, 3), np.uint8)
        f[80:100, 150:170] = 255
        w.write(f)
    w.release()
    jalur = Jalur([(0.0, 110.0, 0.0), (3.0, 110.0, 0.0)], 100, 180, 320, 180, "9:16", 1.0)
    biasa, zoom = tmp_path / "biasa.mp4", tmp_path / "zoom.mp4"
    R.render_klip(sumber, 0.0, 3.0, biasa, jalur=jalur, lebar_keluaran=180)
    R.render_klip(sumber, 0.0, 3.0, zoom, jalur=jalur, lebar_keluaran=180, selang_zoom=[(1.0, 2.0)])

    def putih(p, nomor):
        c = cv2.VideoCapture(str(p)); c.set(cv2.CAP_PROP_POS_FRAMES, nomor); ok, f = c.read(); c.release()
        assert ok
        return float((f[:, :, 0] > 128).mean())
    luas_biasa, luas_zoom = putih(biasa, 45), putih(zoom, 45)           # detik 1,5 (di dalam zoom)
    assert luas_zoom == pytest.approx(luas_biasa * 1.25 ** 2, rel=0.25)
    assert putih(zoom, 10) == pytest.approx(putih(biasa, 10), rel=0.1)  # di luar zoom: sama dengan biasa
