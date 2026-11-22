"""Tes core/metadata.py (judul, caption, hashtag versi aturan). Data buatan, bukan hasil video nyata."""
import json

import pytest

from core import metadata
from core.models import Word
from core.scoring import build_idf
from core.segments import split_sentences


def _kata(teks: str, mulai: float = 0.0, dur: float = 0.4, jeda: float = 0.05) -> list:
    """Mengubah teks jadi daftar Word berurutan (tiap token satu kata, waktu tetap)."""
    hasil, t = [], mulai
    for w in teks.split():
        hasil.append(Word(w, round(t, 3), round(t + dur, 3)))
        t += dur + jeda
    return hasil


KORPUS = ("Kalau gaji kita tinggi tapi pengeluaran juga tinggi. Itu bukan masalah penghasilan. "
          "Masalahnya adalah kebiasaan menabung yang buruk. Disiplin keuangan itu penting sekali. "
          "Kenapa banyak orang gagal menabung? Karena mereka tidak punya tujuan keuangan yang jelas. "
          "Investasi reksadana cocok untuk pemula. Reksadana itu mudah dan murah. "
          "Tentukan tujuan keuangan dulu sebelum investasi. Setelah itu baru pilih instrumen. "
          "Disiplin menabung setiap bulan jauh lebih penting. Jangan menunggu kaya baru mulai.")


def test_judul_kalimat_pertama_dan_huruf_besar():
    assert metadata.buat_judul(["kenapa banyak orang gagal menabung?", "lain"]) == "Kenapa banyak orang gagal menabung?"


def test_judul_dipotong_dengan_titik_tiga():
    j = metadata.buat_judul(["satu dua tiga empat lima enam tujuh delapan sembilan sepuluh sebelas dua belas tiga belas empat belas"])
    assert j.endswith("…") and len(j.rstrip("…").split()) == metadata.MAKS_KATA_JUDUL


def test_judul_titik_akhir_dibuang_tanya_dipertahankan():
    assert metadata.buat_judul(["Ini kalimat biasa."]) == "Ini kalimat biasa"
    assert metadata.buat_judul(["Benarkah begitu?"]).endswith("?")


def test_judul_kosong():
    assert metadata.buat_judul([]) == ""
    assert metadata.buat_judul(["   ", ""]) == ""


def test_judul_melewati_kalimat_kosong():
    assert metadata.buat_judul(["", "  ", "isi pertama"]) == "Isi pertama"


def test_hashtag_istilah_khas_tanpa_kata_umum_dan_pengisi():
    model = build_idf(split_sentences(_kata(KORPUS)))
    tag = metadata.pilih_hashtag(["eh anu reksadana itu yang untuk dengan reksadana pemula investasi"], model)
    assert tag and all(t.startswith("#") for t in tag)
    isi = {t[1:] for t in tag}
    assert "reksadana" in isi and "investasi" in isi
    assert not isi & (metadata.KATA_UMUM | {"anu", "eh"})


def test_hashtag_tanpa_angka_dan_tanpa_duplikat():
    model = build_idf(split_sentences(_kata(KORPUS)))
    tag = metadata.pilih_hashtag(["reksadana 2024 reksadana reksadana-bagus tabungan tabungan"], model, 5)
    assert "#2024" not in tag and len(tag) == len(set(tag))


def test_hashtag_jumlah_dibatasi_dan_kosong_bila_tidak_ada_istilah():
    model = build_idf(split_sentences(_kata(KORPUS)))
    assert len(metadata.pilih_hashtag([KORPUS], model, 3)) == 3
    assert metadata.pilih_hashtag(["yang dan itu"], model) == []
    assert metadata.pilih_hashtag([], model) == []


def test_hashtag_urutan_deterministik():
    model = build_idf(split_sentences(_kata(KORPUS)))
    a = metadata.pilih_hashtag([KORPUS], model)
    assert a == metadata.pilih_hashtag([KORPUS], model)


def test_caption_kalimat_awal_plus_hashtag():
    c = metadata.buat_caption(["kalimat satu.", "kalimat dua."], ["#a", "#b"])
    assert c == "Kalimat satu. kalimat dua.\n\n#a #b"


def test_caption_dibatasi_huruf_pada_batas_kalimat():
    k = ["a" * 70, "b" * 70, "c" * 70]
    c = metadata.buat_caption(k, [], maks_huruf=150)
    assert len(c) <= 150 and "c" * 70 not in c


def test_caption_kalimat_pertama_terlalu_panjang_dipotong_di_batas_kata():
    c = metadata.buat_caption(["kata " * 100], [], maks_huruf=50)
    assert c.endswith("…") and len(c) <= 51 and "kat…" not in c


def test_caption_tanpa_hashtag_atau_tanpa_isi():
    assert metadata.buat_caption(["halo."], []) == "Halo."
    assert metadata.buat_caption([], ["#a"]) == "#a"
    assert metadata.buat_caption([], []) == ""


def test_kata_dalam_rentang():
    kata = _kata("a b c d e f", dur=1.0, jeda=0.0)   # a:0-1, b:1-2, ...
    assert [k.text for k in metadata.kata_dalam_rentang(kata, 1.0, 4.0)] == ["b", "c", "d"]


