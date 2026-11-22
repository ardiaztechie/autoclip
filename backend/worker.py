"""worker.py: mengambil pekerjaan dari job_queue dan memprosesnya (video -> klip jadi).

Menjalankan (jendela PowerShell tersendiri, dari folder proyek, .venv aktif, MySQL XAMPP menyala):
    python -m backend.worker            # berjalan terus, menunggu pekerjaan baru; hentikan dengan Ctrl+C
    python -m backend.worker --sekali   # mengerjakan semua antrean yang ada lalu berhenti

Tiap pekerjaan menjalankan `python -m core.jalankan` (transkripsi -> pilih klip -> judul/caption -> render) sebagai
proses terpisah, membaca keluarannya untuk memperbarui tahap dan progres di tabel projects, lalu menyimpan klip jadi
ke tabel clips dan waktu tiap tahap ke job_metrics (bahan tabel Bab 4).
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from . import antrean, config, proyek
from .konteks import GalatKonfigurasi, Konteks

BASE = config.BASE
log = logging.getLogger("autoclip.worker")

# nomor langkah core.jalankan -> (nama tampil, nama di job_metrics, progres saat tahap dimulai)
TAHAP = {1: ("Transkripsi", "transkripsi", 2), 2: ("Memilih klip", "pemilihan_klip", 47),
         3: ("Judul dan caption", "metadata", 52), 4: ("Render klip", "render", 55)}
PROGRES_RENDER_AWAL, PROGRES_RENDER_LEBAR, PROGRES_MAKS_BERJALAN = 55, 45, 99
PROGRES_UNDUH_AWAL, PROGRES_UNDUH_LEBAR = 1, 9           # unduhan YouTube mengisi 1% sampai 10%
FORMAT_UNDUH = "bv*[height<=1080]+ba/b[height<=1080]/b"  # video maksimal 1080p, audio terbaik, digabung jadi mp4

_POLA_LANGKAH = re.compile(r"^=== Langkah (\d+)/\d+: (.*) ===$")
_POLA_SELESAI = re.compile(r"^--- .+: selesai \(([\d.]+) dtk\)$")
_POLA_KLIP = re.compile(r"^\[(\d+)/(\d+)\] ")
_POLA_GAGAL = re.compile(r"^\[GAGAL\] (.*)$")
_POLA_UNDUH = re.compile(r"^\[download\]\s+(\d+(?:\.\d+)?)%")
_POLA_ERROR_YTDLP = re.compile(r"^ERROR:\s*(.*)$")


class GalatProses(Exception):
    """Pemrosesan gagal dengan alasan yang boleh ditampilkan kepada pengguna."""


# ===========================================================================
# MEMBACA KELUARAN core.jalankan
# ===========================================================================
def urai_baris(baris: str):
    """Mengubah satu baris keluaran core.jalankan menjadi peristiwa, atau None bila tidak relevan."""
    m = _POLA_LANGKAH.match(baris)
    if m and int(m.group(1)) in TAHAP:
        return {"jenis": "lewati" if "dilewati" in m.group(2) else "mulai", "langkah": int(m.group(1))}
    m = _POLA_SELESAI.match(baris)
    if m:
        return {"jenis": "selesai", "detik": float(m.group(1))}
    m = _POLA_KLIP.match(baris)
    if m:
        return {"jenis": "klip", "i": int(m.group(1)), "n": int(m.group(2))}
    m = _POLA_GAGAL.match(baris)
    if m:
        return {"jenis": "gagal", "pesan": m.group(1).strip()}
    return None


class Kemajuan:
    """Mengikuti peristiwa dan menghasilkan pembaruan {"stage", "progress"}. Progres tidak pernah turun."""

    def __init__(self, progres_awal: int = 0):
        self.langkah = None
        self.progres = progres_awal
        self.metrik = []              # [(nama tahap, detik)]
        self.pesan_gagal = None

    def terapkan(self, p):
        if p is None:
            return None
        jenis = p["jenis"]
        if jenis in ("mulai", "lewati"):
            self.langkah = p["langkah"]
            if jenis == "lewati":
                return None
            nama, _, awal = TAHAP[self.langkah]
            return self._maju(nama, awal)
        if jenis == "selesai":
            if self.langkah is not None:
                self.metrik.append((TAHAP[self.langkah][1], p["detik"]))
            return None
        if jenis == "klip":
            if self.langkah == 4 and 1 <= p["i"] <= p["n"]:
                persen = PROGRES_RENDER_AWAL + int(PROGRES_RENDER_LEBAR * p["i"] / p["n"])
                return self._maju(f"Render klip {p['i']}/{p['n']}", persen)
            return None
        if jenis == "gagal":
            self.pesan_gagal = p["pesan"]
        return None

    def _maju(self, tahap: str, persen: int) -> dict:
        self.progres = max(self.progres, min(PROGRES_MAKS_BERJALAN, persen))
        return {"stage": tahap, "progress": self.progres}


# ===========================================================================
# MENJALANKAN PEMROSESAN
# ===========================================================================
def durasi_video(jalur):
    """Durasi video (detik) dari header berkas, atau None bila tidak terbaca."""
    try:
        import av
        with av.open(str(jalur)) as wadah:
            return wadah.duration / av.time_base if wadah.duration else None
    except Exception:  # noqa: BLE001  (berkas rusak atau PyAV tidak ada: biarkan transkripsi yang melaporkan)
        return None


def susun_argv(video, folder_hasil, p: dict) -> list:
    argv = [sys.executable, "-m", "core.jalankan", str(video), "--folder", str(folder_hasil), "--rasio", p["ratio"]]
    if p["n_clips"] is not None:                       # jumlah pasti dari pengguna
        argv += ["--n", str(p["n_clips"])]
    else:                                              # otomatis: menurut durasi video dan kepadatan
        argv += ["--tingkat", p["clip_density"]]
    argv += ["--durasi", p["clip_length"]]
    if p["language"] != "auto":
        argv += ["--bahasa", p["language"]]
    if not p["face_tracking"]:
        argv += ["--mode", "tengah"]
    return argv


def jalankan_proses(argv, cwd, pada_baris) -> int:
    """Menjalankan proses anak dan memanggil pada_baris(teks) untuk tiap baris keluarannya."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    with subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace") as proses:
        try:
            for baris in proses.stdout:
                pada_baris(baris.rstrip("\r\n"))
        except BaseException:
            proses.kill()
            raise
        return proses.wait()


