"""Pengujian logika core/pembicara.py dengan data buatan (tanpa video dan tanpa model).

Jalankan: python -m pytest tests/test_pembicara.py -v
Analisis video nyata hanya berjalan bila AUTOCLIP_VIDEO_UJI dan berkas model YuNet tersedia.
"""
import os

import numpy as np
import pytest

from core import pembicara as P
from core.face import Jalur, Kotak, jalur_model
from core.models import Word

L, T, LANGKAH = 640, 360, 0.1


def kotak(cx, cy=180, ukuran=100):
    return Kotak(cx - ukuran / 2, cy - ukuran / 2, ukuran, ukuran, 0.9)


def peng(id_, cx, mulut=0.0, wajah=5.0, ukuran=100):
    return P.Pengamatan(id_, kotak(cx, ukuran=ukuran), mulut, wajah)


def rangkai(n, fungsi, potong_di=(), luas=0.0):
    """n sampel tiap 0,1 dtk; fungsi(i) -> daftar Pengamatan; luas = luas gerak (angka atau daftar)."""
    return [P.Sampel(round(i * LANGKAH, 3), tuple(fungsi(i)), i in potong_di,
                     luas if not isinstance(luas, list) else luas[i]) for i in range(n)]


# ---------------------------------------------------------------- pelacak identitas
def test_pelacak_menjaga_nomor_wajah_yang_bergeser_sedikit():
    p = P.PelacakWajah()
    a = p.perbarui([kotak(100), kotak(400)])
    b = p.perbarui([kotak(104), kotak(397)])
    assert a == b and len(set(a)) == 2


def test_pelacak_tidak_menukar_dua_wajah_dan_memberi_nomor_baru_pada_wajah_baru():
    p = P.PelacakWajah()
    a = p.perbarui([kotak(100), kotak(400)])
    b = p.perbarui([kotak(400), kotak(100)])            # urutan deteksi terbalik
    assert b == [a[1], a[0]]
    c = p.perbarui([kotak(100), kotak(400), kotak(250)])
    assert c[:2] == [a[0], a[1]] and c[2] not in a


def test_pelacak_membuang_jalur_hilang_lalu_nomor_baru_dan_reset():
    p = P.PelacakWajah(maks_hilang=2)
    a = p.perbarui([kotak(100)])
    for _ in range(3):
        p.perbarui([])
    assert p.perbarui([kotak(100)])[0] != a[0]
    p.reset()
    assert p._jalur == {}


# ---------------------------------------------------------------- foto diam
def test_foto_dikenali_dari_gerak_wajah_nol():
    sampel = rangkai(30, lambda i: [peng(1, 100, wajah=6.0), peng(2, 300, wajah=0.0)])
    foto, med = P.klasifikasi_foto(sampel)
    assert foto == {2} and med[1] == 6.0 and med[2] == 0.0


def test_jalur_pendek_dianggap_hidup_dan_none_diabaikan():
    sampel = rangkai(5, lambda i: [peng(1, 100, wajah=0.0)])
    assert P.klasifikasi_foto(sampel)[0] == set()
    sampel = rangkai(30, lambda i: [P.Pengamatan(1, kotak(100), None, None)])
    assert P.klasifikasi_foto(sampel) == (set(), {})


# ---------------------------------------------------------------- gerbang ucapan
def test_ada_ucapan_menurut_kata():
    f = P.ada_ucapan([Word("a", 1.0, 2.0), Word("b", 2.1, 3.0), Word("c", 6.0, 7.0)])
    assert f(1.5) and f(3.1) and f(6.5)
    assert not f(4.5) and not f(0.5) and not f(8.0)
    assert P.ada_ucapan(None)(123.0) is True
    assert P.ada_ucapan([])(1.0) is False


# ---------------------------------------------------------------- pembicara aktif
def dua_orang(n, bicara):
    """Orang 1 di kiri, orang 2 di kanan. bicara(i) -> 1 atau 2 (mulut yang bergerak)."""
    return rangkai(n, lambda i: [peng(1, 150, 4.0 if bicara(i) == 1 else 0.1),
                                 peng(2, 500, 4.0 if bicara(i) == 2 else 0.1)])


def test_pembicara_mengikuti_mulut_dan_pindah_dimundurkan_ke_awal_unggul():
    sampel = dua_orang(120, lambda i: 1 if i < 60 else 2)
    hasil = P.pilih_pembicara(sampel, set())
    assert hasil[0] == 1 and hasil[59] == 1
    assert hasil[60] == 2 and hasil[-1] == 2            # pindah tepat di awal, tanpa menunggu 0,8 dtk


