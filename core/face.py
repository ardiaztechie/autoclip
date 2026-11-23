"""face.py: melacak wajah (OpenCV YuNet) dan menyusun jalur jendela potong untuk rasio 9:16, 1:1, 4:5.

Hasilnya HANYA berupa jalur (posisi jendela potong tiap waktu). Belum memotong atau
merender video, dan belum ada zoom otomatis: jendela memakai ukuran terbesar yang muat.

Alur: video -> deteksi wajah tiap LANGKAH_SAMPEL detik -> pilih satu wajah utama ->
posisi tengah dihaluskan -> jalur jendela potong yang tidak keluar dari bingkai.

Seluruh angka di bagian "Nilai awal" adalah nilai AWAL YANG BELUM DIUJI (eksperimental), bukan
hasil penelitian. Disetel nanti lewat uji tampilan pada video nyata.

Model YuNet (berkas .onnx, sekitar 230 KB) diunduh sendiri. Lokasi dibaca dari .env:
    YUNET_MODEL=models/face_detection_yunet_2023mar.onnx

Cara pakai dari terminal:
    python -m core.face storage/uji/video_uji.mp4 --mulai 19.9 --akhir 43.7 --rasio 9:16 --gambar storage/uji/pratinjau.jpg
"""
import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# --- Nilai awal (eksperimental) ---------------------------------------------
MODEL_BAWAAN = "models/face_detection_yunet_2023mar.onnx"
LANGKAH_SAMPEL = 0.2          # detik antar deteksi
AMBANG_YAKIN = 0.6            # keyakinan minimum deteksi wajah (0-1)
LEBAR_DETEKSI_MAKS = 640      # gambar diperkecil sampai selebar ini sebelum dideteksi (kecepatan)
ALPHA_HALUS = 0.25            # 0-1; makin kecil makin halus tapi makin lambat mengikuti
ZONA_MATI = 0.05              # gerakan < 5% lebar jendela diabaikan (mengurangi getar)
TAHAN_TANPA_WAJAH = 1.5       # detik; bila wajah hilang, posisi terakhir ditahan selama ini
RASIO_VALID = {"9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5}


@dataclass(frozen=True)
class Kotak:
    x: float
    y: float
    w: float
    h: float
    skor: float = 1.0
    mata_y: float = None   # tinggi garis mata (rata-rata dua titik mata dari YuNet), piksel bingkai; None = tidak diketahui

    @property
    def pusat(self):
        return (self.x + self.w / 2, self.y + self.h / 2)

    @property
    def luas(self):
        return self.w * self.h


ZOOM_MASUK = 0.12     # detik: zoom penekanan masuk (cepat, terasa seperti cut)
ZOOM_KELUAR = 0.40    # detik: zoom penekanan keluar (halus)
FAKTOR_NAPAS = 1.08   # zoom pelan saat tenang: 1,00 -> 1,08 (atau sebaliknya)
NAPAS_MIN = 3.0       # detik: bagian tenang paling pendek yang diberi zoom pelan


def _halus_ease(u: float) -> float:
    """Lengkung mulus 0..1 (smoothstep): mulai dan berhenti pelan."""
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)


