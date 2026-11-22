"""Tes core/jalankan.py: urutan langkah, argumen yang diteruskan, dan penghentian saat gagal.
Langkah asli (Whisper, FFmpeg) TIDAK dijalankan; diganti fungsi palsu yang mencatat panggilan."""
import json

import pytest

from core import jalankan


def _video(tmp_path, nama="v.mp4"):
    p = tmp_path / nama
    p.write_bytes(b"x")
    return p


class Palsu:
    """Mencatat panggilan dan (opsional) membuat berkas keluaran seperti modul aslinya."""

    def __init__(self, klip=None, gagal_di=None):
        self.panggilan = []
        self.klip = [{"mulai": 1.0, "akhir": 31.0}] if klip is None else klip
        self.gagal_di = gagal_di

    def _tulis(self, argv, kunci, isi):
        tujuan = argv[argv.index(kunci) + 1]
        with open(tujuan, "w", encoding="utf-8") as f:
            f.write(isi)

    def transkripsi(self, argv):
        self.panggilan.append(("transkripsi", argv))
        if self.gagal_di == "transkripsi":
            return 1
        self._tulis(argv, "--simpan", "[]")
        return 0

    def pipeline(self, argv):
        self.panggilan.append(("pipeline", argv))
        if self.gagal_di == "pipeline":
            return 1
        self._tulis(argv, "--simpan", json.dumps(self.klip))
        return 0

    def metadata(self, argv):
        self.panggilan.append(("metadata", argv))
        if self.gagal_di == "metadata":
            return 1
        self._tulis(argv, "--simpan", "[]")
        return 0

    def render(self, argv):
        self.panggilan.append(("render", argv))
        return 1 if self.gagal_di == "render" else 0

    def langkah(self):
        return {"transkripsi": self.transkripsi, "pipeline": self.pipeline, "metadata": self.metadata,
                "render": self.render}

    def nama(self):
        return [n for n, _ in self.panggilan]


def test_urutan_empat_langkah_dan_folder(tmp_path):
    v = _video(tmp_path)
    f = tmp_path / "hasil"
    p = Palsu()
    assert jalankan.main([str(v), "--folder", str(f)], langkah=p.langkah()) == 0
    assert p.nama() == ["transkripsi", "pipeline", "metadata", "render"]
    assert (f / "kata.json").is_file() and (f / "klip.json").is_file() and (f / "metadata.json").is_file()
    argv_metadata = dict(p.panggilan)["metadata"]
    assert argv_metadata[:2] == [str(f / "kata.json"), str(f / "klip.json")]
    assert argv_metadata[argv_metadata.index("--simpan") + 1] == str(f / "metadata.json")
    argv_pipeline = dict(p.panggilan)["pipeline"]
    assert argv_pipeline[:1] == [str(f / "kata.json")]
    assert argv_pipeline[argv_pipeline.index("--media") + 1] == str(v)
    argv_render = dict(p.panggilan)["render"]
    assert argv_render[0] == str(v) and argv_render[1] == str(f / "klip.json")
    assert argv_render[argv_render.index("--kata") + 1] == str(f / "kata.json")
    assert argv_render[argv_render.index("--folder") + 1] == str(f)


def test_hanya_pilihan_yang_diisi_diteruskan(tmp_path):
    v = _video(tmp_path)
    p = Palsu()
    jalankan.main([str(v), "--folder", str(tmp_path / "h")], langkah=p.langkah())
    for nama, argv in p.panggilan:
        for kunci in ("--n", "--tingkat", "--durasi", "--mode-calon", "--rasio", "--mode", "--bahasa", "--lebar"):
            assert kunci not in argv, (nama, kunci)
        assert "--tanpa-zoom" not in argv