def test_foto_tidak_pernah_dipilih_walau_mulutnya_dianggap_bergerak():
    sampel = rangkai(50, lambda i: [peng(1, 150, 0.2), peng(2, 500, 9.0)])
    assert set(P.pilih_pembicara(sampel, {2})) <= {None, 1} and P.pilih_pembicara(sampel, {2})[-1] is None
    assert set(P.pilih_pembicara(sampel, set())) == {2}


def test_tanpa_ucapan_tidak_berpindah():
    sampel = dua_orang(120, lambda i: 1 if i < 40 else 2)
    ucapan = lambda t: t < 3.5                              # hening setelah detik 3,5
    hasil = P.pilih_pembicara(sampel, set(), ucapan)
    assert hasil[30] == 1 and hasil[-1] == 1                # sesudah hening tetap pembicara terakhir


def test_ayunan_singkat_tidak_menggeser_pembicara():
    # Orang 2 unggul hanya 0,4 dtk (< 0,8 dtk) lalu kembali orang 1
    sampel = dua_orang(100, lambda i: 2 if 40 <= i < 44 else 1)
    assert set(P.pilih_pembicara(sampel, set())) == {1}


def test_pesaing_harus_unggul_dengan_margin():
    # Orang 1 berbicara dulu; lalu mulut orang 2 hanya 7,5% lebih aktif (< margin 15%): tidak pindah
    sampel = rangkai(100, lambda i: [peng(1, 150, 4.0), peng(2, 500, 0.1 if i < 40 else 4.3)])
    assert set(P.pilih_pembicara(sampel, set())) == {1}
    # Bila unggul jauh (50%), pindah
    sampel = rangkai(100, lambda i: [peng(1, 150, 4.0), peng(2, 500, 0.1 if i < 40 else 6.0)])
    assert P.pilih_pembicara(sampel, set())[-1] == 2


def test_gerak_mulut_di_bawah_ambang_bukan_berbicara():
    sampel = rangkai(50, lambda i: [peng(1, 150, 0.1), peng(2, 500, 0.2)])
    assert set(P.pilih_pembicara(sampel, set())) == {None}


def test_pergantian_kamera_mengatur_ulang_dan_langsung_pindah():
    # Setelah potong (i=50) nomor jalur baru: orang 7 (kiri) berbicara
    def f(i):
        if i < 50:
            return [peng(1, 150, 4.0), peng(2, 500, 0.1)]
        return [peng(7, 150, 0.1), peng(8, 500, 4.0)]
    hasil = P.pilih_pembicara(rangkai(100, f, potong_di={50}), set())
    assert hasil[10] == 1 and hasil[49] == 1 and hasil[50] == 8 and hasil[99] == 8


def test_pembicara_awal_adegan_diisi_mundur():
    # mulut baru aktif di i=20 -> sampel 0..19 mengikuti pembicara pertama adegan itu
    sampel = rangkai(60, lambda i: [peng(1, 150, 4.0 if i >= 20 else 0.0), peng(2, 500, 0.0)])
    hasil = P.pilih_pembicara(sampel, set())
    assert hasil[0] == 1 and hasil[19] == 1


def test_wajah_pembicara_hilang_lama_dilepas():
    sampel = rangkai(60, lambda i: [peng(1, 150, 4.0)] if i < 20 else [peng(2, 500, 0.0)])
    hasil = P.pilih_pembicara(sampel, set())
    assert hasil[10] == 1 and hasil[-1] is None


# ---------------------------------------------------------------- gerakan mendadak berskala tubuh
def test_gerak_besar_mendadak_memicu_tampilan_lebar_dengan_awal_dan_tahan():
    luas = [0.02] * 100
    for i in range(40, 55):                                 # 15% - 30% bingkai bergerak selama 1,5 dtk
        luas[i] = 0.30
    selang = P.deteksi_lonjakan(rangkai(100, lambda i: [], luas=luas))
    assert len(selang) == 1
    a, b = selang[0]
    assert a == pytest.approx(4.0 - P.AWAL_LEBAR) and b == pytest.approx(5.4 + P.TAHAN_LEBAR)


def test_gerak_kecil_saat_duduk_tidak_memicu():
    # Tangan sesekali bergerak: 6% bingkai selama 0,5 dtk (6x biasanya, tetapi areanya kecil)
    luas = [0.01] * 200
    for awal in range(20, 190, 30):
        for i in range(awal, awal + 5):
            luas[i] = 0.06
    assert P.deteksi_lonjakan(rangkai(200, lambda i: [], luas=luas)) == []
    assert P.deteksi_lonjakan(rangkai(100, lambda i: [], luas=0.03)) == []