@dataclass(frozen=True)
class Jalur:
    titik: list            # [(waktu, x_kiri, y_atas)] dalam piksel bingkai asli, urut waktu
    lebar_potong: int
    tinggi_potong: int
    lebar_frame: int
    tinggi_frame: int
    rasio: str
    persen_berwajah: float  # 0-1: porsi sampel yang ada wajahnya
    selang_lebar: tuple = ()  # [(awal, akhir)] detik: tampilkan seluruh bingkai (bukan potongan)
    selang_zoom: tuple = ()   # [(awal, akhir)] detik: zoom in penekanan (potong langsung)
    faktor_zoom: float = 1.0  # jendela dipersempit menjadi 1/faktor selama selang_zoom
    titik_zoom: tuple = ()    # [(waktu, pusat_x, pusat_y)] pusat zoom (wajah pembicara); kosong = tengah jendela
    gaya: str = "lama"        # "lama": zoom potong langsung | "campuran": zoom masuk cepat/keluar halus + zoom napas
    selang_napas: tuple = ()  # [(awal, akhir, arah)] zoom pelan saat tenang; arah +1 mendekat, -1 menjauh
    titik_mata: tuple = ()    # [(waktu, y_mata)] tinggi garis mata pembicara; dipakai agar mata di sepertiga atas
    titik_dasar: tuple = ()   # [(waktu, faktor)] zoom dasar agar wajah kecil (shot lebar) mengisi bingkai; hanya gaya campuran

    def faktor_dasar(self, t: float) -> float:
        """Zoom dasar pada waktu t (>= 1,0), interpolasi linear; 1,0 bila tidak ada atau bukan gaya campuran."""
        p = self.titik_dasar
        if self.gaya != "campuran" or not p:
            return 1.0
        if t <= p[0][0]:
            return p[0][1]
        if t >= p[-1][0]:
            return p[-1][1]
        for (t0, f0), (t1, f1) in zip(p, p[1:]):
            if t0 <= t <= t1:
                return f0 if t1 == t0 else f0 + (t - t0) / (t1 - t0) * (f1 - f0)
        return p[-1][1]

    def faktor_pada(self, t: float) -> float:
        """Faktor zoom total pada waktu t (1,0 = tanpa zoom): zoom dasar x zoom tambahan (penekanan/napas)."""
        return self.faktor_dasar(t) * self.faktor_tambahan(t)

    def faktor_tambahan(self, t: float) -> float:
        """Faktor zoom penekanan atau napas saja. Gaya lama: 0/1 langsung; campuran: lengkung halus."""
        if self.gaya != "campuran":
            return self.faktor_zoom if any(a <= t <= b for a, b in self.selang_zoom) else 1.0
        for a, b in self.selang_zoom:
            if a <= t <= b:
                naik, turun = _halus_ease((t - a) / ZOOM_MASUK), _halus_ease((b - t) / ZOOM_KELUAR)
                return 1.0 + (self.faktor_zoom - 1.0) * min(naik, turun)
        for a, b, arah in self.selang_napas:
            if a <= t <= b and b > a:
                u = _halus_ease((t - a) / (b - a))
                return 1.0 + (FAKTOR_NAPAS - 1.0) * (u if arah > 0 else 1.0 - u)
        return 1.0

    def mata_pada(self, t: float):
        """Tinggi mata (piksel bingkai) pada waktu t, interpolasi linear; None bila tidak diketahui."""
        p = self.titik_mata
        if not p:
            return None
        if t <= p[0][0]:
            return p[0][1]
        if t >= p[-1][0]:
            return p[-1][1]
        for (t0, y0), (t1, y1) in zip(p, p[1:]):
            if t0 <= t <= t1:
                return y0 if t1 == t0 else y0 + (t - t0) / (t1 - t0) * (y1 - y0)
        return p[-1][1]

    def pada(self, t: float):
        """Posisi (x_kiri, y_atas) pada waktu t, interpolasi linear; di luar rentang = ujungnya."""
        p = self.titik
        if not p:
            return (0.0, 0.0)
        if t <= p[0][0]:
            return (p[0][1], p[0][2])
        if t >= p[-1][0]:
            return (p[-1][1], p[-1][2])
        for (t0, x0, y0), (t1, x1, y1) in zip(p, p[1:]):
            if t0 <= t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))
        return (p[-1][1], p[-1][2])

    def pusat_zoom(self, t: float):
        """Pusat zoom (x, y) pada waktu t: wajah pembicara bila ada, selain itu tengah jendela potong."""
        p = self.titik_zoom
        if not p:
            x, y = self.pada(t)
            return (x + self.lebar_potong / 2, y + self.tinggi_potong / 2)
        if t <= p[0][0]:
            return (p[0][1], p[0][2])
        if t >= p[-1][0]:
            return (p[-1][1], p[-1][2])
        for (t0, x0, y0), (t1, x1, y1) in zip(p, p[1:]):
            if t0 <= t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))
        return (p[-1][1], p[-1][2])


# ===========================================================================
# LOGIKA MURNI (tanpa video, mudah diuji)
# ===========================================================================
def ukuran_potong(lebar: int, tinggi: int, rasio: str) -> tuple:
    """Jendela terbesar berbentuk `rasio` yang muat di bingkai, dibulatkan ke bilangan genap."""
    if rasio not in RASIO_VALID:
        raise ValueError(f"rasio harus salah satu dari {tuple(RASIO_VALID)}, diterima: {rasio!r}")
    if not (isinstance(lebar, int) and isinstance(tinggi, int)) or lebar < 2 or tinggi < 2:
        raise ValueError("ukuran bingkai harus bilangan bulat >= 2")
    r = RASIO_VALID[rasio]
    if r <= lebar / tinggi:
        h, w = tinggi, tinggi * r
    else:
        w, h = lebar, lebar / r
    w, h = int(w) // 2 * 2, int(h) // 2 * 2
    return max(2, min(w, lebar)), max(2, min(h, tinggi))


