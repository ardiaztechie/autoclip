"""main.py: aplikasi FastAPI AutoClip.

Menjalankan (dari folder proyek, .venv aktif):
    uvicorn backend.main:app --reload
Lalu buka http://127.0.0.1:8000/health  (dokumentasi otomatis dan tempat mencoba: http://127.0.0.1:8000/docs)
"""
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from . import api_klip, api_proyek, auth, landing
from .db import cek_database
from .konteks import GalatKonfigurasi, Konteks

log = logging.getLogger("autoclip")


def buat_app(cek_db=None, *, konteks=None) -> FastAPI:
    """cek_db() -> dict {"ok": bool, ...}. Bawaan memeriksa MariaDB sungguhan; diganti saat tes.
    konteks: engine database, pengaturan sesi, jam, dan pembatas login (bawaan: dari .env)."""
    app = FastAPI(title="AutoClip")
    app.state.konteks = konteks or Konteks()

    def cek_bawaan() -> dict:
        try:
            return cek_database(app.state.konteks.engine())
        except GalatKonfigurasi as e:
            return {"ok": False, "pesan": str(e)}

    cek = cek_db or cek_bawaan

    @app.exception_handler(GalatKonfigurasi)
    def _galat_konfigurasi(request, e):
        return JSONResponse({"detail": str(e)}, status_code=503)

    @app.exception_handler(SQLAlchemyError)
    def _galat_database(request, e):
        log.warning("galat database: %s", e)
        return JSONResponse({"detail": "Database tidak bisa dihubungi; pastikan MySQL di XAMPP berstatus Running"},
                            status_code=503)

    app.include_router(auth.router)
    app.include_router(api_proyek.router)
    app.include_router(api_klip.router)
    app.include_router(landing.router)

    @app.get("/health")
    def health():
        db = cek()
        return JSONResponse({"status": "ok" if db["ok"] else "bermasalah", "database": db},
                            status_code=200 if db["ok"] else 503)

    return app


app = buat_app()