def test_gerak_besar_yang_terus_menerus_bukan_lonjakan():
    # Luas 20% sepanjang video (misalnya latar bergerak terus): tidak ada "mendadak" terhadap sekitarnya
    assert P.deteksi_lonjakan(rangkai(100, lambda i: [], luas=0.20)) == []


def test_lonjakan_satu_sampel_diabaikan_dan_selang_singkat_diperpanjang():
    luas = [0.01] * 100
    luas[50] = 0.6
    assert P.deteksi_lonjakan(rangkai(100, lambda i: [], luas=luas)) == []
    luas = [0.01] * 100
    for i in range(50, 54):                                  # 0,4 dtk, sah tapi singkat
        luas[i] = 0.4
    (a, b), = P.deteksi_lonjakan(rangkai(100, lambda i: [], luas=luas))
    assert b - a >= P.SELANG_LEBAR_MIN - 1e-6 and a == pytest.approx(5.0 - P.AWAL_LEBAR)


def test_wajah_menerjang_cepat_memicu_walau_luas_gerak_kecil():
    # Wajah (lebar 100) melompat 40 px per 0,1 dtk = 4 lebar-wajah/dtk selama 0,5 dtk
    sampel = rangkai(100, lambda i: [peng(1, 200 + (40 * (i - 50) if 50 <= i < 55 else (200 if i < 50 else 400)))])
    selang = P.deteksi_lonjakan(sampel)
    assert len(selang) == 1 and selang[0][0] == pytest.approx(5.1 - P.AWAL_LEBAR, abs=0.15)


def test_wajah_membesar_cepat_memicu():
    # Orang maju ke kamera: kotak wajah membesar 1,4x tiap 0,1 dtk selama 0,5 dtk (sekitar 3,3 lebar-wajah/dtk)
    def ukuran(i):
        return 100 if i < 50 else min(100 * 1.4 ** (i - 49), 384) if i < 55 else 384
    sampel = rangkai(100, lambda i: [peng(1, 300, ukuran=ukuran(i))])
    assert len(P.deteksi_lonjakan(sampel)) == 1


def test_wajah_membesar_pelan_tidak_memicu():
    sampel = rangkai(100, lambda i: [peng(1, 300, ukuran=100 + i)])         # 1% per sampel
    assert P.deteksi_lonjakan(sampel) == []


def test_gerak_kepala_biasa_tidak_memicu():
    # kepala bergeser 8 px per 0,1 dtk (0,8 lebar-wajah/dtk) terus-menerus
    sampel = rangkai(100, lambda i: [peng(1, 200 + 8 * (i % 10))])
    assert P.deteksi_lonjakan(sampel) == []


def test_foto_dan_wajah_hilang_muncul_tidak_menghasilkan_kecepatan():
    sampel = rangkai(60, lambda i: [peng(1, 200 + 60 * (i % 2))])          # foto "meloncat" karena deteksi goyang
    assert max(P.kecepatan_wajah(sampel, foto={1})) == 0.0
    sampel = rangkai(60, lambda i: [peng(1, 200)] if i < 20 or i > 40 else [])
    assert max(P.kecepatan_wajah(sampel)) == 0.0                           # jeda pengamatan terlalu lama: tidak dibandingkan


def test_pergantian_kamera_tidak_dianggap_lonjakan_atau_kecepatan():
    def f(i):
        return [peng(1, 150)] if i < 50 else [peng(9, 500)]
    sampel = rangkai(100, f, potong_di={50}, luas=[0.0] * 100)
    assert max(P.kecepatan_wajah(sampel)) == 0.0 and P.deteksi_lonjakan(sampel) == []


def test_lonjakan_kosong():
    assert P.deteksi_lonjakan([]) == []


# ---------------------------------------------------------------- jalur
def test_jalur_pembicara_potong_langsung_bukan_geser():
    sampel = dua_orang(120, lambda i: 1 if i < 60 else 2)
    pembicara = P.pilih_pembicara(sampel, set())
    jalur, sasaran = P.susun_jalur(sampel, pembicara, set(), L, T, "9:16")
    xs_sebelum, xs_sesudah = jalur.pada(5.89)[0], jalur.pada(6.0)[0]
    assert xs_sebelum < 100 and xs_sesudah > 300             # loncat dalam satu sampel, tak ada geseran bertahap
    antara = [p for p in jalur.titik if 5.8 < p[0] < 6.05]
    assert max(abs(b[1] - a[1]) for a, b in zip(antara, antara[1:])) > 200
    assert sasaran[0] == pytest.approx(150 / L) and sasaran[-1] == pytest.approx(500 / L)