def pilih_wajah(kotak_list, sebelumnya=None):
    """Satu wajah utama: terdekat dengan posisi sebelumnya bila ada, selain itu yang terbesar."""
    if not kotak_list:
        return None
    if sebelumnya is None:
        return max(kotak_list, key=lambda k: (k.luas, k.skor))
    sx, sy = sebelumnya
    return min(kotak_list, key=lambda k: (math.hypot(k.pusat[0] - sx, k.pusat[1] - sy), -k.luas))


def bangun_jalur(deteksi, lebar: int, tinggi: int, rasio: str = "9:16", *,
                 langkah: float = LANGKAH_SAMPEL, alpha: float = ALPHA_HALUS,
                 zona_mati: float = ZONA_MATI, tahan: float = TAHAN_TANPA_WAJAH) -> Jalur:
    """deteksi: [(waktu, [Kotak, ...])] urut waktu. Mengembalikan Jalur jendela potong."""
    if not (0 < alpha <= 1):
        raise ValueError("alpha harus di antara 0 (tidak termasuk) dan 1")
    if zona_mati < 0 or tahan < 0:
        raise ValueError("zona_mati dan tahan tidak boleh negatif")
    wp, hp = ukuran_potong(lebar, tinggi, rasio)
    pusat_bingkai = (lebar / 2, tinggi / 2)
    cx, cy = pusat_bingkai
    terakhir = None            # pusat wajah terakhir yang terlihat
    t_terakhir = None
    titik, ada = [], 0
    for t, kotak in deteksi:
        w = pilih_wajah(kotak, terakhir)
        if w is not None:
            ada += 1
            terakhir, t_terakhir = w.pusat, t
            sasaran = w.pusat
        elif terakhir is not None and t - t_terakhir <= tahan:
            sasaran = terakhir                       # tahan posisi terakhir
        else:
            sasaran = pusat_bingkai                  # wajah lama hilang: kembali ke tengah
        dx, dy = sasaran[0] - cx, sasaran[1] - cy
        if abs(dx) > zona_mati * wp:
            cx += alpha * dx
        if abs(dy) > zona_mati * hp:
            cy += alpha * dy
        x = min(max(cx - wp / 2, 0.0), lebar - wp)
        y = min(max(cy - hp / 2, 0.0), tinggi - hp)
        titik.append((round(float(t), 3), round(x, 2), round(y, 2)))
    persen = ada / len(titik) if titik else 0.0
    return Jalur(titik, wp, hp, lebar, tinggi, rasio, persen)


# ===========================================================================
# DETEKSI DARI VIDEO (butuh OpenCV dan berkas model)
# ===========================================================================
def jalur_model() -> Path:
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
    except ImportError:
        pass
    p = Path(os.getenv("YUNET_MODEL") or MODEL_BAWAAN)
    return p if p.is_absolute() else BASE / p


def deteksi_video(path_video, mulai: float, akhir: float, *, langkah: float = LANGKAH_SAMPEL,
                  path_model=None, ambang: float = AMBANG_YAKIN):
    """Mengembalikan (deteksi, lebar, tinggi, fps); deteksi = [(waktu, [Kotak])] tiap `langkah` detik.

    Waktu diambil dari nomor frame sebenarnya, bukan dari tebakan, karena posisi lompat (seek)
    pada sebagian codec hanya perkiraan.
    """
    if not (math.isfinite(mulai) and math.isfinite(akhir)) or mulai < 0 or akhir <= mulai:
        raise ValueError("mulai harus >= 0 dan akhir harus lebih besar dari mulai")
    if not math.isfinite(langkah) or langkah <= 0:
        raise ValueError("langkah harus positif")
    jalur = Path(path_video)
    if not jalur.is_file():
        raise FileNotFoundError(f"Berkas tidak ditemukan: {jalur}")
    model = Path(path_model) if path_model else jalur_model()
    if not model.is_file():
        raise FileNotFoundError(f"Model YuNet tidak ditemukan: {model} (lihat petunjuk unduh di core/face.py)")
    try:
        import cv2
    except ImportError:
        raise RuntimeError("opencv belum terpasang. Jalankan: pip install -r requirements.txt") from None

    cap = cv2.VideoCapture(str(jalur))
    try:
        if not cap.isOpened():
            raise ValueError(f"video tidak dapat dibuka: {jalur}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        lebar, tinggi = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not (fps and math.isfinite(fps) and fps > 0) or lebar <= 0 or tinggi <= 0:
            raise ValueError("fps atau ukuran video tidak terbaca")
        skala = min(1.0, LEBAR_DETEKSI_MAKS / lebar)
        dw, dh = max(1, int(round(lebar * skala))), max(1, int(round(tinggi * skala)))
        detektor = cv2.FaceDetectorYN.create(str(model), "", (dw, dh), ambang, 0.3, 5000)

        hasil = []
        awal = int(mulai * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, awal)
        idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))      # frame yang benar-benar akan dibaca berikutnya
        berikutnya = mulai
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / fps
            idx += 1
            if t > akhir:
                break
            if t + 1e-9 < berikutnya:
                continue
            berikutnya += langkah
            kecil = cv2.resize(frame, (dw, dh)) if skala < 1.0 else frame
            _, wajah = detektor.detect(kecil)
            kotak = []
            if wajah is not None:
                for r in wajah:
                    kotak.append(Kotak(float(r[0]) / skala, float(r[1]) / skala,
                                       float(r[2]) / skala, float(r[3]) / skala, float(r[14]),
                                       (float(r[5]) + float(r[7])) / 2 / skala))
            hasil.append((round(t, 3), kotak))
        return hasil, lebar, tinggi, fps
    finally:
        cap.release()


