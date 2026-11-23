"""proyek.py: akses tabel projects dan job_queue. SQL biasa (text) agar mudah dibaca dan dites."""
import json
import math
import re

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
PANJANG_KLIP = ("otomatis", "pendek", "sedang", "panjang", "sangat_panjang", "ekstra_panjang")
# Durasi klip terpendek tiap pilihan (detik); harus sama dengan core.pipeline.PRESET_DURASI (dijaga oleh tes).
MIN_DETIK_PANJANG = {"otomatis": 30.0, "pendek": 15.0, "sedang": 30.0, "panjang": 60.0, "sangat_panjang": 90.0,
                     "ekstra_panjang": 120.0}
NAMA_PANJANG = {"otomatis": "Otomatis", "pendek": "Pendek", "sedang": "Sedang", "panjang": "Panjang",
                "sangat_panjang": "Sangat panjang", "ekstra_panjang": "Ekstra panjang"}


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


# Klip yang sedang/baru gagal dirender ulang tetap punya video lama (berkasnya baru diganti bila render ulang berhasil).
STATUS_ADA_VIDEO = ("done", "rendering", "failed")
MIN_KLIP_DETIK = 5.0          # batas atur-batas-klip (perkiraan; bukan hasil riset)
MAKS_KLIP_DETIK = 300.0

_KOLOM_KLIP = ("id, project_id, start_sec, end_sec, score, hook, flow, value_score, trend, title, caption, hashtags, "
               "ratio, status, file_path, size_bytes, edit_settings")

# Pilihan subtitle (harus sama dengan core/subtitle.py; ada tes yang membandingkannya)
GAYA_SUBTITLE = ("klasik", "kuning", "kotak", "sorot", "minimal")
POSISI_SUBTITLE = ("bawah", "tengah", "atas")
UKURAN_SUBTITLE = ("kecil", "sedang", "besar")
ANIMASI_SUBTITLE = ("tanpa", "muncul", "pudar")
SUBTITLE_BAWAAN = {"gaya": "klasik", "posisi": "bawah", "ukuran": "sedang", "animasi": "tanpa", "aktif": True}
MAKS_KOREKSI = 2000
MAKS_HURUF_KATA = 60


def _bersihkan_subtitle(nilai) -> dict:
    """Pilihan subtitle yang valid; nilai yang hilang atau salah memakai bawaan."""
    nilai = nilai if isinstance(nilai, dict) else {}
    hasil = dict(SUBTITLE_BAWAAN)
    for kunci, pilihan in (("gaya", GAYA_SUBTITLE), ("posisi", POSISI_SUBTITLE), ("ukuran", UKURAN_SUBTITLE),
                           ("animasi", ANIMASI_SUBTITLE)):
        if nilai.get(kunci) in pilihan:
            hasil[kunci] = nilai[kunci]
    if isinstance(nilai.get("aktif"), bool):
        hasil["aktif"] = nilai["aktif"]
    return hasil


def _bersihkan_koreksi(nilai) -> list:
    """Daftar [{'s': detik mulai kata, 'w': teks baru}]; item rusak dibuang, maksimal MAKS_KOREKSI. Teks kosong = kata dibuang."""
    hasil = []
    for item in nilai if isinstance(nilai, list) else []:
        if not isinstance(item, dict):
            continue
        s, w = item.get("s"), item.get("w")
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s) or s < 0 or not isinstance(w, str):
            continue
        hasil.append({"s": round(float(s), 3), "w": " ".join(w.split())[:MAKS_HURUF_KATA]})
        if len(hasil) >= MAKS_KOREKSI:
            break
    return hasil


JEDA_BAWAAN = {"aktif": False, "ambang": 0.6}
AMBANG_JEDA_MIN, AMBANG_JEDA_MAKS = 0.3, 3.0            # harus sama dengan core/jeda.py


def _bersihkan_jeda(nilai) -> dict:
    """Pilihan potong jeda: {"aktif": bool, "ambang": detik 0,3-3,0}. Isi rusak -> bawaan (mati)."""
    hasil = dict(JEDA_BAWAAN)
    if isinstance(nilai, dict):
        if isinstance(nilai.get("aktif"), bool):
            hasil["aktif"] = nilai["aktif"]
        a = nilai.get("ambang")
        if isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a):
            hasil["ambang"] = round(min(AMBANG_JEDA_MAKS, max(AMBANG_JEDA_MIN, float(a))), 2)
    return hasil