def test_jalur_mengabaikan_foto_saat_tidak_ada_pembicara():
    # Foto besar di tengah, orang kecil di kiri; tanpa pembicara target = wajah hidup terbesar
    sampel = rangkai(40, lambda i: [peng(1, 150, 0.0, 5.0, ukuran=60), peng(2, 330, 0.0, 0.0, ukuran=140)])
    jalur, _ = P.susun_jalur(sampel, [None] * 40, {2}, L, T, "9:16")
    x_tengah = jalur.pada(3.0)[0] + jalur.lebar_potong / 2
    assert x_tengah < 250


def test_jendela_diam_selama_wajah_di_zona_nyaman():
    # Wajah pembicara bergoyang +-25 px (zona nyaman = 20% x 202 = 40 px): jendela tidak bergerak sama sekali
    sampel = rangkai(100, lambda i: [peng(1, 320 + 25 * np.sin(i / 3.0), 0.0 + 4.0)])
    jalur, _ = P.susun_jalur(sampel, [1] * 100, set(), L, T, "9:16")
    xs = [p[1] for p in jalur.titik]
    assert max(xs) - min(xs) == 0.0


def test_jendela_mengejar_hanya_selisih_di_luar_zona():
    # Wajah pindah pelan-pelan ke x=500 dan menetap: jendela berhenti saat wajah berada di tepi zona nyaman
    sampel = rangkai(300, lambda i: [peng(1, 320 + min(180, i * 3))])
    jalur, _ = P.susun_jalur(sampel, [1] * 300, set(), L, T, "9:16")
    x_tengah = jalur.titik[-1][1] + jalur.lebar_potong / 2
    assert 500 - x_tengah == pytest.approx(P.ZONA_NYAMAN * jalur.lebar_potong, abs=2.0)
    xs = [p[1] for p in jalur.titik]
    assert all(b >= a - 1e-9 for a, b in zip(xs, xs[1:]))                   # tidak pernah mundur atau bergetar


def test_jendela_tidak_bergerak_untuk_gerak_kecil_lalu_bergerak_untuk_gerak_besar():
    sampel = rangkai(120, lambda i: [peng(1, 320 + (10 if i % 2 else -10) + (0 if i < 60 else 150))])
    jalur, _ = P.susun_jalur(sampel, [1] * 120, set(), L, T, "9:16")
    x_awal = [p[1] for p in jalur.titik[:60]]
    assert max(x_awal) == min(x_awal)
    assert jalur.titik[-1][1] > x_awal[0] + 40


def test_selang_lebar_dikosongkan_bila_jendela_sudah_seluruh_bingkai():
    sampel = rangkai(10, lambda i: [peng(1, 100)])
    jalur, _ = P.susun_jalur(sampel, [1] * 10, set(), 360, 640, "9:16", selang_lebar=[(0.0, 1.0)])
    assert jalur.selang_lebar == ()
    jalur, _ = P.susun_jalur(sampel, [1] * 10, set(), L, T, "9:16", selang_lebar=[(0.0, 1.0)])
    assert jalur.selang_lebar == ((0.0, 1.0),)


def test_jalur_dari_sampel_kosong():
    jalur, sx = P.susun_jalur([], [], set(), L, T, "9:16")
    assert jalur.titik == [] and sx == [] and jalur.persen_berwajah == 0.0


# ---------------------------------------------------------------- ketepatan
def test_ketepatan_dengan_toleransi():
    garis = [(1.0, 0.2), (2.0, 0.25), (3.0, 0.8), (4.0, None), (9.0, 0.2)]
    r = P.ketepatan(garis, [{"mulai": 0.5, "akhir": 4.5, "x": 0.2}])
    assert r == {"sampel": 4, "cocok": 2, "persen": 0.5}


def test_ketepatan_tanpa_sampel_dan_label_salah():
    assert P.ketepatan([], [{"mulai": 0, "akhir": 1, "x": 0.5}])["persen"] == 0.0
    for rusak in ("bukan daftar", [{"mulai": 0}], [1]):
        with pytest.raises(ValueError):
            P.ketepatan([(1.0, 0.5)], rusak)


