"""Tes backend/keamanan.py dan pengaturan sesi. Tanpa database, tanpa internet."""
import pytest
from argon2 import PasswordHasher

from backend import config, keamanan
from backend.keamanan import PembatasLogin, baca_token, buat_token, cek_password, hash_password

RAHASIA = "r" * 32


@pytest.fixture(autouse=True)
def hasher_cepat(monkeypatch):
    """Argon2 bawaan sengaja lambat; untuk tes dipakai parameter minimum agar cepat."""
    monkeypatch.setattr(keamanan, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    monkeypatch.setattr(keamanan, "_hash_palsu", None)


# ---------------------------------------------------------------- password
def test_hash_bukan_teks_asli_dan_bisa_diverifikasi():
    h = hash_password("rahasia123")
    assert "rahasia123" not in h and h.startswith("$argon2")
    assert cek_password(h, "rahasia123") is True
    assert cek_password(h, "rahasia124") is False


def test_hash_memakai_garam_acak():
    assert hash_password("sama") != hash_password("sama")


@pytest.mark.parametrize("rusak", ["", "bukan hash", "$argon2id$rusak"])
def test_hash_rusak_dianggap_salah_bukan_crash(rusak):
    assert cek_password(rusak, "apa saja") is False


def test_hash_palsu_valid_dan_tidak_cocok_dengan_input_biasa():
    h = keamanan.hash_palsu()
    assert h.startswith("$argon2") and cek_password(h, "apa saja") is False
    assert keamanan.hash_palsu() == h                      # dibuat sekali lalu dipakai ulang


# ---------------------------------------------------------------- token
def test_token_bolak_balik():
    assert baca_token(buat_token(7, RAHASIA, 1000, 60), RAHASIA, 1000) == 7


def test_token_kedaluwarsa():
    t = buat_token(7, RAHASIA, 1000, 60)
    assert baca_token(t, RAHASIA, 1059) == 7
    assert baca_token(t, RAHASIA, 1060) is None            # tepat di batas = sudah tidak berlaku
    assert baca_token(t, RAHASIA, 5000) is None


def test_token_rahasia_lain_ditolak():
    assert baca_token(buat_token(7, RAHASIA, 1000, 60), "x" * 32, 1000) is None


def test_token_dipalsukan_ditolak():
    isi, tanda = buat_token(7, RAHASIA, 1000, 60).split(".")
    palsu = buat_token(1, "penyerang" * 4, 1000, 60).split(".")[0]      # id admin, ditandatangani rahasia lain
    assert baca_token(palsu + "." + tanda, RAHASIA, 1000) is None
    assert baca_token(isi + "." + tanda[:-2] + "AA", RAHASIA, 1000) is None


@pytest.mark.parametrize("sampah", [None, "", "abc", "a.b", "a.b.c", 123, b"x.y", "....", "!!!.???"])
def test_token_sampah_ditolak_bukan_crash(sampah):
    assert baca_token(sampah, RAHASIA, 1000) is None


def test_token_isi_bertipe_salah_ditolak():
    # ditandatangani dengan rahasia yang benar tetapi isinya tidak masuk akal
    def tanda_tangan(isi_json):
        isi = keamanan._b64(isi_json.encode())
        return isi + "." + keamanan._b64(keamanan._tanda(isi, RAHASIA))

    assert baca_token(tanda_tangan('{"uid": true, "exp": 9999}'), RAHASIA, 1000) is None
    assert baca_token(tanda_tangan('{"uid": "7", "exp": 9999}'), RAHASIA, 1000) is None
    assert baca_token(tanda_tangan('{"uid": 7, "exp": "9999"}'), RAHASIA, 1000) is None
    assert baca_token(tanda_tangan('{"uid": 7}'), RAHASIA, 1000) is None
    assert baca_token(tanda_tangan('[1, 2]'), RAHASIA, 1000) is None
    assert baca_token(tanda_tangan('{"uid": 7, "exp": 9999}'), RAHASIA, 1000) == 7


# ---------------------------------------------------------------- pembatas login
def test_pembatas_memblokir_setelah_batas_dan_membuka_setelah_jendela():
    p = PembatasLogin(maks=3, jendela=100)
    for t in (0, 1, 2):
        assert not p.terblokir("a", t)
        p.catat_gagal("a", t)
    assert p.terblokir("a", 3)
    assert p.terblokir("a", 99)                            # percobaan pertama (t=0) belum lewat jendela
    assert not p.terblokir("a", 102)                       # t=0 dan t=1 sudah lewat, tinggal satu


def test_pembatas_kunci_terpisah_dan_reset():
    p = PembatasLogin(maks=2, jendela=100)
    p.catat_gagal("a", 0)
    p.catat_gagal("a", 1)
    assert p.terblokir("a", 2) and not p.terblokir("b", 2)
    p.reset("a")
    assert not p.terblokir("a", 2)


def test_pembatas_membersihkan_catatan_lama():
    p = PembatasLogin(maks=2, jendela=10)
    p.catat_gagal("a", 0)
    assert not p.terblokir("a", 50)
    assert "a" not in p._gagal


# ---------------------------------------------------------------- pengaturan sesi
def test_sesi_bawaan_acak_dan_tujuh_hari():
    s = config.pengaturan_sesi({})
    assert s["acak"] is True and len(s["rahasia"]) == 64 and s["umur"] == 7 * 86400 and s["cookie_aman"] is False
    assert config.pengaturan_sesi({})["rahasia"] != s["rahasia"]


def test_sesi_dari_env():
    s = config.pengaturan_sesi({"SESSION_SECRET": "k" * 40, "SESSION_DAYS": "0.5", "COOKIE_SECURE": "1"})
    assert s == {"rahasia": "k" * 40, "acak": False, "umur": 43200, "cookie_aman": True}


def test_sesi_rahasia_pendek_ditolak_dengan_petunjuk():
    with pytest.raises(ValueError, match="secrets.token_hex"):
        config.pengaturan_sesi({"SESSION_SECRET": "pendek"})


@pytest.mark.parametrize("hari", ["abc", "0", "-1"])
def test_sesi_hari_tidak_valid(hari):
    with pytest.raises(ValueError, match="SESSION_DAYS"):
        config.pengaturan_sesi({"SESSION_DAYS": hari})
