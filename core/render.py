"""render.py: memotong klip dari video, mengikuti jalur jendela potong (core.face), lalu menyimpan MP4.

Cara kerja: frame dibaca dengan OpenCV, dipotong sesuai jendela pada waktu itu, diperbesar/dikecilkan
ke ukuran keluaran, lalu dialirkan ke FFmpeg (H.264) bersama suara dari video asal.
Subtitle dibakar bila `kata` diberikan (core.subtitle). Zoom otomatis belum ada.

Ukuran keluaran (sisi lebar; tinggi mengikuti rasio):
    9:16 -> 1080x1920    1:1 -> 1080x1080    4:5 -> 1080x1350
Bila sumber lebih kecil dari ukuran itu (misalnya 360p), gambar diperbesar dan terlihat buram.
Itu batas kualitas sumber, bukan kesalahan program.

Lokasi FFmpeg: variabel lingkungan FFMPEG_PATH (di .env) atau ffmpeg di PATH.

Cara pakai dari terminal:
    python -m core.render storage/uji/video_uji.mp4 storage/uji/klip_energi.json --rasio 9:16 --folder storage/hasil
    ... tambahkan  --kata storage/uji/kata.json  untuk membakar subtitle
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .face import BASE, RASIO_VALID, Jalur, lacak, ukuran_potong
from .subtitle import ANIMASI, GAYA, POSISI, UKURAN, buat_ass
from .transcribe import dari_json

# --- Nilai awal ---------------------------------------------------------------
LEBAR_KELUARAN = 1080
CRF = 23                  # kualitas H.264: makin kecil makin bagus dan makin besar berkasnya
PRESET = "veryfast"
FAKTOR_ZOOM_BAWAAN = 1.25   # sama dengan core.penekanan.FAKTOR_ZOOM
BITRATE_AUDIO = "128k"


def cari_ffmpeg() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
    except ImportError:
        pass
    jalur = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")
    if not jalur:
        raise RuntimeError("FFmpeg tidak ditemukan. Pasang FFmpeg atau isi FFMPEG_PATH di .env")
    return jalur


def ukuran_keluaran(rasio: str, lebar: int = LEBAR_KELUARAN) -> tuple:
    """(lebar, tinggi) keluaran, keduanya genap."""
    if rasio not in RASIO_VALID:
        raise ValueError(f"rasio harus salah satu dari {tuple(RASIO_VALID)}, diterima: {rasio!r}")
    if isinstance(lebar, bool) or not isinstance(lebar, int) or lebar < 2 or lebar % 2:
        raise ValueError("lebar keluaran harus bilangan bulat genap >= 2")
    tinggi = int(round(lebar / RASIO_VALID[rasio]))
    return lebar, tinggi + tinggi % 2


def jalur_tengah(lebar: int, tinggi: int, rasio: str, durasi: float) -> Jalur:
    """Jendela diam di tengah bingkai (tanpa pelacakan wajah)."""
    wp, hp = ukuran_potong(lebar, tinggi, rasio)
    x, y = (lebar - wp) / 2, (tinggi - hp) / 2
    return Jalur([(0.0, x, y), (max(durasi, 0.001), x, y)], wp, hp, lebar, tinggi, rasio, 0.0)


def _jalur_filter(jalur) -> str:
    """Jalur berkas untuk filter FFmpeg: garis miring biasa, titik dua di-escape (mis. D:\\x -> D\\:/x)."""
    return str(jalur).replace("\\", "/").replace(":", "\\:")


def komposit_lebar(frame, kw: int, kh: int):
    """Seluruh bingkai tampil utuh di tengah, di atas latar buram dari bingkai yang sama."""
    import cv2
    h, w = frame.shape[:2]
    skala = min(kw / w, kh / h)
    fw, fh = max(2, int(round(w * skala))), max(2, int(round(h * skala)))
    kecil = cv2.resize(frame, (max(2, kw // 16), max(2, kh // 16)), interpolation=cv2.INTER_AREA)
    latar = cv2.resize(cv2.GaussianBlur(kecil, (5, 5), 0), (kw, kh), interpolation=cv2.INTER_LINEAR)
    latar = (latar * 0.6).astype(latar.dtype)                      # digelapkan agar bingkai utama menonjol
    depan = cv2.resize(frame, (fw, fh), interpolation=cv2.INTER_AREA if skala < 1 else cv2.INTER_CUBIC)
    x0, y0 = (kw - fw) // 2, (kh - fh) // 2
    latar[y0:y0 + fh, x0:x0 + fw] = depan
    return latar


def pusat_jendela_zoom(jalur: Jalur, t: float, hz: float, bobot_wajah: float = 1.0, bobot_mata: float = 0.0,
                       ikut_wajah_x: bool = True):
    """Pusat (x, y) jendela zoom. Gaya lama: pusat wajah pembicara. Campuran: pusat bergeser dari jendela
    biasa ke wajah sebesar `bobot_wajah` (agar tidak loncat saat zoom baru mulai), lalu sebesar `bobot_mata`
    digeser agar garis mata jatuh di sepertiga atas jendela (mata_y = atas + hz/3)."""
    x0, y0 = jalur.pada(t)
    nx, ny = x0 + jalur.lebar_potong / 2, y0 + jalur.tinggi_potong / 2
    zx, zy = jalur.pusat_zoom(t)
    cx = nx + bobot_wajah * (zx - nx) if ikut_wajah_x else nx
    cy = ny + bobot_wajah * (zy - ny)
    mata = jalur.mata_pada(t)
    if mata is not None and bobot_mata > 0:
        cy = cy + bobot_mata * ((mata + hz / 6.0) - cy)      # pusat = mata + hz/2 - hz/3
    return cx, cy


def potong_zoom(frame, jalur: Jalur, t: float, kw: int, kh: int):
    """Zoom in: jendela dipersempit 1/faktor, berpusat di wajah pembicara dan tetap di dalam bingkai.

    Gaya campuran: faktor mengikuti lengkung halus (Jalur.faktor_pada); zoom penekanan berpusat di wajah
    dengan mata di sepertiga atas, zoom napas mengikuti jendela biasa tetapi dengan garis mata yang sama."""
    import cv2
    h, w = frame.shape[:2]
    faktor = jalur.faktor_pada(t)
    wz = max(2, int(round(jalur.lebar_potong / faktor)))
    hz = max(2, int(round(jalur.tinggi_potong / faktor)))
    if jalur.gaya == "campuran":
        penekanan = any(a <= t <= b for a, b in jalur.selang_zoom)
        if penekanan:
            tambahan = jalur.faktor_tambahan(t)
            bobot = (tambahan - 1.0) / (jalur.faktor_zoom - 1.0) if jalur.faktor_zoom > 1.0 else 1.0
            cx, cy = pusat_jendela_zoom(jalur, t, hz, bobot, bobot)
        else:
            cx, cy = pusat_jendela_zoom(jalur, t, hz, 0.0, 1.0, ikut_wajah_x=False)
    else:
        cx, cy = jalur.pusat_zoom(t)
    x = int(round(min(max(cx - wz / 2, 0), w - wz)))
    y = int(round(min(max(cy - hz / 2, 0), h - hz)))
    return cv2.resize(frame[y:y + hz, x:x + wz], (kw, kh), interpolation=cv2.INTER_CUBIC)


def _dalam_selang(t: float, selang) -> bool:
    return any(a <= t <= b for a, b in selang)


def _ada_zoom(jalur: Jalur, t: float) -> bool:
    if jalur.gaya == "campuran":
        return jalur.faktor_pada(t) > 1.0005
    return bool(jalur.selang_zoom) and jalur.faktor_zoom > 1.0 and _dalam_selang(t, jalur.selang_zoom)


def render_klip(video, mulai: float, akhir: float, tujuan, *, rasio: str = "9:16", jalur: Jalur = None,
                lebar_keluaran: int = LEBAR_KELUARAN, kata=None, font: str = None,
                selang_zoom=(), faktor_zoom: float = None, pada_kemajuan=None,
                gaya_teks: str = None, posisi_teks: str = None, ukuran_teks: str = None,
                animasi_teks: str = None, buang=()) -> dict:
    """Merender satu klip ke `tujuan` (.mp4). Mengembalikan ringkasan {frame, durasi, ukuran, berkas}.

    jalur=None -> jendela diam di tengah. kata (list[Word]) diisi -> subtitle dibakar ke video. Berkas video tidak ada -> FileNotFoundError.
    Rentang atau parameter salah -> ValueError. FFmpeg tidak ada atau gagal -> RuntimeError.
    pada_kemajuan(bagian 0..1) dipanggil kira-kira tiap 15 frame (opsional).
    buang = [(a, b)] selang waktu video sumber yang dipotong dari klip (jeda): gambar, suara, dan subtitle ikut dibuang.
    """
    if not (math.isfinite(mulai) and math.isfinite(akhir)) or mulai < 0 or akhir <= mulai:
        raise ValueError("mulai harus >= 0 dan akhir harus lebih besar dari mulai")
    sumber = Path(video)
    if not sumber.is_file():
        raise FileNotFoundError(f"Berkas tidak ditemukan: {sumber}")
    kw, kh = ukuran_keluaran(rasio, lebar_keluaran)
    ffmpeg = cari_ffmpeg()
    try:
        import cv2
    except ImportError:
        raise RuntimeError("opencv belum terpasang. Jalankan: pip install -r requirements.txt") from None

    cap = cv2.VideoCapture(str(sumber))
    proses = None
    folder_ass = None
    tujuan = Path(tujuan)
    try:
        if not cap.isOpened():
            raise ValueError(f"video tidak dapat dibuka: {sumber}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        lebar, tinggi = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not (fps and math.isfinite(fps) and fps > 0) or lebar <= 0 or tinggi <= 0:
            raise ValueError("fps atau ukuran video tidak terbaca")
        if jalur is None:
            jalur = jalur_tengah(lebar, tinggi, rasio, akhir - mulai)
        elif (jalur.lebar_frame, jalur.tinggi_frame) != (lebar, tinggi):
            raise ValueError("ukuran bingkai pada jalur tidak sama dengan video")
        if selang_zoom and not jalur.selang_zoom:        # mode tanpa pelacak pembicara: zoom berpusat di jendela
            from .penekanan import FAKTOR_ZOOM
            from dataclasses import replace
            jalur = replace(jalur, selang_zoom=tuple(selang_zoom), faktor_zoom=faktor_zoom or FAKTOR_ZOOM)

        cap.set(cv2.CAP_PROP_POS_FRAMES, int(mulai * fps))
        idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        t_awal = idx / fps                       # waktu frame pertama yang benar-benar dibaca
        tujuan.parent.mkdir(parents=True, exist_ok=True)

        # Frame mentah masuk lewat pipa; suara diambil dari video asal pada waktu yang sama.
        # Durasi suara ditentukan setelah jumlah frame diketahui, jadi dipotong dengan -shortest.
        from .jeda import filter_suara, petakan_kata, selaraskan, total_buang
        buang = [(max(a, t_awal), min(b, akhir)) for a, b in selaraskan(buang or (), fps) if b > t_awal and a < akhir]
        buang = [(a, b) for a, b in buang if b > a]
        if buang and total_buang(buang) >= (akhir - t_awal) - 1.0 / fps:
            raise ValueError("seluruh klip akan terbuang; kurangi pemotongan jeda")
        akhir_ass = akhir - total_buang(buang)
        filter_suara_ = filter_suara(buang, t_awal)
        filter_video = []
        if kata:
            kata = petakan_kata(kata, buang) if buang else kata
            folder_ass = tempfile.mkdtemp(prefix="autoclip_")
            berkas_ass = Path(folder_ass) / "sub.ass"
            opsi = {k: v for k, v in (("font", font), ("gaya", gaya_teks), ("posisi", posisi_teks),
                                      ("ukuran", ukuran_teks), ("animasi", animasi_teks)) if v}
            berkas_ass.write_text(buat_ass(kata, t_awal, akhir_ass, kw, kh, **opsi), encoding="utf-8")
            filter_video = ["-vf", f"ass='{_jalur_filter(berkas_ass)}'"]
        perintah = [ffmpeg, "-y", "-loglevel", "error",
                    "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{kw}x{kh}", "-r", f"{fps:.5f}", "-i", "-",
                    "-ss", f"{t_awal:.3f}", "-t", f"{akhir - t_awal:.3f}", "-i", str(sumber),
                    "-map", "0:v:0", "-map", "1:a:0?", *filter_video, *(["-af", filter_suara_] if filter_suara_ else []),
                    "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", BITRATE_AUDIO, "-shortest", "-movflags", "+faststart", str(tujuan)]
        proses = subprocess.Popen(perintah, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

        n = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / fps
            idx += 1
            if t >= akhir:
                break
            if buang and any(a <= t < b for a, b in buang):
                continue
            if jalur.selang_lebar and _dalam_selang(t, jalur.selang_lebar):
                keluar = komposit_lebar(frame, kw, kh)
            elif _ada_zoom(jalur, t):
                keluar = potong_zoom(frame, jalur, t, kw, kh)
            else:
                x, y = jalur.pada(t)
                x = int(round(min(max(x, 0), lebar - jalur.lebar_potong)))
                y = int(round(min(max(y, 0), tinggi - jalur.tinggi_potong)))
                potong = frame[y:y + jalur.tinggi_potong, x:x + jalur.lebar_potong]
                antar = cv2.INTER_AREA if jalur.lebar_potong > kw else cv2.INTER_CUBIC
                keluar = cv2.resize(potong, (kw, kh), interpolation=antar)
            try:
                proses.stdin.write(keluar.tobytes())
            except BrokenPipeError:          # FFmpeg berhenti lebih dulu; alasannya dibaca dari stderr di bawah
                break
            n += 1
            if pada_kemajuan is not None and n % 15 == 0:
                pada_kemajuan(min(1.0, n / max(1.0, (akhir_ass - t_awal) * fps)))
        try:
            proses.stdin.close()
        except BrokenPipeError:
            pass
        _, galat = proses.communicate()
        if n == 0:
            raise ValueError("tidak ada frame terbaca pada rentang waktu itu")
        if proses.returncode != 0:
            raise RuntimeError("FFmpeg gagal: " + galat.decode("utf-8", "replace").strip()[-400:])
        return {"berkas": str(tujuan), "frame": n, "durasi": round(n / fps, 3), "ukuran": (kw, kh)}
    except BaseException:
        if proses is not None and proses.poll() is None:
            proses.kill()
        if tujuan.exists():
            try:
                tujuan.unlink()
            except OSError:
                pass
        raise
    finally:
        cap.release()
        if folder_ass:
            shutil.rmtree(folder_ass, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render klip terpilih menjadi MP4.")
    ap.add_argument("video")
    ap.add_argument("klip_json", help="berkas hasil core.pipeline --simpan (berisi mulai dan akhir)")
    ap.add_argument("--rasio", default="9:16", choices=list(RASIO_VALID))
    ap.add_argument("--folder", default="storage/hasil", help="folder keluaran")
    ap.add_argument("--mode", default="pembicara", choices=["pembicara", "satu-wajah", "tengah"],
                    help="pembicara: ikuti yang berbicara (banyak orang); satu-wajah: wajah terbesar; tengah: diam")
    ap.add_argument("--tengah", action="store_true", help="sama dengan --mode tengah")
    ap.add_argument("--kata", default=None, help="berkas kata.json dari core.transcribe; bila diisi, subtitle dibakar")
    ap.add_argument("--font", default=None, help="nama font subtitle (bawaan Arial)")
    ap.add_argument("--gaya-teks", default=None, choices=list(GAYA), help="gaya subtitle (bawaan klasik)")
    ap.add_argument("--posisi-teks", default=None, choices=list(POSISI), help="posisi subtitle (bawaan bawah)")
    ap.add_argument("--ukuran-teks", default=None, choices=list(UKURAN), help="ukuran subtitle (bawaan sedang)")
    ap.add_argument("--animasi-teks", default=None, choices=list(ANIMASI), help="animasi muncul subtitle (bawaan tanpa)")
    ap.add_argument("--tanpa-subtitle", action="store_true",
                    help="jangan bakar subtitle (kata tetap dipakai untuk pelacak pembicara dan zoom)")
    ap.add_argument("--buang", default=None, help='selang yang dipotong dari klip (jeda), JSON: [[a,b],...] dalam detik video sumber')
    ap.add_argument("--tanpa-zoom", action="store_true", help="matikan zoom in penekanan")
    ap.add_argument("--gaya-kamera", default="campuran", choices=["campuran", "lama"],
                    help="campuran: zoom masuk cepat/keluar halus, zoom pelan saat tenang, mata di sepertiga atas; "
                         "lama: zoom potong langsung (untuk perbandingan)")
    ap.add_argument("--potongan-kamera", action="store_true",
                    help="hidupkan potongan langsung ukuran gambar tiap 3-5 detik (bawaan: mati; kamera mengikuti wajah dengan gerak halus)")
    ap.add_argument("--faktor-zoom", type=float, default=None, help="besar zoom penekanan (bawaan 1,25)")
    ap.add_argument("--lebar", type=int, default=LEBAR_KELUARAN, help="lebar keluaran dalam piksel (genap)")
    arg = ap.parse_args(argv)
    try:
        daftar = json.loads(Path(arg.klip_json).read_text(encoding="utf-8"))
        if not isinstance(daftar, list) or not all(isinstance(k, dict) and {"mulai", "akhir"} <= k.keys()
                                                   for k in daftar):
            raise ValueError("berkas klip harus berupa daftar yang tiap itemnya punya mulai dan akhir")
        kata = dari_json(Path(arg.kata).read_text(encoding="utf-8")) if arg.kata else None
        terakhir = [-1]

        def lapor(persen: float, tahap: str):
            """Mencetak '[PROGRES] <persen> <tahap>' (hanya bila persen bulat berubah) untuk dibaca worker."""
            p = max(0, min(99, int(persen)))
            if p != terakhir[0]:
                terakhir[0] = p
                print(f"[PROGRES] {p} {tahap}", flush=True)

        n_klip = len(daftar)
        lapor(0, "Menganalisis suara")
        energi_zoom, ucapan = None, None
        if not arg.tanpa_zoom:
            from .audio import hitung_energi
            from .pembicara import ada_ucapan
            from .penekanan import LANGKAH_ENERGI
            try:
                energi_zoom = hitung_energi(arg.video, LANGKAH_ENERGI)
            except ValueError:                           # video tanpa suara: hanya kata emosi yang dipakai
                energi_zoom = None
            ucapan = ada_ucapan(kata) if kata is not None else None
        def peta(i: int, bagian: float) -> float:
            """Bagian 0..1 di dalam klip ke-i menjadi persen keseluruhan (5% pertama untuk analisis suara)."""
            return 5 + 94 * ((i - 1) + bagian) / n_klip

        for i, k in enumerate(daftar, 1):
            lapor(peta(i, 0), "Melacak wajah dan pembicara")
            tujuan = Path(arg.folder) / f"klip_{i:02d}_{arg.rasio.replace(':', 'x')}.mp4"
            mode = "tengah" if arg.tengah else arg.mode
            zoom = []
            if not arg.tanpa_zoom:
                from .penekanan import FAKTOR_ZOOM, selang_penekanan
                zoom = selang_penekanan(kata, k["mulai"], k["akhir"], energi_zoom, ucapan)
            faktor = arg.faktor_zoom or FAKTOR_ZOOM_BAWAAN
            if mode == "tengah":
                jalur = None
            elif mode == "satu-wajah":
                jalur = lacak(arg.video, k["mulai"], k["akhir"], arg.rasio)
            else:
                from .pembicara import lacak_pembicara
                jalur, _ = lacak_pembicara(arg.video, k["mulai"], k["akhir"], arg.rasio, kata=kata,
                                           selang_zoom=zoom, faktor_zoom=faktor,
                                           gaya=arg.gaya_kamera, napas=not arg.tanpa_zoom, potongan=arg.potongan_kamera,
                                           pada_kemajuan=lambda b, i=i: lapor(peta(i, 0.45 * b), "Melacak wajah dan pembicara"))
            buang_klip = [tuple(x) for x in json.loads(arg.buang)] if arg.buang else ()
            lapor(peta(i, 0.45), "Merender video")
            r = render_klip(arg.video, k["mulai"], k["akhir"], tujuan, rasio=arg.rasio, jalur=jalur,
                            lebar_keluaran=arg.lebar, kata=None if arg.tanpa_subtitle else kata, font=arg.font,
                            gaya_teks=arg.gaya_teks, posisi_teks=arg.posisi_teks, ukuran_teks=arg.ukuran_teks, animasi_teks=arg.animasi_teks,
                            buang=buang_klip,
                            selang_zoom=zoom if mode != "pembicara" else (), faktor_zoom=faktor,
                            pada_kemajuan=lambda b, i=i: lapor(peta(i, 0.45 + 0.55 * b), "Merender video"))
            ukuran_mb = Path(r["berkas"]).stat().st_size / 1_048_576
            wajah = ("tanpa pelacakan" if jalur is None else
                     f"wajah {jalur.persen_berwajah:.0%}, tampilan lebar {len(jalur.selang_lebar)}x")
            wajah += f", zoom {len(jalur.selang_zoom) if jalur is not None else len(zoom)}x"
            print(f"[{i}/{len(daftar)}] {tujuan}  {r['ukuran'][0]}x{r['ukuran'][1]}  "
                  f"{r['durasi']:.1f} dtk  {ukuran_mb:.1f} MB  ({wajah})")
    except (OSError, ValueError, RuntimeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