def bersihkan_pesan(pesan: str, folder_storage: Path) -> str:
    """Membuang lokasi folder di server dari pesan sebelum ditampilkan kepada pengguna."""
    for lokasi, ganti in ((str(folder_storage), "storage"), (folder_storage.as_posix(), "storage"),
                          (str(BASE), "."), (BASE.as_posix(), ".")):
        pesan = pesan.replace(lokasi, ganti)
    return pesan[:500]


def _bersihkan_sumber(folder_proyek: Path) -> None:
    """Membuang sisa unduhan (source.* termasuk .part) agar percobaan berikutnya mulai dari awal."""
    for sisa in folder_proyek.glob("source.*"):
        sisa.unlink(missing_ok=True)


def _pesan_ytdlp(baris: list) -> str:
    for b in reversed(baris):
        m = _POLA_ERROR_YTDLP.match(b)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def _periksa_durasi(detik, proses_cfg) -> None:
    """Menolak video yang lebih panjang dari batas. Tanpa batas (None) = semua durasi diterima."""
    batas = proses_cfg.get("maks_durasi_detik")
    if detik and batas and detik > batas:
        raise GalatProses(f"Durasi video {detik / 60:.1f} menit melebihi batas {batas / 60:g} menit")


def unduh_youtube(engine, pid: int, p: dict, folder_proyek: Path, cfg: dict, proses_cfg: dict, ubah, *, runner):
    """Mengunduh video dari tautan YouTube ke folder proyek (source.mp4). Mengembalikan (jalur video, durasi atau None).
    Dua langkah: baca info (judul, durasi) lebih dulu supaya video yang terlalu panjang ditolak sebelum diunduh."""
    url = p["source_ref"]
    ubah(status="processing", stage="Mengunduh video", progress=PROGRES_UNDUH_AWAL, error=None)
    yt = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings"]

    info = []
    kode = runner(yt + ["--skip-download", "--print", "%(duration)s\t%(title)s", "--", url], BASE, info.append)
    if kode != 0:
        alasan = _pesan_ytdlp(info) or f"kode {kode}"
        raise GalatProses(f"Gagal membaca video dari YouTube: {alasan}")
    detik, judul = None, ""
    for b in reversed(info):
        if "\t" in b:
            bagian, judul = b.split("\t", 1)
            try:
                detik = float(bagian)
            except ValueError:
                detik = None
            break
    pembaruan = {}
    if judul.strip() and not p["title"].strip():
        pembaruan["title"] = judul.strip()[:200]
    if detik:
        pembaruan["duration_sec"] = detik
    if pembaruan:
        ubah(**pembaruan)
    _periksa_durasi(detik, proses_cfg)

    unduhan = []

    def pada_baris(baris):
        unduhan.append(baris)
        m = _POLA_UNDUH.match(baris)
        if m:
            persen = PROGRES_UNDUH_AWAL + int(PROGRES_UNDUH_LEBAR * min(100.0, float(m.group(1))) / 100)
            ubah(stage="Mengunduh video", progress=persen)

    argv = yt + ["--newline", "-f", FORMAT_UNDUH, "--merge-output-format", "mp4",
                 "--max-filesize", str(cfg["maks_bytes"]), "-o", str(folder_proyek / "source.%(ext)s"), "--", url]
    try:
        kode = runner(argv, BASE, pada_baris)
    except BaseException:
        _bersihkan_sumber(folder_proyek)
        raise
    sumber = sorted(folder_proyek.glob("source.*"))
    if kode != 0 or not sumber or any(s.suffix == ".part" for s in sumber):
        _bersihkan_sumber(folder_proyek)
        if kode != 0:
            raise GalatProses(f"Gagal mengunduh dari YouTube: {_pesan_ytdlp(unduhan) or f'kode {kode}'}")
        raise GalatProses("Unduhan selesai tetapi berkas video tidak ditemukan")
    return sumber[0], detik