MAKS_POTONGAN = 200


def _bersihkan_potong(nilai) -> list:
    """Potongan manual: daftar [a, b] detik video sumber yang dibuang dari klip. Isi rusak diabaikan; hasil urut dan tanpa tumpang tindih."""
    selang = []
    if isinstance(nilai, list):
        for x in nilai[:MAKS_POTONGAN * 4]:
            if (isinstance(x, (list, tuple)) and len(x) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in x)
                    and 0 <= x[0] < x[1]):
                selang.append((round(float(x[0]), 3), round(float(x[1]), 3)))
    selang.sort()
    hasil = []
    for a, b in selang:
        if hasil and a <= hasil[-1][1]:
            hasil[-1] = [hasil[-1][0], max(hasil[-1][1], b)]
        else:
            hasil.append([a, b])
    return hasil[:MAKS_POTONGAN]


def urai_potong(nilai) -> list:
    return _bersihkan_potong(_muat_edit(nilai).get("potong"))


def _potong_terender(nilai) -> list:
    ter = _muat_edit(nilai).get("terender")
    return _bersihkan_potong(ter.get("potong") if isinstance(ter, dict) else None)


def urai_jeda(nilai) -> dict:
    """Kolom clips.edit_settings -> pilihan potong jeda klip."""
    return _bersihkan_jeda(_muat_edit(nilai).get("jeda"))


def _jeda_efektif(jeda: dict):
    """Yang memengaruhi video: None bila mati (ambang tidak berarti), selain itu ambangnya."""
    return jeda["ambang"] if jeda["aktif"] else None


def _jeda_terender(nilai) -> dict:
    ter = _muat_edit(nilai).get("terender")
    return _bersihkan_jeda(ter.get("jeda") if isinstance(ter, dict) else None)


def _muat_edit(nilai) -> dict:
    if isinstance(nilai, (bytes, bytearray)):
        nilai = nilai.decode("utf-8", "replace")
    if isinstance(nilai, str):
        try:
            nilai = json.loads(nilai)
        except ValueError:
            nilai = None
    return nilai if isinstance(nilai, dict) else {}


def urai_pengaturan(nilai) -> tuple:
    """Kolom clips.edit_settings (JSON/teks/None) -> (subtitle: dict, koreksi: list). Rusak -> bawaan."""
    nilai = _muat_edit(nilai)
    return _bersihkan_subtitle(nilai.get("subtitle")), _bersihkan_koreksi(nilai.get("koreksi"))


def _terender(nilai) -> tuple:
    """(subtitle, koreksi) yang dipakai video klip saat ini. Belum pernah dirender ulang -> bawaan (render awal pipeline)."""
    ter = _muat_edit(nilai).get("terender")
    ter = ter if isinstance(ter, dict) else {}
    return _bersihkan_subtitle(ter.get("subtitle")), _bersihkan_koreksi(ter.get("koreksi"))


def subtitle_perlu_render(nilai) -> bool:
    """True bila gaya/koreksi tersimpan berbeda dari yang sudah dibakar di video klip."""
    return urai_pengaturan(nilai) != _terender(nilai) or _jeda_efektif(urai_jeda(nilai)) != _jeda_efektif(_jeda_terender(nilai)) or urai_potong(nilai) != _potong_terender(nilai)


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
            "size_bytes": r[15], "ada_video": r[13] in STATUS_ADA_VIDEO and bool(r[14]),
            "subtitle": urai_pengaturan(r[16])[0], "koreksi": urai_pengaturan(r[16])[1],
            "subtitle_perlu_render": subtitle_perlu_render(r[16]), "jeda": urai_jeda(r[16]), "potong": urai_potong(r[16])}


def daftar_klip(k, project_id: int) -> list:
    """Klip satu proyek, urut menurut menit video (yang awal dulu). Pemeriksaan pemilik proyek dilakukan pemanggil (lihat cari)."""
    baris = k.execute(text(f"SELECT {_KOLOM_KLIP} FROM clips WHERE project_id = :p ORDER BY start_sec, id"),
                      {"p": project_id}).all()
    return [_publik_klip(b) for b in baris]


def cari_klip(k, project_id: int, clip_id: int):
    """Satu klip proyek ini, atau None."""
    r = k.execute(text(f"SELECT {_KOLOM_KLIP} FROM clips WHERE id = :i AND project_id = :p"),
                  {"i": clip_id, "p": project_id}).first()
    return None if r is None else _publik_klip(r)