# ---------------------------------------------------------------- tampilan lebar di render
def test_komposit_lebar_menaruh_bingkai_utuh_di_tengah():
    from core.render import komposit_lebar
    frame = np.full((180, 320, 3), 200, np.uint8)
    out = komposit_lebar(frame, 360, 640)
    assert out.shape == (640, 360, 3)
    assert out[320, 180].tolist() == [200, 200, 200]            # tengah = bingkai asli
    assert out[10, 180].max() < 200                             # atas = latar digelapkan


def test_dalam_selang():
    from core.render import _dalam_selang
    assert _dalam_selang(1.5, [(1.0, 2.0)]) and not _dalam_selang(2.5, [(1.0, 2.0)]) and not _dalam_selang(1, [])


# ---------------------------------------------------------------- masukan salah
def test_analisis_masukan_salah(tmp_path):
    with pytest.raises(FileNotFoundError):
        P.analisis_video(tmp_path / "x.mp4", 0, 5)
    with pytest.raises(ValueError):
        P.analisis_video(tmp_path / "x.mp4", 5, 5)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        P.analisis_video(v, 0, 5, path_model=tmp_path / "tidak_ada.onnx")


def test_terminal_gagal_kode_1(tmp_path, capsys):
    assert P.main([str(tmp_path / "x.mp4"), "--mulai", "0", "--akhir", "5"]) == 1
    assert "[GAGAL]" in capsys.readouterr().out


@pytest.mark.skipif(not (os.getenv("AUTOCLIP_VIDEO_UJI") and jalur_model().is_file()),
                    reason="butuh AUTOCLIP_VIDEO_UJI dan berkas model YuNet")
def test_analisis_nyata():
    jalur, lap = P.lacak_pembicara(os.environ["AUTOCLIP_VIDEO_UJI"], 0, 6, "9:16")
    assert jalur.titik and len(lap.pembicara_x) == len(lap.terbesar_x) > 0


# ---------------------------------------------------------------- gaya kamera campuran
def peng_mata(id_, cx, mata_y, ukuran=100):
    k = Kotak(cx - ukuran / 2, 180 - ukuran / 2, ukuran, ukuran, 0.9, mata_y)
    return P.Pengamatan(id_, k, 0.0, 5.0)


def test_gaya_lama_tidak_berubah_dan_tanpa_napas():
    sampel = rangkai(120, lambda i: [peng(1, 320)])
    jalur, _ = P.susun_jalur(sampel, [1] * 120, set(), L, T, "9:16")
    assert jalur.gaya == "lama" and jalur.selang_napas == () and jalur.titik_mata == ()


def test_campuran_memberi_napas_pada_bagian_tenang_bergantian_arah():
    sampel = rangkai(200, lambda i: [peng_mata(1, 320, 160)])          # 20 detik tenang, satu pembicara
    jalur, _ = P.susun_jalur(sampel, [1] * 200, set(), L, T, "9:16", gaya="campuran")
    assert jalur.gaya == "campuran" and len(jalur.selang_napas) == 1
    a, b, arah = jalur.selang_napas[0]
    assert a == pytest.approx(0.0) and b == pytest.approx(19.9) and arah == 1
    assert jalur.titik_mata and jalur.mata_pada(5.0) == pytest.approx(160)


def test_campuran_tanpa_napas_bila_dimatikan():
    sampel = rangkai(200, lambda i: [peng_mata(1, 320, 160)])
    jalur, _ = P.susun_jalur(sampel, [1] * 200, set(), L, T, "9:16", gaya="campuran", napas=False)
    assert jalur.selang_napas == ()


def test_napas_dipecah_di_pergantian_pembicara_dan_arah_bergantian():
    sampel = dua_orang(120, lambda i: 1 if i < 60 else 2)             # 12 detik, ganti pembicara di detik 6
    pembicara = P.pilih_pembicara(sampel, set())
    jalur, _ = P.susun_jalur(sampel, pembicara, set(), L, T, "9:16", gaya="campuran")
    assert [x[2] for x in jalur.selang_napas] == [1, -1]
    assert all(not (a < 6.0 < b) for a, b, _ in jalur.selang_napas)