def test_pilihan_diteruskan_ke_langkah_yang_tepat(tmp_path):
    v = _video(tmp_path)
    p = Palsu()
    kode = jalankan.main([str(v), "--folder", str(tmp_path / "h"), "--bahasa", "id", "--model", "base",
                          "--n", "4", "--tingkat", "rapat", "--durasi", "pendek", "--min-detik", "10",
                          "--maks-detik", "25", "--jeda-maks-calon", "0", "--mode-calon", "lama",
                          "--toleransi", "5", "--rasio", "1:1", "--mode", "tengah", "--tanpa-zoom",
                          "--lebar", "720"], langkah=p.langkah())
    assert kode == 0
    d = dict(p.panggilan)
    t = d["transkripsi"]
    assert t[t.index("--bahasa") + 1] == "id" and t[t.index("--model") + 1] == "base"
    pl = d["pipeline"]
    for kunci, nilai in [("--n", "4"), ("--tingkat", "rapat"), ("--durasi", "pendek"), ("--min-detik", "10.0"),
                         ("--maks-detik", "25.0"), ("--jeda-maks-calon", "0.0"), ("--mode-calon", "lama"),
                         ("--toleransi", "5.0")]:
        assert pl[pl.index(kunci) + 1] == nilai, kunci
    r = d["render"]
    assert r[r.index("--rasio") + 1] == "1:1" and r[r.index("--mode") + 1] == "tengah"
    assert r[r.index("--lebar") + 1] == "720" and "--tanpa-zoom" in r


def test_kata_json_ada_transkripsi_dilewati(tmp_path):
    v = _video(tmp_path)
    f = tmp_path / "h"
    f.mkdir()
    (f / "kata.json").write_text("[]", encoding="utf-8")
    p = Palsu()
    assert jalankan.main([str(v), "--folder", str(f)], langkah=p.langkah()) == 0
    assert p.nama() == ["pipeline", "metadata", "render"]


def test_ulang_memaksa_transkripsi(tmp_path):
    v = _video(tmp_path)
    f = tmp_path / "h"
    f.mkdir()
    (f / "kata.json").write_text("[]", encoding="utf-8")
    p = Palsu()
    assert jalankan.main([str(v), "--folder", str(f), "--ulang"], langkah=p.langkah()) == 0
    assert p.nama() == ["transkripsi", "pipeline", "metadata", "render"]


@pytest.mark.parametrize("gagal,sisa", [("transkripsi", ["transkripsi"]),
                                         ("pipeline", ["transkripsi", "pipeline"]),
                                         ("metadata", ["transkripsi", "pipeline", "metadata"]),
                                         ("render", ["transkripsi", "pipeline", "metadata", "render"])])
def test_berhenti_saat_langkah_gagal(tmp_path, gagal, sisa):
    v = _video(tmp_path)
    p = Palsu(gagal_di=gagal)
    assert jalankan.main([str(v), "--folder", str(tmp_path / "h")], langkah=p.langkah()) == 1
    assert p.nama() == sisa


def test_tidak_ada_klip_terpilih_render_tidak_jalan(tmp_path, capsys):
    v = _video(tmp_path)
    p = Palsu(klip=[])
    assert jalankan.main([str(v), "--folder", str(tmp_path / "h")], langkah=p.langkah()) == 1
    assert p.nama() == ["transkripsi", "pipeline"]
    assert "tidak ada klip terpilih" in capsys.readouterr().out


def test_video_tidak_ada(tmp_path, capsys):
    p = Palsu()
    assert jalankan.main([str(tmp_path / "tidak_ada.mp4")], langkah=p.langkah()) == 1
    assert p.panggilan == []
    assert "tidak ditemukan" in capsys.readouterr().out


def test_folder_bawaan_memakai_nama_video(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    v = _video(tmp_path, "podcast.mp4")
    p = Palsu()
    assert jalankan.main([str(v)], langkah=p.langkah()) == 0
    assert (tmp_path / "storage" / "hasil" / "podcast" / "klip.json").is_file()


def test_pilihan_tidak_valid_ditolak(tmp_path):
    v = _video(tmp_path)
    with pytest.raises(SystemExit):
        jalankan.main([str(v), "--tingkat", "banyak-sekali"], langkah=Palsu().langkah())
