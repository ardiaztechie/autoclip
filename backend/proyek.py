"""proyek.py: akses tabel projects dan job_queue. SQL biasa (text) agar mudah dibaca dan dites."""
import json

from sqlalchemy import text

_KOLOM = ("id, title, source_type, source_ref, language, ratio, n_clips, clip_density, clip_length, face_tracking, "
          "status, stage, progress, error, duration_sec, created_at, expires_at")


def _publik(r) -> dict:
    d = dict(r._mapping)
    d["face_tracking"] = bool(d["face_tracking"])
    for kunci in ("created_at", "expires_at"):
        d[kunci] = None if d[kunci] is None else str(d[kunci])
    return d


def jumlah(k, uid: int) -> int:
    return int(k.execute(text("SELECT COUNT(*) FROM projects WHERE user_id = :u"), {"u": uid}).scalar())


KEPADATAN = ("jarang", "sedang", "rapat")
PANJANG_KLIP = ("otomatis", "pendek", "sedang", "panjang")


def buat(k, uid: int, title: str, source_ref: str, language: str, ratio: str, n_clips, face_tracking: bool,
         source_type: str = "upload", kepadatan: str = "sedang", panjang: str = "otomatis") -> int:
    """Menambah proyek (status awal 'queued', tahap 'Antre'); mengembalikan id.
    source_type: 'upload' (berkas) atau 'link' (tautan YouTube; source_ref = tautannya).
    n_clips None = jumlah klip otomatis menurut durasi video dan `kepadatan`; angka = jumlah pasti.
    panjang = lamanya tiap klip (otomatis/pendek/sedang/panjang)."""
    if source_type not in ("upload", "link"):
        raise ValueError("source_type harus 'upload' atau 'link'")
    if kepadatan not in KEPADATAN:
        raise ValueError("kepadatan harus salah satu dari " + ", ".join(KEPADATAN))
    if panjang not in PANJANG_KLIP:
        raise ValueError("panjang harus salah satu dari " + ", ".join(PANJANG_KLIP))
    hasil = k.execute(text(
        "INSERT INTO projects (user_id, title, source_type, source_ref, language, ratio, n_clips, clip_density, "
        "clip_length, face_tracking) VALUES (:u, :t, :st, :s, :l, :r, :n, :kd, :kl, :f)"),
        {"u": uid, "t": title, "st": source_type, "s": source_ref, "l": language, "r": ratio, "n": n_clips,
         "kd": kepadatan, "kl": panjang, "f": 1 if face_tracking else 0})
    return int(hasil.lastrowid)


def antrekan(k, project_id: int) -> int:
    """Menaruh pekerjaan 'process_project' di job_queue; worker yang mengambilnya nanti."""
    hasil = k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('process_project', :p)"),
                      {"p": json.dumps({"project_id": project_id})})
    return int(hasil.lastrowid)


def daftar(k, uid: int) -> list:
    baris = k.execute(text(f"SELECT {_KOLOM} FROM projects WHERE user_id = :u ORDER BY id DESC"), {"u": uid}).all()
    return [_publik(b) for b in baris]


def cari(k, project_id: int, uid: int):
    """Proyek milik uid, atau None (termasuk bila proyeknya ada tetapi milik orang lain)."""
    r = k.execute(text(f"SELECT {_KOLOM} FROM projects WHERE id = :i AND user_id = :u"),
                  {"i": project_id, "u": uid}).first()
    return None if r is None else _publik(r)


_KOLOM_KLIP = ("id, project_id, start_sec, end_sec, score, hook, flow, value_score, trend, title, caption, hashtags, "
               "ratio, status, file_path, size_bytes")


def _json_daftar(nilai) -> list:
    """Kolom JSON: MariaDB mengembalikan teks, SQLite juga. Isi rusak/bukan daftar -> daftar kosong."""
    if isinstance(nilai, (bytes, bytearray)):
        nilai = nilai.decode("utf-8", "replace")
    if isinstance(nilai, str):
        try:
            nilai = json.loads(nilai)
        except ValueError:
            return []
    return [str(x) for x in nilai] if isinstance(nilai, list) else []