def lacak(path_video, mulai: float, akhir: float, rasio: str = "9:16", **kw) -> Jalur:
    deteksi, lebar, tinggi, _ = deteksi_video(path_video, mulai, akhir, path_model=kw.pop("path_model", None))
    if not deteksi:
        raise ValueError("tidak ada frame terbaca pada rentang waktu itu")
    return bangun_jalur(deteksi, lebar, tinggi, rasio, **kw)


# ===========================================================================
# TERMINAL
# ===========================================================================
def _gambar_pratinjau(path_video, jalur: Jalur, deteksi, t: float, tujuan: Path):
    import cv2
    cap = cv2.VideoCapture(str(path_video))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        return False
    terdekat = min(deteksi, key=lambda d: abs(d[0] - t))
    for k in terdekat[1]:
        cv2.rectangle(frame, (int(k.x), int(k.y)), (int(k.x + k.w), int(k.y + k.h)), (0, 255, 0), 2)
    x, y = jalur.pada(t)
    cv2.rectangle(frame, (int(x), int(y)), (int(x + jalur.lebar_potong), int(y + jalur.tinggi_potong)),
                  (0, 0, 255), 3)
    tujuan.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(tujuan), frame))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lacak wajah dan susun jalur jendela potong.")
    ap.add_argument("video")
    ap.add_argument("--mulai", type=float, required=True, help="detik awal")
    ap.add_argument("--akhir", type=float, required=True, help="detik akhir")
    ap.add_argument("--rasio", default="9:16", choices=list(RASIO_VALID))
    ap.add_argument("--simpan", default=None, help="simpan jalur ke berkas JSON")
    ap.add_argument("--gambar", default=None, help="simpan satu gambar pratinjau (kotak hijau wajah, merah jendela)")
    arg = ap.parse_args(argv)
    try:
        deteksi, lebar, tinggi, fps = deteksi_video(arg.video, arg.mulai, arg.akhir)
        if not deteksi:
            raise ValueError("tidak ada frame terbaca pada rentang waktu itu")
        jalur = bangun_jalur(deteksi, lebar, tinggi, arg.rasio)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"[GAGAL] {e}")
        return 1
    xs = [p[1] for p in jalur.titik]
    print(f"Bingkai asli    : {lebar}x{tinggi} @ {fps:.2f} fps")
    print(f"Jendela potong  : {jalur.lebar_potong}x{jalur.tinggi_potong} (rasio {jalur.rasio})")
    print(f"Sampel deteksi  : {len(jalur.titik)} (tiap {LANGKAH_SAMPEL} dtk)")
    print(f"Ada wajah       : {jalur.persen_berwajah:.0%} dari sampel")
    print(f"Rentang x kiri  : {min(xs):.0f} sampai {max(xs):.0f} (px)")
    if arg.simpan:
        tujuan = Path(arg.simpan)
        tujuan.parent.mkdir(parents=True, exist_ok=True)
        tujuan.write_text(json.dumps({"rasio": jalur.rasio, "lebar_potong": jalur.lebar_potong,
                                      "tinggi_potong": jalur.tinggi_potong, "titik": jalur.titik}), encoding="utf-8")
        print(f"Jalur disimpan  : {tujuan}")
    if arg.gambar:
        tengah = (arg.mulai + arg.akhir) / 2
        ok = _gambar_pratinjau(arg.video, jalur, deteksi, tengah, Path(arg.gambar))
        print(f"Pratinjau       : {arg.gambar}" if ok else "Pratinjau       : gagal dibuat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