def test_susun_napas_buang_bagian_pendek_tanpa_wajah_dan_tumpang_tindih():
    waktu = [i * 0.1 for i in range(200)]
    ada = [True] * 200
    assert P.susun_napas(0.0, 19.9, (), [], waktu, ada) == ((0.0, 19.9, 1),)
    assert P.susun_napas(0.0, 2.9, (), [], waktu[:30], ada[:30]) == ()                       # < NAPAS_MIN
    assert P.susun_napas(0.0, 19.9, (), [], waktu, [False] * 200) == ()                      # tanpa wajah
    hasil = P.susun_napas(0.0, 19.9, ((8.0, 10.0),), [], waktu, ada)                          # dilewati zoom/lebar
    assert [(a, b) for a, b, _ in hasil] == [(0.0, 8.0), (10.0, 19.9)]
    hasil = P.susun_napas(0.0, 19.9, (), [10.0], waktu, ada)                                  # dipecah di potongan
    assert len(hasil) == 2


def test_campuran_zona_nyaman_lebih_sempit_membuat_jendela_ikut_gerak_kecil():
    sampel = rangkai(100, lambda i: [peng(1, 320 + 40 * np.sin(i / 3.0), 0.0, 4.0)])
    lama, _ = P.susun_jalur(sampel, [1] * 100, set(), L, T, "9:16")
    baru, _ = P.susun_jalur(sampel, [1] * 100, set(), L, T, "9:16", zona_mati=P.ZONA_CAMPURAN)
    rentang = lambda j: max(p[1] for p in j.titik) - min(p[1] for p in j.titik)
    assert rentang(lama) == 0.0 and rentang(baru) > 0.0


# ---------------------------------------------------------------- tanpa wajah => tampilan lebar; wajah kecil => zoom dasar
def test_selang_tanpa_wajah_hanya_untuk_yang_cukup_lama():
    waktu = [round(i * 0.1, 3) for i in range(100)]
    ada = [not (30 <= i < 60 or 80 <= i < 83) for i in range(100)]               # 3 dtk kosong dan 0,3 dtk kosong
    assert P.selang_tanpa_wajah(waktu, ada) == [(3.0, 6.0)]
    assert P.selang_tanpa_wajah(waktu, [False] * 100) == [(0.0, 10.0)]            # kosong sampai akhir
    assert P.selang_tanpa_wajah([], []) == []


def test_campuran_tanpa_wajah_menjadi_tampilan_lebar_dan_lama_tidak_berubah():
    sampel = rangkai(100, lambda i: [peng_mata(1, 320, 160)] if i < 30 or i >= 70 else [])   # kosong detik 3,0-7,0
    campur, _ = P.susun_jalur(sampel, [1] * 100, set(), L, T, "9:16", gaya="campuran")
    assert any(a == pytest.approx(3.0) and b == pytest.approx(7.0) for a, b in campur.selang_lebar)
    assert all(not (a < 5.0 < b) for a, b, _ in campur.selang_napas)               # tidak ada zoom napas di bagian kosong
    lama, _ = P.susun_jalur(sampel, [1] * 100, set(), L, T, "9:16")
    assert lama.selang_lebar == ()


def test_campuran_wajah_hilang_sebentar_tidak_memicu_tampilan_lebar():
    sampel = rangkai(100, lambda i: [] if 40 <= i < 43 else [peng_mata(1, 320, 160)])
    jalur, _ = P.susun_jalur(sampel, [1] * 100, set(), L, T, "9:16", gaya="campuran")
    assert jalur.selang_lebar == ()


def test_campuran_wajah_kecil_diberi_zoom_dasar_dan_wajah_besar_tidak():
    kecil = rangkai(50, lambda i: [peng_mata(1, 320, 160, ukuran=40)])
    j, _ = P.susun_jalur(kecil, [1] * 50, set(), L, T, "9:16", gaya="campuran", zoom_dasar=True)
    assert j.faktor_dasar(2.0) == pytest.approx(1.77, abs=0.05) and j.faktor_pada(2.0) >= 1.7
    besar = rangkai(50, lambda i: [peng_mata(1, 320, 160, ukuran=100)])
    j2, _ = P.susun_jalur(besar, [1] * 50, set(), L, T, "9:16", gaya="campuran", zoom_dasar=True)
    assert j2.titik_dasar == () and j2.faktor_dasar(2.0) == 1.0
    lama, _ = P.susun_jalur(kecil, [1] * 50, set(), L, T, "9:16")
    mati, _ = P.susun_jalur(kecil, [1] * 50, set(), L, T, "9:16", gaya="campuran")      # bawaan: mati
    assert mati.titik_dasar == ()
    assert lama.titik_dasar == () and lama.faktor_pada(2.0) == 1.0


