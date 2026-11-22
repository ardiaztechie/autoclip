"""Tes backend/migrasi.py. TIDAK memakai MariaDB sungguhan: koneksi dipalsukan dan perintah SQL-nya dicatat."""
import re
from pathlib import Path

import pytest

from backend import migrasi


class _Hasil:
    def __init__(self, baris):
        self._b = baris

    def first(self):
        return self._b


class KoneksiPalsu:
    """kolom: {nama_kolom: boleh_kosong(bool)} untuk tabel projects; kolom yang tidak ada = belum ada."""

    def __init__(self, kolom):
        self.kolom = dict(kolom)
        self.perintah = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "information_schema" in sql:
            nama = params["c"]
            assert params["t"] == "projects"
            return _Hasil((("YES" if self.kolom[nama] else "NO"),) if nama in self.kolom else None)
        self.perintah.append(sql)
        return _Hasil(None)


LAMA = {"n_clips": False}
BARU = {"n_clips": True, "clip_density": False, "clip_length": False}


def test_database_lama_dimigrasi():
    k = KoneksiPalsu(LAMA)
    laporan = migrasi.terapkan(k)
    assert k.perintah == [migrasi.SQL_N_CLIPS_BOLEH_KOSONG, migrasi.SQL_KEPADATAN, migrasi.SQL_PANJANG]
    assert len(laporan) == 3 and "boleh kosong" in laporan[0] and "ditambahkan" in laporan[1] + laporan[2]


def test_database_sudah_baru_tidak_diubah_lagi():
    k = KoneksiPalsu(BARU)
    laporan = migrasi.terapkan(k)
    assert k.perintah == [] and all("dilewati" in baris for baris in laporan)


@pytest.mark.parametrize("kolom,jumlah", [
    ({"n_clips": True}, 2), ({"n_clips": False, "clip_density": False}, 2), ({"n_clips": True, "clip_density": False}, 1),
])
def test_sebagian_sudah_ada_hanya_sisanya_dikerjakan(kolom, jumlah):
    k = KoneksiPalsu(kolom)
    migrasi.terapkan(k)
    assert len(k.perintah) == jumlah


def test_tabel_belum_ada_dilaporkan_jelas():
    with pytest.raises(RuntimeError, match="schema.sql"):
        migrasi.terapkan(KoneksiPalsu({}))


def test_pernyataan_sql_sama_dengan_schema_sql():
    """Kolom hasil migrasi harus sama persis dengan definisi di schema.sql (supaya database baru dan lama identik)."""
    sql = (Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
    for definisi in (migrasi.SQL_KEPADATAN, migrasi.SQL_PANJANG):
        potongan = re.search(r"ADD COLUMN (\w+) (ENUM\([^)]*\)) NOT NULL DEFAULT ('\w+')", definisi).groups()
        assert re.search(rf"{potongan[0]}\s+{re.escape(potongan[1])} NOT NULL DEFAULT {potongan[2]}", sql), potongan
    assert re.search(r"n_clips\s+TINYINT UNSIGNED NULL", sql) and "TINYINT UNSIGNED NULL DEFAULT NULL" in migrasi.SQL_N_CLIPS_BOLEH_KOSONG


class _Engine:
    def __init__(self, koneksi):
        self.koneksi = koneksi

    def begin(self):
        k = self.koneksi

        class Konteks:
            def __enter__(s):
                return k

            def __exit__(s, *a):
                return False
        return Konteks()


class _Ctx:
    def __init__(self, engine):
        self._e = engine

    def engine(self):
        return self._e


def test_main_berhasil_dan_mencetak_laporan(capsys):
    assert migrasi.main(konteks=_Ctx(_Engine(KoneksiPalsu(LAMA)))) == 0
    out = capsys.readouterr().out
    assert "clip_density: ditambahkan" in out and "Selesai" in out


def test_main_database_mati_tanpa_membocorkan_rahasia(capsys):
    from sqlalchemy.exc import OperationalError

    class Mati:
        def begin(self):
            raise OperationalError("x", {}, Exception("rahasia"))

    assert migrasi.main(konteks=_Ctx(Mati())) == 1
    out = capsys.readouterr().out
    assert "XAMPP" in out and "[GAGAL]" in out


def test_main_konfigurasi_salah(capsys):
    from backend.konteks import GalatKonfigurasi

    class Salah:
        def engine(self):
            raise GalatKonfigurasi("DB_PORT di .env harus berupa angka")

    assert migrasi.main(konteks=Salah()) == 1
    assert "DB_PORT" in capsys.readouterr().out