def baca_hasil(folder_hasil: Path, ratio: str, folder_storage: Path) -> list:
    """Membaca klip.json, metadata.json, dan berkas klip jadi. Salah satu klip hilang = GalatProses."""
    try:
        klip = json.loads((folder_hasil / "klip.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GalatProses("Hasil pemilihan klip tidak ditemukan") from None
    if not isinstance(klip, list) or not klip:
        raise GalatProses("Tidak ada klip yang terpilih dari video ini")
    try:
        meta = json.loads((folder_hasil / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = []
    if not isinstance(meta, list):
        meta = []
    hasil = []
    for i, k in enumerate(klip, 1):
        berkas = folder_hasil / f"klip_{i:02d}_{ratio.replace(':', 'x')}.mp4"
        if not berkas.is_file():
            raise GalatProses(f"Klip ke-{i} belum jadi (berkas hasil render tidak ditemukan)")
        m = meta[i - 1] if i - 1 < len(meta) and isinstance(meta[i - 1], dict) else {}
        tag = m.get("hashtag") if isinstance(m.get("hashtag"), list) else []
        try:
            hasil.append({
                "start": float(k["mulai"]), "end": float(k["akhir"]), "score": float(k.get("skor", 0)),
                "hook": float(k.get("hook", 0)), "flow": float(k.get("flow", 0)),
                "value": float(k.get("value", 0)), "trend": float(k.get("trend", 0)),
                "title": str(m.get("judul") or f"Klip {i}"), "caption": str(m.get("caption") or ""),
                "hashtags": [str(x) for x in tag],
                "file_path": berkas.relative_to(folder_storage).as_posix(), "size_bytes": berkas.stat().st_size})
        except (KeyError, TypeError, ValueError, AttributeError):
            raise GalatProses("Format hasil pemilihan klip tidak sesuai") from None
    return hasil


def proses_proyek(engine, job: dict, cfg: dict, proses_cfg: dict, *, runner=jalankan_proses, durasi=durasi_video):
    """Mengerjakan satu pekerjaan process_project. Gagal = GalatProses (atau galat tak terduga)."""
    payload = job["payload"]
    if not isinstance(payload, dict) or isinstance(payload.get("project_id"), bool) \
            or not isinstance(payload.get("project_id"), int):
        raise GalatProses("Isi pekerjaan tidak valid")
    pid = payload["project_id"]
    with engine.connect() as k:
        p = proyek.ambil_untuk_proses(k, pid)
    if p is None:
        raise GalatProses("Proyek tidak ditemukan")
    if p["status"] == "done":
        return                                                   # pekerjaan ganda untuk proyek yang sudah selesai
    folder_proyek = cfg["folder"] / "projects" / str(pid)
    sumber = sorted(folder_proyek.glob("source.*"))

    def ubah(**nilai):
        with engine.begin() as k:
            proyek.ubah(k, pid, **nilai)

    diunduh = False
    if not sumber and p["source_type"] == "link":
        folder_proyek.mkdir(parents=True, exist_ok=True)
        video, detik_info = unduh_youtube(engine, pid, p, folder_proyek, cfg, proses_cfg, ubah, runner=runner)
        diunduh = True
    elif not sumber:
        raise GalatProses("Berkas video proyek tidak ditemukan di server")
    else:
        video, detik_info = sumber[0], None

    detik = durasi(video) or detik_info
    ubah(status="processing", stage="Menyiapkan", progress=PROGRES_UNDUH_AWAL + (PROGRES_UNDUH_LEBAR if diunduh else 0),
         error=None, **({"duration_sec": detik} if detik else {}))
    _periksa_durasi(detik, proses_cfg)

    folder_hasil = folder_proyek / "hasil"
    folder_hasil.mkdir(parents=True, exist_ok=True)
    kemajuan, baris_log = Kemajuan(PROGRES_UNDUH_AWAL + PROGRES_UNDUH_LEBAR if diunduh else 0), []

    def pada_baris(baris):
        baris_log.append(baris)
        perubahan = kemajuan.terapkan(urai_baris(baris))
        if perubahan:
            ubah(**perubahan)

    try:
        kode = runner(susun_argv(video, folder_hasil, p), BASE, pada_baris)
    finally:
        try:
            (folder_proyek / "proses.log").write_text("\n".join(baris_log) + "\n", encoding="utf-8")
        except OSError:
            log.warning("log proses tidak bisa ditulis")
    if kode != 0:
        raise GalatProses(kemajuan.pesan_gagal or f"Pemrosesan gagal (kode {kode})")

    klip = baca_hasil(folder_hasil, p["ratio"], cfg["folder"])
    with engine.begin() as k:                                    # klip, metrik, dan status selesai: satu transaksi
        proyek.simpan_klip(k, pid, p["ratio"], klip)
        for tahap, lama in kemajuan.metrik:
            proyek.catat_metrik(k, job["id"], pid, tahap, lama, detik)
        proyek.ubah(k, pid, status="done", stage="Selesai", progress=100, error=None)


def kerjakan(engine, job, cfg, proses_cfg, *, runner=jalankan_proses, durasi=durasi_video) -> bool:
    """Mengerjakan satu pekerjaan dan mencatat hasilnya di job_queue. True bila berhasil.
    KeyboardInterrupt tidak ditangkap: pekerjaan tetap 'running' dan dipulihkan saat worker dinyalakan lagi."""
    pid = job["payload"].get("project_id") if isinstance(job["payload"], dict) else None
    try:
        proses_proyek(engine, job, cfg, proses_cfg, runner=runner, durasi=durasi)
    except GalatProses as e:
        pesan = bersihkan_pesan(str(e), cfg["folder"])
    except Exception:  # noqa: BLE001
        log.exception("galat tak terduga pada pekerjaan %s", job["id"])
        pesan = "Terjadi kesalahan tak terduga saat memproses video"
    else:
        with engine.begin() as k:
            antrean.selesai(k, job["id"])
        return True
    with engine.begin() as k:
        antrean.gagal(k, job["id"], pesan)
        if isinstance(pid, int) and not isinstance(pid, bool):
            proyek.ubah(k, pid, status="failed", stage="Gagal", error=pesan)
    log.warning("pekerjaan %s gagal: %s", job["id"], pesan)
    return False


def pulihkan(engine) -> list:
    """Mengembalikan pekerjaan yang terputus (worker sebelumnya mati) dan menyesuaikan status proyeknya."""
    with engine.begin() as k:
        hasil = antrean.pulihkan_terhenti(k)
        for _job, pid, diulang in hasil:
            if pid is None:
                continue
            if diulang:
                proyek.ubah(k, pid, status="queued", stage="Antre", progress=0)
            else:
                proyek.ubah(k, pid, status="failed", stage="Gagal", error="Pemrosesan terhenti berulang kali")
    return hasil


def jalankan_worker(engine, cfg, proses_cfg, *, runner=jalankan_proses, durasi=durasi_video, sekali=False,
                    jeda=2.0, tidur=time.sleep, berhenti=lambda: False) -> int:
    """Perulangan utama. Mengembalikan jumlah pekerjaan yang dikerjakan (berguna untuk tes dan --sekali)."""
    for job_id, pid, diulang in pulihkan(engine):
        log.info("pekerjaan %s (proyek %s) terputus sebelumnya: %s", job_id, pid, "diulang" if diulang else "digagalkan")
    dikerjakan = 0
    while not berhenti():
        try:
            with engine.begin() as k:
                job = antrean.ambil(k)
        except SQLAlchemyError as e:
            log.warning("database tidak bisa dihubungi: %s", e)
            if sekali:
                raise
            tidur(jeda * 5)
            continue
        if job is None:
            if sekali:
                break
            tidur(jeda)
            continue
        log.info("mengerjakan pekerjaan %s", job["id"])
        kerjakan(engine, job, cfg, proses_cfg, runner=runner, durasi=durasi)
        dikerjakan += 1
    return dikerjakan


def main(argv=None, *, konteks=None) -> int:
    ap = argparse.ArgumentParser(description="Worker AutoClip: memproses antrean video menjadi klip.")
    ap.add_argument("--sekali", action="store_true", help="kerjakan antrean yang ada lalu berhenti")
    ap.add_argument("--jeda", type=float, default=2.0, help="detik menunggu bila antrean kosong (bawaan 2)")
    arg = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    try:
        k = konteks or Konteks()
        engine, cfg = k.engine(), k.unggah()
        proses_cfg = config.pengaturan_proses()
    except (GalatKonfigurasi, ValueError) as e:
        print(f"[GAGAL] {e}")
        return 1
    print("Worker AutoClip berjalan." + ("" if arg.sekali else " Tekan Ctrl+C untuk berhenti."))
    try:
        n = jalankan_worker(engine, cfg, proses_cfg, sekali=arg.sekali, jeda=arg.jeda)
    except SQLAlchemyError:
        print("[GAGAL] Database tidak bisa dihubungi. Pastikan MySQL di XAMPP berstatus Running dan .env benar.")
        return 1
    except KeyboardInterrupt:
        print("\nWorker dihentikan. Pekerjaan yang sedang berjalan akan dilanjutkan saat worker dinyalakan lagi.")
        return 0
    print(f"Selesai: {n} pekerjaan dikerjakan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
