"""konteks.py: hal-hal yang dipakai bersama oleh seluruh endpoint (engine database, pengaturan sesi, jam,
pembatas login). Semuanya dibuat MALAS (saat pertama dipakai), bukan saat impor, dan mudah diganti saat tes."""
import logging
import time

from . import config
from .db import buat_engine
from .keamanan import PembatasLogin

log = logging.getLogger("autoclip")


class GalatKonfigurasi(Exception):
    """Pengaturan di .env salah atau kurang. Pesannya aman ditampilkan."""


class Konteks:
    def __init__(self, *, engine=None, sesi=None, unggah=None, sekarang=time.time, pembatas=None, muat_env=None):
        self._engine, self._sesi, self._unggah = engine, sesi, unggah
        self.sekarang = sekarang
        self.pembatas = pembatas or PembatasLogin()
        self._muat_env, self._env_dimuat = muat_env, False

    def _muat(self):
        if not self._env_dimuat:
            (self._muat_env or config.muat_env)()
            self._env_dimuat = True

    def engine(self):
        if self._engine is None:
            self._muat()
            try:
                self._engine = buat_engine(config.pengaturan_db())
            except ValueError as e:
                raise GalatKonfigurasi(str(e)) from None
        return self._engine

    def sesi(self) -> dict:
        if self._sesi is None:
            self._muat()
            try:
                self._sesi = config.pengaturan_sesi()
            except ValueError as e:
                raise GalatKonfigurasi(str(e)) from None
            if self._sesi["acak"]:
                log.warning("SESSION_SECRET belum diisi di .env: sesi login hilang setiap server dimulai ulang")
        return self._sesi

    def unggah(self) -> dict:
        """{"folder": Path penyimpanan, "maks_bytes": batas ukuran satu video}."""
        if self._unggah is None:
            self._muat()
            try:
                self._unggah = config.pengaturan_unggah()
            except ValueError as e:
                raise GalatKonfigurasi(str(e)) from None
        return self._unggah