def test_zoom_dasar_dibatasi_dan_berpindah_mulus_antar_orang():
    sangat_kecil = rangkai(30, lambda i: [peng_mata(1, 320, 160, ukuran=10)])
    j, _ = P.susun_jalur(sangat_kecil, [1] * 30, set(), L, T, "9:16", gaya="campuran", zoom_dasar=True)
    assert j.faktor_dasar(1.0) == pytest.approx(P.MAKS_ZOOM_DASAR)
    sampel = rangkai(60, lambda i: [peng_mata(1, 320, 160, ukuran=100 if i < 30 else 40)])
    j2, _ = P.susun_jalur(sampel, [1] * 60, set(), L, T, "9:16", gaya="campuran", zoom_dasar=True)
    nilai = [f for _, f in j2.titik_dasar]
    assert max(abs(b - a) for a, b in zip(nilai, nilai[1:])) < 0.2                   # tidak loncat


# ---------------------------------------------------------------- reaksi lawan bicara; gerak halus gaya campuran
def dua_gerak(n, gerak_b):
    """Orang 1 (kiri) bicara terus; orang 2 (kanan) diam kecuali gerak_b(i) besar."""
    return rangkai(n, lambda i: [peng(1, 160, mulut=5.0, wajah=0.4), peng(2, 480, mulut=0.0, wajah=gerak_b(i))])


def test_reaksi_lawan_bicara_menjadi_cut_singkat_lalu_kembali():
    sampel = dua_gerak(120, lambda i: 8.0 if 50 <= i < 58 else 0.4)                 # gerak besar 0,8 dtk di detik 5,0
    asli = [1] * 120
    hasil = P.tambah_reaksi(sampel, asli, set())
    cut = [i for i, x in enumerate(hasil) if x == 2]
    assert cut and cut[0] == 50 and 10 <= len(cut) <= 20                            # 1-2 dtk
    assert hasil[:50] == [1] * 50 and hasil[cut[-1] + 1:] == [1] * (119 - cut[-1])


def test_reaksi_tidak_dihitung_untuk_gerak_singkat_foto_atau_pembicara_sendiri():
    singkat = dua_gerak(120, lambda i: 8.0 if 50 <= i < 53 else 0.4)                # 0,3 dtk
    assert P.tambah_reaksi(singkat, [1] * 120, set()) == [1] * 120
    besar = dua_gerak(120, lambda i: 8.0 if 50 <= i < 60 else 0.4)
    assert P.tambah_reaksi(besar, [1] * 120, {2}) == [1] * 120                      # orang 2 adalah foto
    assert P.tambah_reaksi(besar, [2] * 120, set()) == [2] * 120                    # orang 2 sudah pembicara


def test_reaksi_diberi_jarak_dan_tidak_melewati_pergantian_kamera():
    sampel = dua_gerak(200, lambda i: 8.0 if (50 <= i < 60 or 70 <= i < 80) else 0.4)   # dua reaksi berdekatan
    hasil = P.tambah_reaksi(sampel, [1] * 200, set())
    awal = [i for i in range(1, 200) if hasil[i] == 2 and hasil[i - 1] != 2]
    assert awal == [50]                                                              # yang kedua dibuang (jarak < 8 dtk)
    potong = dua_gerak(120, lambda i: 8.0 if 50 <= i < 60 else 0.4)
    potong = [P.Sampel(s.t, s.wajah, s.potong or i == 55, s.luas_gerak) for i, s in enumerate(potong)]
    hasil = P.tambah_reaksi(potong, [1] * 120, set())
    assert all(hasil[i] == 1 for i in range(55, 120))


def test_campuran_ikut_gerak_wajah_kecil_tapi_halus():
    sampel = rangkai(100, lambda i: [peng(1, 320 + 15 * np.sin(i / 6.0), 0.0, 4.0)])
    baru, _ = P.susun_jalur(sampel, [1] * 100, set(), L, T, "9:16", zona_mati=0.03, alpha=0.15)          # opsional: lebih peka, bukan bawaan
    x = [p[1] for p in baru.titik]
    assert max(x) - min(x) > 3.0                                                    # ikut gerak kecil
    assert max(abs(b - a) for a, b in zip(x, x[1:])) < 4.0                          # tanpa loncatan


# ---------------------------------------------------------------- potongan ukuran gambar (cut-to-cut)
def _jeda_kata(n=60, selang=0.3):
    return [Word("k", round(selang * i, 3), round(selang * i + 0.2, 3)) for i in range(n)]    # jeda 0,1 dtk antar kata