def test_buat_metadata_satu_klip():
    kata = _kata(KORPUS)
    akhir = kata[-1].end
    hasil = metadata.buat_metadata(kata, [{"mulai": 0.0, "akhir": akhir}])
    assert len(hasil) == 1
    m = hasil[0]
    assert m["nomor"] == 1 and m["judul"] and m["caption"] and isinstance(m["hashtag"], list)
    assert m["judul"].startswith("Kalau gaji kita")


def test_buat_metadata_dua_klip_urut_dan_berbeda():
    kata = _kata(KORPUS)
    pertengahan = kata[len(kata) // 2].start
    hasil = metadata.buat_metadata(kata, [{"mulai": 0.0, "akhir": pertengahan}, {"mulai": pertengahan - 0.01, "akhir": kata[-1].end}])
    assert [m["nomor"] for m in hasil] == [1, 2]
    assert hasil[0]["judul"] != hasil[1]["judul"]


def test_buat_metadata_rentang_tanpa_kata_menghasilkan_kosong():
    hasil = metadata.buat_metadata(_kata(KORPUS), [{"mulai": 5000.0, "akhir": 5030.0}])
    assert hasil[0]["judul"] == "" and hasil[0]["hashtag"] == [] and hasil[0]["caption"] == ""


def test_buat_metadata_tanpa_kata():
    hasil = metadata.buat_metadata([], [{"mulai": 0.0, "akhir": 30.0}])
    assert hasil[0]["judul"] == ""


def test_main_menulis_berkas(tmp_path):
    kata = _kata(KORPUS)
    (tmp_path / "kata.json").write_text(json.dumps([{"w": k.text, "s": k.start, "e": k.end} for k in kata]), encoding="utf-8")
    (tmp_path / "klip.json").write_text(json.dumps([{"mulai": 0.0, "akhir": kata[-1].end}]), encoding="utf-8")
    out = tmp_path / "metadata.json"
    assert metadata.main([str(tmp_path / "kata.json"), str(tmp_path / "klip.json"), "--simpan", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["judul"] and "hashtag" in data[0]


def test_main_gagal_bila_berkas_tidak_ada_atau_bentuk_salah(tmp_path, capsys):
    assert metadata.main([str(tmp_path / "x.json"), str(tmp_path / "y.json")]) == 1
    (tmp_path / "kata.json").write_text("[]", encoding="utf-8")
    (tmp_path / "klip.json").write_text('{"bukan": "daftar"}', encoding="utf-8")
    assert metadata.main([str(tmp_path / "kata.json"), str(tmp_path / "klip.json")]) == 1
    assert "[GAGAL]" in capsys.readouterr().out


def test_hashtag_urutan_menurut_porsi_dan_kekhasan():
    # "jangan" 3 dari 4 istilah dan jarang di korpus; "disiplin" 1 dari 4 dan lebih umum -> jangan harus pertama
    model = build_idf(split_sentences(_kata(KORPUS)))
    tag = metadata.pilih_hashtag(["jangan jangan jangan disiplin"], model, 2)
    assert tag == ["#jangan", "#disiplin"]


def test_hashtag_hanya_huruf_tanpa_tanda_hubung():
    model = build_idf(split_sentences(_kata(KORPUS)))
    tag = metadata.pilih_hashtag(["reksadana-bagus reksadana-bagus tabungan2024 reksadana"], model, 5)
    assert tag == ["#reksadana"]
    assert all(t[1:].isalpha() for t in tag)


def test_kata_dalam_rentang_toleransi_kecil_saja():
    kata = [Word("hampir", 0.97, 1.5), Word("dalam", 1.5, 2.0), Word("jauh", 0.5, 1.2), Word("luar", 2.0, 2.2)]
    ada = [k.text for k in metadata.kata_dalam_rentang(kata, 1.0, 2.0)]
    assert ada == ["hampir", "dalam"]


def test_hashtag_kata_pemancing_bukan_topik():
    model = build_idf(split_sentences(_kata(KORPUS)))
    tag = metadata.pilih_hashtag(["kenapa ternyata penting reksadana reksadana"], model, 5)
    assert tag == ["#reksadana"]


def test_judul_dipotong_di_koma_terakhir_bila_cukup_panjang():
    teks = "Jadi yang harus di fokus kan bukanlah apa yang kita kerjakan, melainkan bagaimana cara kita approaching work"
    assert metadata.buat_judul([teks]) == "Jadi yang harus di fokus kan bukanlah apa yang kita kerjakan"


def test_judul_koma_terlalu_awal_tidak_dipakai():
    teks = "Jadi, yang harus difokuskan bukanlah apa yang kita kerjakan melainkan bagaimana cara kita bekerja sehari-hari"
    j = metadata.buat_judul([teks])
    assert j.endswith("…") and j.startswith("Jadi, yang")


def test_caption_tidak_berakhir_koma():
    c = metadata.buat_caption(["Kalau kamu tidak suka posisimu sekarang,"], ["#a"])
    assert c.splitlines()[0] == "Kalau kamu tidak suka posisimu sekarang"


def test_hashtag_kata_keterangan_umum_tidak_ikut():
    model = build_idf(split_sentences(_kata(KORPUS)))
    tag = metadata.pilih_hashtag(["pun selalu semakin bilang kalian reksadana reksadana"], model, 5)
    assert tag == ["#reksadana"]
