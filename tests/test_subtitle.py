"""Pengujian core/subtitle.py dan pembakaran subtitle di render.py. Jalankan: python -m pytest tests/test_subtitle.py -v"""
import shutil

import numpy as np
import pytest

from core import render as R
from core import subtitle as S
from core.models import Word


def kata_dari(teks, mulai=0.0, durasi=0.3, jeda=0.05):
    hasil, t = [], mulai
    for w in teks.split():
        hasil.append(Word(w, round(t, 3), round(t + durasi, 3)))
        t += durasi + jeda
    return hasil


# ---------------------------------------------------------------- kata dalam klip
def test_kata_dalam_klip_hanya_yang_seluruhnya_di_dalam():
    k = [Word("a", 0.0, 0.5), Word("b", 4.8, 5.2), Word("c", 6.0, 6.4), Word("d", 10.0, 10.5)]
    assert [w.text for w in S.kata_dalam_klip(k, 5.0, 10.2)] == ["c"]
    assert [w.text for w in S.kata_dalam_klip(k, 4.8, 6.4)] == ["b", "c"]


def test_kata_rusak_dilewati():
    class Rusak:
        text, start, end = None, 1.0, 2.0
    k = [Rusak(), Word("ok", 1.0, 1.5), Word("  ", 2.0, 2.5), Word("x", float("nan"), 3.0), None, "bukan kata"]
    assert [w.text for w in S.kata_dalam_klip(k, 0, 10)] == ["ok"]
    assert S.kata_dalam_klip(None, 0, 10) == []


# ---------------------------------------------------------------- pengelompokan
def test_batas_jumlah_kata_dan_huruf():
    baris = S.kelompokkan(kata_dari("satu dua tiga empat lima enam tujuh delapan sembilan"), maks_kata=3, maks_huruf=100)
    assert all(len(b) <= 3 for b in baris) and sum(len(b) for b in baris) == 9
    baris = S.kelompokkan(kata_dari("aaaaaaaaaa bbbbbbbbbb cccccccccc"), maks_kata=10, maks_huruf=22)
    assert [len(b) for b in baris] == [2, 1]


def test_pisah_di_tanda_akhir_dan_koma():
    baris = S.kelompokkan(kata_dari("halo dunia. apa kabar, teman baik"))
    assert [[w.text for w in b] for b in baris] == [["halo", "dunia."], ["apa", "kabar,"], ["teman", "baik"]]


def test_pisah_di_jeda_panjang():
    k = kata_dari("satu dua") + kata_dari("tiga empat", mulai=5.0)
    assert [len(b) for b in S.kelompokkan(k)] == [2, 2]


def test_kata_tunggal_terlalu_panjang_tetap_tampil():
    baris = S.kelompokkan(kata_dari("super" + "x" * 40 + " ok"), maks_huruf=10)
    assert [len(b) for b in baris] == [1, 1]


def test_kelompok_kosong_dan_parameter_salah():
    assert S.kelompokkan([]) == []
    for kw in ({"maks_kata": 0}, {"maks_huruf": 0}, {"jeda": -1}):
        with pytest.raises(ValueError):
            S.kelompokkan(kata_dari("a b"), **kw)


# ---------------------------------------------------------------- ASS
def test_waktu_ass():
    assert S._waktu_ass(0) == "0:00:00.00"
    assert S._waktu_ass(61.5) == "0:01:01.50"
    assert S._waktu_ass(3725.07) == "1:02:05.07"
    assert S._waktu_ass(-3) == "0:00:00.00"


def test_ass_berisi_gaya_dan_dialog_dengan_waktu_relatif():
    k = kata_dari("halo dunia semua orang.", mulai=10.0)
    ass = S.buat_ass(k, 9.5, 14.0, 1080, 1920)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass and "[Events]" in ass
    dialog = [b for b in ass.splitlines() if b.startswith("Dialogue:")]
    assert len(dialog) == 1 and ",0:00:00.50," in dialog[0] and dialog[0].endswith("halo dunia semua orang.")


def test_ass_tanpa_kata_tetap_valid():
    ass = S.buat_ass([], 0, 5, 720, 1280)
    assert "[Events]" in ass and "Dialogue:" not in ass


