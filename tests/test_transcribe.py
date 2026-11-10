"""Pengujian core/transcribe.py tanpa Whisper dan tanpa video (model tiruan).

Jalankan dari folder proyek:  python -m pytest tests/test_transcribe.py -v

Tes dengan model SUNGGUHAN (butuh video) hanya berjalan bila variabel lingkungan
AUTOCLIP_VIDEO_UJI berisi jalur sebuah berkas video atau audio.
"""
import os
from types import SimpleNamespace as NS

import pytest

from core import transcribe as T
from core.models import Word
from core.segments import build_candidates, split_sentences


def kw(teks, mulai, akhir):
    """Kata tiruan berbentuk keluaran faster-whisper (atribut word, start, end)."""
    return NS(word=teks, start=mulai, end=akhir, probability=0.9)


def seg(*kata):
    return NS(words=list(kata))


class ModelTiruan:
    def __init__(self, segmen, bahasa="id", prob=0.97, durasi=12.5):
        self.segmen, self.info = segmen, NS(language=bahasa, language_probability=prob, duration=durasi)
        self.panggilan = []

    def transcribe(self, path, **kwargs):
        self.panggilan.append((path, kwargs))
        return iter(self.segmen), self.info


@pytest.fixture
def media(tmp_path):
    f = tmp_path / "contoh.mp4"
    f.write_bytes(b"bukan video sungguhan")
    return f


@pytest.fixture
def pasang_model(monkeypatch):
    def _pasang(model):
        monkeypatch.setattr(T, "_buat_model", lambda *a, **k: model)
        return model
    return _pasang


# ---------------------------------------------------------------- pembersihan kata
def test_spasi_di_tepi_dibuang_dan_tanda_baca_dipertahankan():
    kata, dibuang = T.kumpulkan_kata([seg(kw(" Halo,", 0.0, 0.4), kw(" dunia.", 0.5, 0.9))])
    assert [k.text for k in kata] == ["Halo,", "dunia."]
    assert dibuang == 0


def test_kata_kosong_dan_waktu_tidak_valid_dibuang_dan_dihitung():
    segmen = [seg(
        kw("ok", 0.0, 0.3),
        kw("   ", 0.4, 0.5),                    # kosong
        kw("a", None, 1.0),                      # mulai kosong
        kw("b", float("nan"), 1.0),              # NaN
        kw("c", -1.0, 0.5),                      # negatif
        kw("d", 2.0, 1.0),                       # akhir sebelum mulai
        kw(None, 3.0, 3.5),                      # teks bukan string
        kw("bagus", 4.0, 4.4),
    )]
    kata, dibuang = T.kumpulkan_kata(segmen)
    assert [k.text for k in kata] == ["ok", "bagus"]
    assert dibuang == 6


def test_segmen_tanpa_kata_atau_bentuk_aneh_tidak_membuat_crash():
    kata, dibuang = T.kumpulkan_kata([NS(words=None), NS(), seg(), seg(kw("x", 0, 1))])
    assert [k.text for k in kata] == ["x"] and dibuang == 0


def test_timestamp_dibulatkan_tiga_desimal():
    kata, _ = T.kumpulkan_kata([seg(kw("a", 0.123456, 0.987654))])
    assert (kata[0].start, kata[0].end) == (0.123, 0.988)


# ---------------------------------------------------------------- statistik waktu
def test_statistik_tumpang_tindih_dan_jeda():
    kata = [Word("a", 0.0, 1.0), Word("b", 0.8, 1.5), Word("c", 3.0, 3.4), Word("d", 3.1, 3.5)]
    st = T.statistik_waktu(kata)
    assert st.jumlah_kata == 4
    assert st.jumlah_tumpang_tindih == 2
    assert st.tumpang_tindih_maks == pytest.approx(0.3)
    assert st.jeda_terpanjang == pytest.approx(1.5)
    assert st.jumlah_mundur == 0


def test_statistik_kata_mundur_dan_masukan_kosong():
    assert T.statistik_waktu([Word("a", 5.0, 5.4), Word("b", 1.0, 1.4)]).jumlah_mundur == 1
    st = T.statistik_waktu([])
    assert (st.jumlah_kata, st.jumlah_tumpang_tindih, st.jeda_terpanjang) == (0, 0, 0.0)


# ---------------------------------------------------------------- JSON
def test_json_bolak_balik_sama():
    kata = [Word("Halo,", 0.0, 0.4), Word("dunia.", 0.5, 0.9), Word("café", 1.0, 1.2)]
    assert T.dari_json(T.ke_json(kata)) == kata


def test_format_json_sesuai_kolom_transcripts():
    import json
    assert json.loads(T.ke_json([Word("a", 0.0, 1.0)])) == [{"w": "a", "s": 0.0, "e": 1.0}]


@pytest.mark.parametrize("rusak", ["bukan json", "{}", "[1, 2]", '[{"w": "a"}]', "null"])
def test_json_rusak_memunculkan_value_error(rusak):
    with pytest.raises(ValueError):
        T.dari_json(rusak)