def jadwalkan_render_ulang(k, project_id: int, clip_id: int, mulai: float, akhir: float) -> dict:
    """Menandai klip 'rendering' dan menaruh pekerjaan render_clip (batas baru mulai-akhir, detik video sumber).
    LookupError bila klip tidak ada; RuntimeError bila klipnya masih dirender ulang. Pemeriksaan pemilik dan batas
    dilakukan pemanggil."""
    hasil = k.execute(text("UPDATE clips SET status = 'rendering' WHERE id = :i AND project_id = :p AND status <> 'rendering'"),
                      {"i": clip_id, "p": project_id})
    if hasil.rowcount == 0:
        if cari_klip(k, project_id, clip_id) is None:
            raise LookupError("klip tidak ditemukan")
        raise RuntimeError("klip masih dirender ulang")
    k.execute(text("INSERT INTO job_queue (type, payload) VALUES ('render_clip', :p)"),
              {"p": json.dumps({"project_id": project_id, "clip_id": clip_id, "mulai": float(mulai), "akhir": float(akhir)})})
    return cari_klip(k, project_id, clip_id)


def simpan_subtitle(k, project_id: int, clip_id: int, subtitle: dict, koreksi=None) -> dict | None:
    """Menyimpan pilihan subtitle satu klip (dan koreksi kata bila koreksi bukan None; None = koreksi lama dipertahankan).
    Tidak merender ulang. Mengembalikan klip yang diperbarui, atau None bila klip tidak ada."""
    r = k.execute(text("SELECT edit_settings FROM clips WHERE id = :i AND project_id = :p"),
                  {"i": clip_id, "p": project_id}).first()
    if r is None:
        return None
    _, koreksi_lama = urai_pengaturan(r[0])
    isi = {"subtitle": _bersihkan_subtitle(subtitle),
           "koreksi": koreksi_lama if koreksi is None else _bersihkan_koreksi(koreksi)}
    for kunci in ("terender", "jeda", "potong"):                    # catatan "apa yang sudah dibakar di video" dan pilihan jeda tidak ikut berubah
        if kunci in _muat_edit(r[0]):
            isi[kunci] = _muat_edit(r[0])[kunci]
    k.execute(text("UPDATE clips SET edit_settings = :e, edit_count = edit_count + 1 WHERE id = :i AND project_id = :p"),
              {"e": json.dumps(isi, ensure_ascii=False), "i": clip_id, "p": project_id})
    return cari_klip(k, project_id, clip_id)


def simpan_jeda(k, project_id: int, clip_id: int, jeda: dict) -> dict | None:
    """Menyimpan pilihan potong jeda satu klip (tanpa merender ulang). Klip tidak ada -> None."""
    r = k.execute(text("SELECT edit_settings FROM clips WHERE id = :i AND project_id = :p"),
                  {"i": clip_id, "p": project_id}).first()
    if r is None:
        return None
    isi = _muat_edit(r[0])
    isi["jeda"] = _bersihkan_jeda(jeda)
    k.execute(text("UPDATE clips SET edit_settings = :e, edit_count = edit_count + 1 WHERE id = :i AND project_id = :p"),
              {"e": json.dumps(isi, ensure_ascii=False), "i": clip_id, "p": project_id})
    return cari_klip(k, project_id, clip_id)


def simpan_potong(k, project_id: int, clip_id: int, potong) -> dict | None:
    """Menyimpan potongan manual (bagi lalu hapus segmen) satu klip, tanpa merender ulang. Klip tidak ada -> None."""
    r = k.execute(text("SELECT edit_settings FROM clips WHERE id = :i AND project_id = :p"),
                  {"i": clip_id, "p": project_id}).first()
    if r is None:
        return None
    isi = _muat_edit(r[0])
    isi["potong"] = _bersihkan_potong(potong)
    k.execute(text("UPDATE clips SET edit_settings = :e, edit_count = edit_count + 1 WHERE id = :i AND project_id = :p"),
              {"e": json.dumps(isi, ensure_ascii=False), "i": clip_id, "p": project_id})
    return cari_klip(k, project_id, clip_id)


def ambil_potong_klip(k, clip_id: int) -> list:
    r = k.execute(text("SELECT edit_settings FROM clips WHERE id = :i"), {"i": clip_id}).first()
    return urai_potong(None if r is None else r[0])