def test_karakter_khusus_dinetralkan():
    ass = S.buat_ass([Word("a{b}\\c", 1.0, 1.5)], 0, 3, 720, 1280)
    teks = [b for b in ass.splitlines() if b.startswith("Dialogue:")][0].split(",,")[-1]
    assert "{" not in teks and "}" not in teks and "\\" not in teks


def test_dialog_tidak_tumpang_tindih():
    k = kata_dari("satu dua tiga empat lima enam tujuh delapan. sembilan sepuluh sebelas dua belas tiga belas.")
    ass = S.buat_ass(k, 0, 20, 1080, 1920)
    waktu = []
    for b in ass.splitlines():
        if b.startswith("Dialogue:"):
            p = b.split(",")
            waktu.append((p[1], p[2]))
    assert all(waktu[i][1] <= waktu[i + 1][0] for i in range(len(waktu) - 1))


@pytest.mark.parametrize("args", [(-1, 5, 720, 1280), (5, 5, 720, 1280), (0, 5, 1, 1280), (0, 5, 720.0, 1280),
                                  (float("nan"), 5, 720, 1280)])
def test_buat_ass_masukan_salah(args):
    with pytest.raises(ValueError):
        S.buat_ass([], *args)


# ---------------------------------------------------------------- escape jalur filter Windows
def test_jalur_filter_windows():
    assert R._jalur_filter(r"C:\Users\Arda Cinema\AppData\Local\Temp\x\sub.ass") == \
        "C\\:/Users/Arda Cinema/AppData/Local/Temp/x/sub.ass"