def test_titik_jeda_tengah_jeda_antar_kata():
    kata = [Word("a", 0.0, 0.4), Word("b", 0.5, 0.9), Word("c", 0.92, 1.3), Word("d", 2.0, 2.4)]
    assert P.titik_jeda(kata, 0.0, 3.0) == [0.45, 1.65]                    # jeda 0,02 (b-c) terlalu pendek
    assert P.titik_jeda(kata, 0.6, 1.5) == []                              # hanya jeda 0,02 di rentang ini
    assert P.titik_jeda(None, 0, 5) == []


def _jadwal(n=200, **kw):
    waktu = [round(i * 0.1, 3) for i in range(n)]
    lebar = [100.0] * n
    return waktu, P.susun_potongan(waktu, lebar, kw.pop("ganti", []), kw.pop("jeda", []), 360.0, **kw)


def test_potongan_tiap_3_sampai_5_detik_dan_ukuran_beda():
    waktu, jadwal = _jadwal(300, jeda=P.titik_jeda(_jeda_kata(), 0, 30))
    t = [a for a, _ in jadwal]
    jarak = [b - a for a, b in zip(t, t[1:])]
    assert len(jadwal) >= 5 and t[0] == 0.0
    assert all(1.9 <= j <= 6.1 for j in jarak), jarak                      # 3-5 dtk, digeser sampai +-1 dtk ke jeda kata
    faktor = [f for _, f in jadwal]
    assert all(abs(a - b) >= P.POTONGAN_BEDA_MIN - 1e-9 for a, b in zip(faktor, faktor[1:]))
    assert max(faktor) > 1.0 and min(faktor) >= 1.0 and max(faktor) <= P.MAKS_ZOOM_DASAR


def test_potongan_jatuh_di_jeda_antar_kata_bukan_tengah_kata():
    kata = _jeda_kata(120)
    jeda = P.titik_jeda(kata, 0, 35)
    _, jadwal = _jadwal(350, jeda=jeda)
    for t, _ in jadwal[1:]:
        assert any(abs(t - j) < 0.002 for j in jeda), t


def test_potongan_deterministik_dan_ikut_pergantian_pembicara():
    a = _jadwal(200, ganti=[8.0], awal_acak=7)[1]
    assert a == _jadwal(200, ganti=[8.0], awal_acak=7)[1]
    assert a != _jadwal(200, ganti=[8.0], awal_acak=8)[1]
    assert any(abs(t - 8.0) < 0.002 for t, _ in a)                          # pergantian pembicara selalu potongan


def test_potongan_dibatasi_ukuran_wajah_dan_tanpa_sampel():
    waktu = [round(i * 0.1, 3) for i in range(100)]
    besar = P.susun_potongan(waktu, [200.0] * 100, [], [], 360.0)          # wajah 200 dari jendela 360: ruang zoom sedikit
    assert all(f <= 0.62 * 360 / 200 + 1e-9 or f == 1.0 for _, f in besar)
    assert P.susun_potongan([], [], [], [], 360.0) == []


def test_titik_dari_potongan_bertangga_potongan_langsung():
    assert P.titik_dari_potongan([(0.0, 1.0), (4.0, 1.45), (8.0, 1.2)]) == \
        ((0.0, 1.0), (3.999, 1.0), (4.0, 1.45), (7.999, 1.45), (8.0, 1.2))


def test_susun_jalur_potongan_menyalakan_zoom_dasar_bertangga_dan_mematikan_zoom_tambahan():
    sampel = rangkai(120, lambda i: [peng(1, 320, mulut=3.0, ukuran=80)])
    biasa, _ = P.susun_jalur(sampel, [1] * 120, set(), L, T, "9:16", gaya="campuran", selang_zoom=[(2.0, 3.0)], faktor_zoom=1.25)
    assert biasa.titik_dasar == () and biasa.selang_zoom
    jalur, _ = P.susun_jalur(sampel, [1] * 120, set(), L, T, "9:16", gaya="campuran", selang_zoom=[(2.0, 3.0)],
                             faktor_zoom=1.25, potongan=True, waktu_jeda=P.titik_jeda(_jeda_kata(), 0, 12))
    assert jalur.titik_dasar and jalur.selang_zoom == () and jalur.selang_napas == ()
    assert len({f for _, f in jalur.titik_dasar}) >= 2
    assert jalur.faktor_dasar(0.5) == jalur.titik_dasar[0][1]
    lama, _ = P.susun_jalur(sampel, [1] * 120, set(), L, T, "9:16", gaya="lama", potongan=True)         # hanya gaya campuran
    assert lama.titik_dasar == ()
