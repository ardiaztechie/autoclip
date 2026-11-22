"""Tes core.varian (perbaikan B, EKSPERIMENTAL): beberapa panjang calon per titik awal."""
import json

import pytest

from core.models import Sentence, Word
from core.pipeline import jalankan_rantai, main as pipeline_main
from core.segments import build_candidates, split_sentences
from core.varian import JUMLAH_BAND_BAWAAN, _persentil_tengah, build_candidates_varian, kualitas_batas


def _kalimat(spek, dur=3.0):
    """spek: daftar dict(awal='kata', akhir='x.', jeda=0.3) -> list[Sentence].
    jeda = jeda SEBELUM kalimat itu. Tiap kalimat 4 kata."""
    hasil, t = [], 0.0
    for s in spek:
        t += s.get("jeda", 0.3)
        langkah = dur / 4
        teks = [s.get("awal", "kata"), "x", "x", s.get("akhir", "akhir.")]
        kata = [Word(teks[i], round(t + i * langkah, 4), round(t + i * langkah + 0.9 * langkah, 4)) for i in range(4)]
        hasil.append(Sentence(kata))
        t = kata[-1].end
    return hasil


def _seragam(n, **kw):
    return _kalimat([dict(kw) for _ in range(n)])


def _idx_dalam(kal, awal, lo, hi):
    return [i for i in range(awal, len(kal)) if lo <= kal[i].end - kal[awal].start < hi]


def _band(durasi, min_sec=20, max_sec=60, k=4):
    return min(k - 1, int((durasi - min_sec) / ((max_sec - min_sec) / k)))


# --- bentuk dasar -------------------------------------------------------------
def test_paling_banyak_satu_calon_per_pita_dan_pita_berbeda():
    kal = _seragam(60)
    calon = build_candidates_varian(kal, jumlah_band=4, jeda_maks_calon=None)
    per_awal = {}
    for c in calon:
        per_awal.setdefault(c.start, []).append(c)
    assert per_awal
    for cs in per_awal.values():
        assert len(cs) <= 4
        pita = [_band(c.duration) for c in cs]
        assert len(pita) == len(set(pita))


def test_semua_calon_dalam_rentang_dan_di_batas_kalimat():
    kal = _seragam(60)
    awal = {s.start for s in kal}
    akhir = {s.end for s in kal}
    calon = build_candidates_varian(kal)
    assert calon
    assert all(20 <= c.duration <= 60 for c in calon)
    assert all(c.start in awal and c.end in akhir for c in calon)


def test_menghasilkan_klip_jauh_lebih_panjang_daripada_mode_lama():
    """Inti perbaikan B: versi 50-60 dtk dari gagasan yang sama ikut menjadi calon."""
    kal = _seragam(60)
    lama = build_candidates(kal, jeda_maks_calon=None)
    baru = build_candidates_varian(kal, jeda_maks_calon=None)
    assert max(c.duration for c in lama) < 35
    assert max(c.duration for c in baru) >= 50


def test_satu_pita_memberi_satu_calon_per_awal():
    kal = _seragam(60)
    calon = build_candidates_varian(kal, jumlah_band=1, jeda_maks_calon=None)
    awal = [c.start for c in calon]
    assert len(awal) == len(set(awal))


# --- pemilihan titik akhir berdasarkan kualitas batas ----------------------------
def _spek_dengan(target, ubah, n=14):
    """Kalimat seragam; kalimat ke-`target` diubah dengan dict `ubah` (kunci kalimat itu)."""
    spek = [dict(akhir="x") for _ in range(n)]       # tanpa tanda baca, jeda sama
    spek[target].update(ubah)
    return spek


def test_memilih_titik_akhir_dengan_tanda_baca_dan_jeda_panjang():
    kal0 = _kalimat([dict(akhir="x") for _ in range(14)])
    dalam = _idx_dalam(kal0, 0, 20, 30)
    assert len(dalam) >= 3
    target = dalam[1]                                  # bukan yang paling awal di pita
    spek = [dict(akhir="x") for _ in range(14)]
    spek[target] = dict(akhir="selesai.")
    spek[target + 1] = dict(akhir="x", jeda=2.5)       # jeda panjang SESUDAH kalimat target
    kal = _kalimat(spek)
    calon = build_candidates_varian(kal, jumlah_band=4, jeda_maks_calon=None)
    pita0 = [c for c in calon if c.start == kal[0].start and 20 <= c.duration < 30]
    assert len(pita0) == 1
    assert pita0[0].end == kal[target].end