# ---------------------------------------------------------------- transkripsi dengan model tiruan
def test_transkripsi_mengembalikan_kata_dan_info(media, pasang_model):
    model = pasang_model(ModelTiruan([seg(kw(" Halo", 0.0, 0.4), kw(" dunia.", 0.5, 0.9))]))
    hasil = T.transkripsi(media, bahasa="id", ukuran_model="base")
    assert [k.text for k in hasil.kata] == ["Halo", "dunia."]
    assert (hasil.bahasa, hasil.model, hasil.durasi) == ("id", "base", 12.5)
    assert hasil.probabilitas_bahasa == pytest.approx(0.97)
    assert hasil.kata_dibuang == 0 and hasil.detik_proses >= 0
    path, opsi = model.panggilan[0]
    assert path == str(media)
    assert opsi["language"] == "id" and opsi["word_timestamps"] is True and opsi["vad_filter"] is True


def test_bahasa_otomatis_bila_tidak_diisi(media, pasang_model):
    model = pasang_model(ModelTiruan([seg(kw("x.", 0, 1))], bahasa="en"))
    hasil = T.transkripsi(media)
    assert model.panggilan[0][1]["language"] is None
    assert hasil.bahasa == "en"


def test_berkas_tidak_ada_memunculkan_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        T.transkripsi(tmp_path / "tidak_ada.mp4")


def test_ukuran_model_tidak_dikenal_memunculkan_value_error(media):
    with pytest.raises(ValueError):
        T.transkripsi(media, ukuran_model="raksasa")


def test_media_tanpa_ucapan_menghasilkan_daftar_kosong(media, pasang_model):
    pasang_model(ModelTiruan([], durasi=5.0))
    hasil = T.transkripsi(media)
    assert hasil.kata == [] and hasil.durasi == 5.0


# ---------------------------------------------------------------- pengaturan
def test_pengaturan_bawaan(monkeypatch):
    for nama in ("WHISPER_MODEL", "WHISPER_THREADS", "WHISPER_COMPUTE", "MODEL_DIR"):
        monkeypatch.delenv(nama, raising=False)
    monkeypatch.setattr(T, "BASE", T.BASE / "folder_yang_tidak_ada")     # .env sungguhan tidak ikut terbaca
    p = T.baca_pengaturan()
    assert p == {"model": "small", "threads": 4, "compute": "int8", "model_dir": None}


def test_pengaturan_dari_lingkungan_dan_nilai_salah_kembali_ke_bawaan(monkeypatch):
    monkeypatch.setattr(T, "BASE", T.BASE / "folder_yang_tidak_ada")
    monkeypatch.setenv("WHISPER_MODEL", " BASE ")
    monkeypatch.setenv("WHISPER_THREADS", "abc")
    monkeypatch.setenv("MODEL_DIR", "D:/cache/whisper")
    p = T.baca_pengaturan()
    assert p["model"] == "base" and p["threads"] == 4 and p["model_dir"] == "D:/cache/whisper"
    monkeypatch.setenv("WHISPER_THREADS", "-2")
    assert T.baca_pengaturan()["threads"] == 4


# ---------------------------------------------------------------- antarmuka terminal
def test_terminal_menyimpan_json_dan_mencetak_ringkasan(media, pasang_model, tmp_path, capsys):
    pasang_model(ModelTiruan([seg(kw(" Halo", 0.0, 0.4), kw(" dunia.", 0.3, 0.9))], durasi=2.0))
    tujuan = tmp_path / "hasil" / "kata.json"
    kode = T.main([str(media), "--bahasa", "id", "--simpan", str(tujuan)])
    keluar = capsys.readouterr().out
    assert kode == 0
    assert "Jumlah kata      : 2" in keluar and "Tumpang tindih   : 1 pasangan" in keluar
    assert [k.text for k in T.dari_json(tujuan.read_text(encoding="utf-8"))] == ["Halo", "dunia."]


def test_terminal_berkas_tidak_ada_mengembalikan_kode_1(tmp_path, capsys):
    assert T.main([str(tmp_path / "tidak_ada.mp4")]) == 1
    assert "[GAGAL]" in capsys.readouterr().out


# ---------------------------------------------------------------- sambungan ke modul lain
def test_keluaran_dapat_diteruskan_ke_segments(media, pasang_model):
    """Rantai: transkripsi tiruan -> split_sentences -> build_candidates."""
    kata, t = [], 0.0
    for i in range(300):
        kata.append(kw(" kata" + str(i) + ("." if i % 10 == 9 else ""), t, t + 0.35))
        t += 0.4
    pasang_model(ModelTiruan([seg(*kata)], durasi=t))
    hasil = T.transkripsi(media, bahasa="id")
    kalimat = split_sentences(hasil.kata)
    assert len(kalimat) == 30
    assert build_candidates(kalimat), "seharusnya terbentuk calon clip"


# ---------------------------------------------------------------- model sungguhan (opsional)
@pytest.mark.skipif(not os.getenv("AUTOCLIP_VIDEO_UJI"), reason="set AUTOCLIP_VIDEO_UJI ke jalur video untuk menjalankan")
def test_transkripsi_nyata():
    hasil = T.transkripsi(os.environ["AUTOCLIP_VIDEO_UJI"], bahasa=os.getenv("AUTOCLIP_BAHASA_UJI") or None)
    assert hasil.kata and hasil.durasi > 0
    assert all(isinstance(k, Word) for k in hasil.kata)
