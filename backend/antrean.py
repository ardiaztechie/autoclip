"""antrean.py: operasi tabel job_queue untuk worker (ambil, selesaikan, gagalkan, pulihkan)."""
import json

from sqlalchemy import text

JENIS_DIDUKUNG = ("process_project", "render_clip")
MAKS_PERCOBAAN = 3
_DAFTAR_JENIS = ", ".join(f"'{j}'" for j in JENIS_DIDUKUNG)      # konstanta di atas, bukan masukan pengguna


def ambil(k):
    """Mengambil satu pekerjaan 'queued' tertua dan menandainya 'running'. None bila antrean kosong.
    Pengambilan bersifat atomik (UPDATE bersyarat), jadi aman walau ada lebih dari satu worker."""
    baris = k.execute(text(f"SELECT id, type, payload FROM job_queue WHERE status = 'queued' "
                           f"AND type IN ({_DAFTAR_JENIS}) ORDER BY id LIMIT 1")).first()
    if baris is None:
        return None
    r = k.execute(text("UPDATE job_queue SET status = 'running', locked_at = CURRENT_TIMESTAMP, "
                       "attempts = attempts + 1 WHERE id = :i AND status = 'queued'"), {"i": baris.id})
    if r.rowcount != 1:
        return None
    try:
        payload = json.loads(baris.payload)
    except (TypeError, ValueError):
        payload = None
    return {"id": baris.id, "type": baris.type, "payload": payload}


def selesai(k, job_id: int) -> None:
    k.execute(text("UPDATE job_queue SET status = 'done', error = NULL WHERE id = :i"), {"i": job_id})


def gagal(k, job_id: int, pesan: str) -> None:
    k.execute(text("UPDATE job_queue SET status = 'failed', error = :e WHERE id = :i"),
              {"e": pesan[:1000], "i": job_id})


def pulihkan_terhenti(k) -> list:
    """Dipanggil saat worker dinyalakan: pekerjaan 'running' berarti worker sebelumnya mati di tengah jalan.
    Dikembalikan ke antrean (maks MAKS_PERCOBAAN kali), selebihnya digagalkan.
    Mengembalikan [(job_id, project_id atau None, diulang: bool)]."""
    hasil = []
    for baris in k.execute(text("SELECT id, payload, attempts, type FROM job_queue WHERE status = 'running' ORDER BY id")).all():
        try:
            isi = json.loads(baris.payload)
            pid = int(isi["project_id"])
        except (TypeError, ValueError, KeyError):
            isi, pid = None, None
        diulang = baris.attempts < MAKS_PERCOBAAN
        if baris.type == "render_clip":                   # render ulang satu klip: status proyek tidak disentuh
            pid = None
            if not diulang and isinstance(isi, dict) and isinstance(isi.get("clip_id"), int):
                k.execute(text("UPDATE clips SET status = 'failed' WHERE id = :c AND status = 'rendering'"), {"c": isi["clip_id"]})
        if diulang:
            k.execute(text("UPDATE job_queue SET status = 'queued', locked_at = NULL WHERE id = :i"), {"i": baris.id})
        else:
            gagal(k, baris.id, "Pemrosesan terhenti berulang kali")
        hasil.append((baris.id, pid, diulang))
    return hasil