def test_seri_memilih_yang_lebih_pendek():
    kal = _seragam(40, akhir="x")                      # semua titik akhir setara
    calon = build_candidates_varian(kal, jumlah_band=4, jeda_maks_calon=None)
    pita0 = [c for c in calon if c.start == kal[0].start and 20 <= c.duration < 30]
    pertama = _idx_dalam(kal, 0, 20, 30)[0]
    assert pita0[0].end == kal[pertama].end


def test_kalimat_yang_berakhir_kata_menggantung_dihindari():
    kal0 = _kalimat([dict(akhir="x") for _ in range(14)])
    dalam = _idx_dalam(kal0, 0, 20, 30)
    pertama = dalam[0]
    spek = [dict(akhir="itu.") for _ in range(14)]
    spek[pertama] = dict(akhir="yang.")                # bertanda baca TAPI menggantung
    kal = _kalimat(spek)
    calon = build_candidates_varian(kal, jumlah_band=4, jeda_maks_calon=None)
    pita0 = [c for c in calon if c.start == kal[0].start and 20 <= c.duration < 30]
    assert pita0[0].end == kal[dalam[1]].end


def test_kalimat_berikutnya_pembuka_penerus_gagasan_dihindari():
    kal0 = _kalimat([dict(akhir="x") for _ in range(14)])
    dalam = _idx_dalam(kal0, 0, 20, 30)
    pertama = dalam[0]
    spek = [dict(akhir="itu.") for _ in range(14)]
    spek[pertama + 1] = dict(akhir="itu.", awal="tapi")  # kalimat sesudah titik akhir pertama
    kal = _kalimat(spek)
    calon = build_candidates_varian(kal, jumlah_band=4, jeda_maks_calon=None)
    pita0 = [c for c in calon if c.start == kal[0].start and 20 <= c.duration < 30]
    assert pita0[0].end != kal[pertama].end
    assert pita0[0].end == kal[dalam[1]].end


def test_jeda_dinilai_relatif_terhadap_sebaran_video():
    """Jeda 1,0 dtk yang sama: tinggi bila jeda lain kecil, rendah bila jeda lain besar."""
    def video(jeda_lain):
        spek = [dict(akhir="x", jeda=jeda_lain) for _ in range(10)]
        spek[5] = dict(akhir="x", jeda=1.0)            # jeda sebelum kalimat 5
        return _kalimat(spek)
    q_a = kualitas_batas(video(0.1))[4]                # kalimat 4 diikuti jeda 1,0
    q_b = kualitas_batas(video(3.0))[4]
    assert q_a > q_b


def test_kualitas_batas_dalam_rentang_nol_satu_dan_kalimat_terakhir_tinggi():
    kal = _seragam(10)
    q = kualitas_batas(kal)
    assert len(q) == len(kal) and all(0.0 <= x <= 1.0 for x in q)
    assert q[-1] >= max(q[:-1])


# --- aturan A tetap berlaku -----------------------------------------------------
def test_calon_tidak_melintasi_jeda_panjang_dan_bisa_dimatikan():
    spek = [dict(akhir="x") for _ in range(24)]
    spek[12] = dict(akhir="x", jeda=30.0)
    kal = _kalimat(spek)
    a, b = kal[11].end, kal[12].start
    aktif = build_candidates_varian(kal, jeda_maks_calon=10)
    mati = build_candidates_varian(kal, jeda_maks_calon=None)
    assert aktif and not any(c.start < a and c.end > b for c in aktif)
    assert any(c.start < a and c.end > b for c in mati)


def test_awal_tepat_setelah_jeda_panjang_tetap_dipakai():
    spek = [dict(akhir="x") for _ in range(24)]
    spek[12] = dict(akhir="x", jeda=30.0)
    kal = _kalimat(spek)
    calon = build_candidates_varian(kal, jeda_maks_calon=10)
    assert any(c.start == kal[12].start for c in calon)


def test_persentil_tengah_menghitung_nilai_seri_setengah():
    assert _persentil_tengah(1.0, [1.0, 1.0, 1.0, 1.0]) == pytest.approx(0.5)
    assert _persentil_tengah(2.0, [1.0, 2.0, 3.0]) == pytest.approx(0.5)
    assert _persentil_tengah(0.5, [1.0, 2.0]) == 0.0
    assert _persentil_tengah(5.0, [1.0, 2.0]) == 1.0
    assert _persentil_tengah(1.0, []) == 0.0