def _publik_klip(r) -> dict:
    """Bentuk klip untuk tampilan. Lokasi berkas di server (file_path) sengaja tidak ikut."""
    return {"id": r[0], "project_id": r[1], "start_sec": r[2], "end_sec": r[3],
            "duration_sec": round(float(r[3]) - float(r[2]), 2), "score": r[4],
            "hook": r[5], "flow": r[6], "value": r[7], "trend": r[8], "title": r[9], "caption": r[10],
            "hashtags": _json_daftar(r[11]), "ratio": r[12], "status": r[13],
            "size_bytes": r[15], "ada_video": r[13] == "done" and bool(r[14])}


def daftar_klip(k, project_id: int) -> list:
    """Klip satu proyek, skor tertinggi dulu. Pemeriksaan pemilik proyek dilakukan pemanggil (lihat cari)."""
    baris = k.execute(text(f"SELECT {_KOLOM_KLIP} FROM clips WHERE project_id = :p ORDER BY score DESC, id"),
                      {"p": project_id}).all()
    return [_publik_klip(b) for b in baris]


def cari_berkas_klip(k, project_id: int, clip_id: int):
    """(file_path relatif, judul) klip yang sudah jadi, atau None."""
    r = k.execute(text("SELECT file_path, title FROM clips WHERE id = :c AND project_id = :p AND status = 'done'"),
                  {"c": clip_id, "p": project_id}).first()
    return None if r is None or not r[0] else (r[0], r[1])


# ---------------------------------------------------------------- dipakai worker
_KOLOM_UBAH = {"status", "stage", "progress", "error", "duration_sec", "title"}


def ambil_untuk_proses(k, project_id: int):
    """Data proyek yang dibutuhkan worker (tanpa saringan pemilik), atau None."""
    r = k.execute(text("SELECT id, user_id, title, source_type, source_ref, n_clips, clip_density, clip_length, ratio, language, "
                       "face_tracking, status "
                       "FROM projects WHERE id = :i"), {"i": project_id}).first()
    if r is None:
        return None
    d = dict(r._mapping)
    d["face_tracking"] = bool(d["face_tracking"])
    return d


def ubah(k, project_id: int, **nilai) -> None:
    """Memperbarui kolom status, stage, progress, error, duration_sec, atau title."""
    if not nilai or not set(nilai) <= _KOLOM_UBAH:
        raise ValueError(f"kolom tidak diizinkan: {sorted(set(nilai) - _KOLOM_UBAH)}")
    set_sql = ", ".join(f"{kolom} = :{kolom}" for kolom in nilai)
    k.execute(text(f"UPDATE projects SET {set_sql} WHERE id = :_id"), {**nilai, "_id": project_id})


def simpan_klip(k, project_id: int, ratio: str, daftar: list) -> None:
    """daftar: dict berisi start, end, score, hook, flow, value, trend, title, caption, hashtags (list),
    file_path (relatif terhadap folder storage), size_bytes."""
    for d in daftar:
        k.execute(text(
            "INSERT INTO clips (project_id, start_sec, end_sec, score, hook, flow, value_score, trend, title, titles, "
            "caption, hashtags, ratio, status, file_path, size_bytes) "
            "VALUES (:p, :s, :e, :sk, :h, :f, :v, :t, :ti, :tis, :c, :ha, :r, 'done', :fp, :sz)"),
            {"p": project_id, "s": d["start"], "e": d["end"], "sk": d["score"], "h": d["hook"], "f": d["flow"],
             "v": d["value"], "t": d["trend"], "ti": d["title"][:200], "tis": json.dumps([d["title"][:200]], ensure_ascii=False),
             "c": d["caption"][:500], "ha": json.dumps(d["hashtags"], ensure_ascii=False), "r": ratio,
             "fp": d["file_path"], "sz": d["size_bytes"]})


def catat_metrik(k, job_id, project_id: int, tahap: str, detik: float, video_detik) -> None:
    k.execute(text("INSERT INTO job_metrics (job_id, project_id, stage, seconds, video_seconds) "
                   "VALUES (:j, :p, :s, :d, :v)"),
              {"j": job_id, "p": project_id, "s": tahap, "d": detik, "v": video_detik})