def ambil_jeda_klip(k, clip_id: int) -> dict:
    """Pilihan potong jeda satu klip untuk worker; bawaan (mati) bila belum diatur."""
    r = k.execute(text("SELECT edit_settings FROM clips WHERE id = :i"), {"i": clip_id}).first()
    return urai_jeda(None if r is None else r[0])


def terapkan_subtitle_semua(k, project_id: int, subtitle: dict) -> list:
    """Menyamakan pilihan subtitle (gaya/posisi/ukuran/aktif) semua klip proyek yang tidak sedang dirender; koreksi kata
    tiap klip dipertahankan. Mengembalikan [(clip_id, start_sec, end_sec)] klip yang diubah."""
    hasil = []
    for baris in k.execute(text("SELECT id, start_sec, end_sec FROM clips WHERE project_id = :p AND status <> 'rendering' "
                                "AND file_path IS NOT NULL AND file_path <> '' ORDER BY start_sec, id"), {"p": project_id}).all():
        if simpan_subtitle(k, project_id, baris[0], subtitle) is not None:
            hasil.append((baris[0], float(baris[1]), float(baris[2])))
    return hasil


def ambil_pengaturan_klip(k, clip_id: int) -> tuple:
    """(subtitle, koreksi) satu klip untuk worker; bawaan bila belum pernah diatur."""
    r = k.execute(text("SELECT edit_settings FROM clips WHERE id = :i"), {"i": clip_id}).first()
    return urai_pengaturan(None if r is None else r[0])


PESAN_DIBATALKAN = "dibatalkan"      # penanda di job_queue.error (kolom status ENUM tidak punya nilai 'cancelled')


def batalkan_render_ulang(k, project_id: int, clip_id: int) -> dict:
    """Membatalkan render ulang satu klip: pekerjaan render_clip yang antre/berjalan ditandai 'failed' dengan penanda
    PESAN_DIBATALKAN (worker yang melihatnya menghentikan prosesnya), klip kembali 'done' dengan video lamanya.
    LookupError bila klip tidak ada; RuntimeError bila klip tidak sedang dirender ulang."""
    hasil = k.execute(text("UPDATE clips SET status = 'done' WHERE id = :i AND project_id = :p AND status = 'rendering' "
                           "AND file_path IS NOT NULL AND file_path <> ''"), {"i": clip_id, "p": project_id})
    if hasil.rowcount == 0:
        if cari_klip(k, project_id, clip_id) is None:
            raise LookupError("klip tidak ditemukan")
        raise RuntimeError("klip tidak sedang dirender ulang")
    for baris in k.execute(text("SELECT id, payload FROM job_queue WHERE type = 'render_clip' "
                                "AND status IN ('queued', 'running')")).all():
        try:
            isi = json.loads(baris.payload)
            cocok = isi["clip_id"] == clip_id and isi["project_id"] == project_id
        except (TypeError, ValueError, KeyError):
            cocok = False
        if cocok:
            k.execute(text("UPDATE job_queue SET status = 'failed', error = :e WHERE id = :i"),
                      {"e": PESAN_DIBATALKAN, "i": baris.id})
    return cari_klip(k, project_id, clip_id)


STAGE_DIBATALKAN = "Dibatalkan"     # status proyek yang dibatalkan = 'failed' + stage ini (ENUM status tidak punya nilai 'cancelled')


def batalkan_proyek(k, project_id: int, uid: int) -> dict:
    """Membatalkan pemrosesan proyek yang antre/berjalan: proyek jadi status 'failed' dengan stage STAGE_DIBATALKAN,
    pekerjaan process_project-nya ditandai 'failed' berpenanda PESAN_DIBATALKAN (worker yang melihatnya menghentikan
    prosesnya). Proyek dan berkas yang sudah ada tidak dihapus. LookupError bila proyek bukan milik uid / tidak ada;
    RuntimeError bila proyek tidak sedang antre/diproses."""
    if cari(k, project_id, uid) is None:
        raise LookupError("proyek tidak ditemukan")
    hasil = k.execute(text("UPDATE projects SET status = 'failed', stage = :s, error = 'Dibatalkan oleh pengguna' "
                           "WHERE id = :i AND user_id = :u AND status IN ('queued', 'processing')"),
                      {"s": STAGE_DIBATALKAN, "i": project_id, "u": uid})
    if hasil.rowcount == 0:
        raise RuntimeError("proyek tidak sedang diproses")
    for baris in k.execute(text("SELECT id, payload FROM job_queue WHERE type = 'process_project' "
                                "AND status IN ('queued', 'running')")).all():
        try:
            cocok = json.loads(baris.payload)["project_id"] == project_id
        except (TypeError, ValueError, KeyError):
            cocok = False
        if cocok:
            k.execute(text("UPDATE job_queue SET status = 'failed', error = :e WHERE id = :i"),
                      {"e": PESAN_DIBATALKAN, "i": baris.id})
    return cari(k, project_id, uid)