# --- toleransi ----------------------------------------------------------------
def _spek_toleransi(kualitas_tinggi: bool):
    kal0 = _kalimat([dict(akhir="x") for _ in range(30)])
    atas = [i for i in range(30) if 60 < kal0[i].end - kal0[0].start <= 65]
    assert len(atas) >= 1
    target = atas[0]
    spek = [dict(akhir="x") for _ in range(30)]
    if kualitas_tinggi:
        spek[target] = dict(akhir="selesai.")
        spek[target + 1] = dict(akhir="x", jeda=2.5)
    return spek, target


def test_toleransi_mati_secara_bawaan():
    spek, _ = _spek_toleransi(True)
    kal = _kalimat(spek)
    calon = build_candidates_varian(kal, jeda_maks_calon=None)
    assert all(c.duration <= 60 for c in calon)


def test_toleransi_dipakai_hanya_untuk_batas_berkualitas_tinggi():
    spek, target = _spek_toleransi(True)
    kal = _kalimat(spek)
    calon = build_candidates_varian(kal, jeda_maks_calon=None, toleransi_sec=5.0)
    atas = [c for c in calon if c.start == kal[0].start and c.duration > 60]
    assert len(atas) == 1 and atas[0].end == kal[target].end
    assert all(c.duration <= 65 for c in calon)

    spek_buruk, _ = _spek_toleransi(False)
    kal_buruk = _kalimat(spek_buruk)
    calon_buruk = build_candidates_varian(kal_buruk, jeda_maks_calon=None, toleransi_sec=5.0)
    assert all(c.duration <= 60 for c in calon_buruk)


# --- masukan -----------------------------------------------------------------
def test_masukan_kosong_atau_terlalu_pendek_tidak_crash():
    assert build_candidates_varian([]) == []
    assert build_candidates_varian(_seragam(3)) == []


def test_min_sama_dengan_max_tidak_crash():
    kal = _seragam(40)
    calon = build_candidates_varian(kal, min_sec=20, max_sec=20, jeda_maks_calon=None)
    assert all(c.duration <= 20 for c in calon)


@pytest.mark.parametrize("kw", [
    dict(min_sec=30, max_sec=20), dict(jumlah_band=0), dict(jumlah_band=-1), dict(jumlah_band=2.5),
    dict(jumlah_band=True), dict(jeda_maks_calon=0), dict(jeda_maks_calon=-1),
    dict(toleransi_sec=-1), dict(q_toleransi=1.5), dict(q_toleransi=-0.1),
])
def test_parameter_tidak_valid_ditolak(kw):
    with pytest.raises(ValueError):
        build_candidates_varian(_seragam(10), **kw)


def test_bawaan():
    assert JUMLAH_BAND_BAWAAN == 4


# --- rantai pipeline ---------------------------------------------------------
def _kata_dari(kal):
    return [w for s in kal for w in s.words]


def test_rantai_mode_lama_sama_dengan_perilaku_sebelumnya_dan_varian_beda():
    kata = _kata_dari(_seragam(80, akhir="selesai."))
    lama = jalankan_rantai(kata, n=3)
    varian = jalankan_rantai(kata, n=3, mode_calon="varian")
    kal = split_sentences(kata)
    assert lama.jumlah_calon == len(build_candidates(kal))
    assert varian.jumlah_calon == len(build_candidates_varian(kal))
    assert varian.jumlah_calon != lama.jumlah_calon


def test_mode_calon_tidak_dikenal_ditolak():
    with pytest.raises(ValueError):
        jalankan_rantai(_kata_dari(_seragam(40)), mode_calon="ngawur")


def test_terminal_mode_varian_berjalan(tmp_path, capsys):
    kata = _kata_dari(_seragam(80, akhir="selesai."))
    berkas = tmp_path / "kata.json"
    berkas.write_text(json.dumps([{"w": k.text, "s": k.start, "e": k.end} for k in kata]), encoding="utf-8")
    assert pipeline_main([str(berkas)]) == 0
    lama = capsys.readouterr().out
    assert pipeline_main([str(berkas), "--mode-calon", "varian", "--varian", "5", "--toleransi", "5"]) == 0
    baru = capsys.readouterr().out
    assert "Calon clip" in baru and baru != lama