# ---------------------------------------------------------------- pembakaran ke video
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg tidak terpasang")
def test_subtitle_terbakar_ke_video(tmp_path):
    import cv2
    sumber = tmp_path / "v.mp4"
    w = cv2.VideoWriter(str(sumber), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 180))
    for _ in range(90):
        w.write(np.zeros((180, 320, 3), np.uint8))               # semua hitam
    w.release()
    kata = kata_dari("HALO DUNIA SEMUA", mulai=0.2, durasi=0.5)
    polos, berteks = tmp_path / "polos.mp4", tmp_path / "teks.mp4"
    R.render_klip(sumber, 0.0, 2.0, polos, rasio="9:16", lebar_keluaran=360)
    R.render_klip(sumber, 0.0, 2.0, berteks, rasio="9:16", lebar_keluaran=360, kata=kata)

    def frame(p, nomor):
        c = cv2.VideoCapture(str(p)); c.set(cv2.CAP_PROP_POS_FRAMES, nomor); ok, f = c.read(); c.release()
        assert ok
        return f
    assert frame(polos, 20).max() < 40                            # video hitam tanpa teks
    assert frame(berteks, 20).max() > 200                         # ada teks putih pada detik ~0,7
    assert frame(berteks, 20)[: 640 // 2].max() < 40              # teks di bagian bawah, atas tetap hitam


# ---------------------------------------------------------------- gaya, posisi, ukuran
def _gaya_baris(ass):
    return [b for b in ass.split("\n") if b.startswith("Style:")][0].split(",")


def test_bawaan_sama_dengan_klasik_bawah_sedang():
    k = kata_dari("HALO DUNIA SEMUA", mulai=1.0)
    assert S.buat_ass(k, 0.5, 4.0, 360, 640) == S.buat_ass(k, 0.5, 4.0, 360, 640, gaya="klasik", posisi="bawah", ukuran="sedang")


@pytest.mark.parametrize("gaya", list(S.GAYA))
def test_semua_gaya_menghasilkan_ass_valid(gaya):
    ass = S.buat_ass(kata_dari("HALO DUNIA SEMUA SAYA", mulai=1.0), 0.5, 5.0, 360, 640, gaya=gaya)
    assert "[V4+ Styles]" in ass and "Dialogue:" in ass


def test_gaya_kotak_memakai_border_style_3_dan_kuning_berwarna_kuning():
    k = kata_dari("HALO DUNIA", mulai=1.0)
    assert _gaya_baris(S.buat_ass(k, 0.5, 4.0, 360, 640, gaya="kotak"))[15] == "3"       # BorderStyle
    assert _gaya_baris(S.buat_ass(k, 0.5, 4.0, 360, 640, gaya="klasik"))[15] == "1"
    assert _gaya_baris(S.buat_ass(k, 0.5, 4.0, 360, 640, gaya="kuning"))[3] == "&H0000FFFF"


def test_sorot_satu_peristiwa_per_kata_dan_hanya_satu_kata_berwarna():
    k = kata_dari("HALO DUNIA SEMUA", mulai=1.0)
    dialog = [b for b in S.buat_ass(k, 0.5, 4.0, 360, 640, gaya="sorot").split("\n") if b.startswith("Dialogue:")]
    assert len(dialog) == 3
    for i, b in enumerate(dialog):
        teks = b.split(",,", 1)[1]
        assert teks.count("{\\1c&H0000D7FF&}") == 1                        # tepat satu kata disorot
        assert "{\\1c&H0000D7FF&}" + ["HALO", "DUNIA", "SEMUA"][i] + "{\\1c&H00FFFFFF&}" in teks
    waktu = [(b.split(",")[1], b.split(",")[2]) for b in dialog]
    assert waktu[0][1] == waktu[1][0] and waktu[1][1] == waktu[2][0]                       # berurutan, tanpa tumpang tindih


def test_posisi_dan_ukuran():
    k = kata_dari("HALO DUNIA", mulai=1.0)
    bawah, tengah, atas = (_gaya_baris(S.buat_ass(k, 0.5, 4.0, 360, 640, posisi=p)) for p in ("bawah", "tengah", "atas"))
    assert (bawah[18], tengah[18], atas[18]) == ("2", "5", "8")                            # Alignment
    kecil, sedang, besar = (int(_gaya_baris(S.buat_ass(k, 0.5, 4.0, 360, 640, ukuran=u))[2]) for u in ("kecil", "sedang", "besar"))
    assert kecil < sedang < besar


@pytest.mark.parametrize("kw", [{"gaya": "tidak ada"}, {"posisi": "kiri"}, {"ukuran": "raksasa"}])
def test_pilihan_tidak_dikenal_ditolak(kw):
    with pytest.raises(ValueError):
        S.buat_ass(kata_dari("HALO"), 0.0, 2.0, 360, 640, **kw)


def test_pilihan_subtitle_backend_sama_dengan_core():
    from backend import proyek
    assert proyek.GAYA_SUBTITLE == tuple(S.GAYA) and proyek.POSISI_SUBTITLE == S.POSISI
    assert proyek.UKURAN_SUBTITLE == tuple(S.UKURAN)
    assert proyek.ANIMASI_SUBTITLE == tuple(S.ANIMASI)
    assert proyek.SUBTITLE_BAWAAN == {"gaya": S.GAYA_BAWAAN, "posisi": "bawah", "ukuran": "sedang", "animasi": "tanpa", "aktif": True}


def test_animasi_awalan_di_depan_baris_dan_bawaan_tanpa_animasi():
    k = kata_dari("HALO DUNIA", mulai=1.0)
    polos = S.buat_ass(k, 0.5, 4.0, 360, 640)
    assert "\\fad" not in polos and "\\t(" not in polos
    assert ",,{\\fad(140,0)}HALO DUNIA" in S.buat_ass(k, 0.5, 4.0, 360, 640, animasi="pudar")
    assert ",,{\\fscx70\\fscy70\\t(0,130,\\fscx100\\fscy100)}HALO DUNIA" in S.buat_ass(k, 0.5, 4.0, 360, 640, animasi="muncul")
    with pytest.raises(ValueError):
        S.buat_ass(k, 0.5, 4.0, 360, 640, animasi="melayang")


def test_animasi_sorot_hanya_pada_kata_pertama_baris():
    k = kata_dari("HALO DUNIA SEMUA", mulai=1.0)
    dialog = [b for b in S.buat_ass(k, 0.5, 4.0, 360, 640, gaya="sorot", animasi="pudar").split("\n") if b.startswith("Dialogue:")]
    assert "\\fad" in dialog[0] and "\\fad" not in dialog[1] and "\\fad" not in dialog[2]