def galat_render_terakhir(k, project_id: int, clip_id: int) -> str | None:
    """Pesan galat pekerjaan render_clip terakhir yang gagal untuk klip ini (bukan pembatalan), atau None."""
    for baris in k.execute(text("SELECT payload, error FROM job_queue WHERE type = 'render_clip' AND status = 'failed' "
                                "ORDER BY id DESC LIMIT 50")).all():
        try:
            isi = json.loads(baris.payload)
            cocok = isi["clip_id"] == clip_id and isi["project_id"] == project_id
        except (TypeError, ValueError, KeyError):
            continue
        if cocok:
            pesan = (baris.error or "").strip()
            return None if not pesan or pesan == PESAN_DIBATALKAN else pesan[:500]
    return None


def _hapus_baris_anak(k, tabel: str, kolom: str, ids: list) -> None:
    """Menghapus baris tabel anak yang kolom `kolom`-nya termasuk ids. Tabel yang belum ada (mis. di tes) dilewati; di MariaDB
    baris anak juga ikut terhapus lewat ON DELETE CASCADE, ini hanya agar hasilnya sama di mana pun."""
    from sqlalchemy import inspect
    if not ids or not inspect(k).has_table(tabel):
        return
    for i in ids:
        k.execute(text(f"DELETE FROM {tabel} WHERE {kolom} = :i"), {"i": i})


def _hapus_pekerjaan(k, tipe: tuple, cocok) -> None:
    for baris in k.execute(text("SELECT id, payload FROM job_queue WHERE type IN (" + ", ".join(f"'{t}'" for t in tipe) + ")")).all():
        try:
            if cocok(json.loads(baris.payload)):
                k.execute(text("DELETE FROM job_queue WHERE id = :i"), {"i": baris.id})
        except (TypeError, ValueError, KeyError):
            continue


def hapus_proyek(k, project_id: int, uid: int) -> None:
    """Menghapus proyek milik uid beserta semua klip, transkrip, dan antreannya (berkas di disk dihapus pemanggil).
    LookupError bila proyek bukan milik uid / tidak ada; RuntimeError bila proyek masih antre/diproses (batalkan dulu)
    atau ada klip yang sedang dirender ulang."""
    p = cari(k, project_id, uid)
    if p is None:
        raise LookupError("proyek tidak ditemukan")
    if p["status"] in ("queued", "processing"):
        raise RuntimeError("proyek masih diproses; batalkan dulu")
    if k.execute(text("SELECT COUNT(*) FROM clips WHERE project_id = :p AND status = 'rendering'"), {"p": project_id}).scalar():
        raise RuntimeError("ada klip yang sedang dirender; tunggu atau batalkan dulu")
    ids = [r[0] for r in k.execute(text("SELECT id FROM clips WHERE project_id = :p"), {"p": project_id}).all()]
    _hapus_baris_anak(k, "clip_subtitles", "clip_id", ids)
    _hapus_baris_anak(k, "clip_elements", "clip_id", ids)
    _hapus_baris_anak(k, "transcripts", "project_id", [project_id])
    k.execute(text("DELETE FROM clips WHERE project_id = :p"), {"p": project_id})
    _hapus_pekerjaan(k, ("process_project", "render_clip"), lambda isi: isi["project_id"] == project_id)
    k.execute(text("DELETE FROM projects WHERE id = :i AND user_id = :u"), {"i": project_id, "u": uid})


def hapus_klip(k, project_id: int, clip_id: int):
    """Menghapus satu klip. Mengembalikan file_path relatif klip itu (untuk dihapus dari disk; bisa None/kosong).
    LookupError bila klip tidak ada; RuntimeError bila klipnya sedang dirender. Pemeriksaan pemilik dilakukan pemanggil."""
    r = k.execute(text("SELECT status, file_path FROM clips WHERE id = :i AND project_id = :p"),
                  {"i": clip_id, "p": project_id}).first()
    if r is None:
        raise LookupError("klip tidak ditemukan")
    if r[0] == "rendering":
        raise RuntimeError("klip sedang dirender; tunggu atau batalkan dulu")
    _hapus_baris_anak(k, "clip_subtitles", "clip_id", [clip_id])
    _hapus_baris_anak(k, "clip_elements", "clip_id", [clip_id])
    k.execute(text("DELETE FROM clips WHERE id = :i AND project_id = :p"), {"i": clip_id, "p": project_id})
    _hapus_pekerjaan(k, ("render_clip",), lambda isi: isi["clip_id"] == clip_id and isi["project_id"] == project_id)
    return r[1]


def ambil_klip_render(k, project_id: int, clip_id: int):
    """(file_path relatif, ratio) klip untuk worker, atau None."""
    r = k.execute(text("SELECT file_path, ratio FROM clips WHERE id = :i AND project_id = :p"),
                  {"i": clip_id, "p": project_id}).first()
    return None if r is None or not r[0] else (r[0], r[1])


def selesai_render_ulang(k, clip_id: int, mulai: float, akhir: float, ukuran: int, terender=None, jeda=None, potong=None) -> None:
    """Klip selesai dirender ulang. terender = (subtitle, koreksi) yang dipakai render itu; dicatat supaya editor tahu
    apakah gaya tersimpan sudah ada di video."""
    k.execute(text("UPDATE clips SET start_sec = :s, end_sec = :e, size_bytes = :z, status = 'done' WHERE id = :i"),
              {"s": mulai, "e": akhir, "z": ukuran, "i": clip_id})
    if terender is not None:
        r = k.execute(text("SELECT edit_settings FROM clips WHERE id = :i"), {"i": clip_id}).first()
        isi = _muat_edit(None if r is None else r[0])
        isi["terender"] = {"subtitle": terender[0], "koreksi": terender[1]}
        if jeda is not None:
            isi["terender"]["jeda"] = _bersihkan_jeda(jeda)
        if potong is not None:
            isi["terender"]["potong"] = _bersihkan_potong(potong)
        k.execute(text("UPDATE clips SET edit_settings = :e WHERE id = :i"),
                  {"e": json.dumps(isi, ensure_ascii=False), "i": clip_id})


def gagal_render_ulang(k, clip_id: int) -> None:
    k.execute(text("UPDATE clips SET status = 'failed' WHERE id = :i AND status = 'rendering'"), {"i": clip_id})


def rapikan_hashtag(daftar, maks: int = 30) -> list:
    """Hashtag dari pengguna: tanpa spasi/karakter kontrol, selalu diawali #, tanpa kembar, paling banyak `maks`, paling panjang 50 huruf."""
    hasil = []
    for h in daftar or []:
        t = re.sub(r"[\s\x00-\x1f#]+", "", str(h))[:49]
        if t and "#" + t not in hasil:
            hasil.append("#" + t)
    return hasil[:maks]


def ubah_teks_klip(k, project_id: int, clip_id: int, judul: str, caption: str, hashtags) -> dict | None:
    """Mengubah judul, caption, dan hashtag satu klip proyek ini. Mengembalikan klip yang sudah diperbarui, atau None bila tidak ada.
    Pemeriksaan pemilik proyek dilakukan pemanggil (lihat cari)."""
    hasil = k.execute(text("UPDATE clips SET title = :t, caption = :c, hashtags = :h WHERE id = :i AND project_id = :p"),
                      {"t": judul[:200], "c": caption[:500], "h": json.dumps(rapikan_hashtag(hashtags), ensure_ascii=False),
                       "i": clip_id, "p": project_id})
    if hasil.rowcount == 0:
        return None
    r = k.execute(text(f"SELECT {_KOLOM_KLIP} FROM clips WHERE id = :i AND project_id = :p"),
                  {"i": clip_id, "p": project_id}).first()
    return None if r is None else _publik_klip(r)


def cari_berkas_klip(k, project_id: int, clip_id: int):
    """(file_path relatif, judul) klip yang sudah jadi, atau None."""
    r = k.execute(text("SELECT file_path, title FROM clips WHERE id = :c AND project_id = :p "
                       "AND status IN ('done', 'rendering', 'failed')"),
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
