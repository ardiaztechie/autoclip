"""Pengujian core/render.py dengan video sintetis (butuh FFmpeg; dilewati bila tidak ada).

Jalankan: python -m pytest tests/test_render.py -v
"""
import json
import re
import shutil
import subprocess
import sys

import numpy as np
import pytest

from core import render as R
from core.face import Jalur

cv2 = pytest.importorskip("cv2")
ADA_FFMPEG = shutil.which("ffmpeg") is not None
butuh_ffmpeg = pytest.mark.skipif(not ADA_FFMPEG, reason="FFmpeg tidak terpasang")

FPS = 30
LEBAR, TINGGI = 320, 180


def buat_video(jalur, detik=4, dengan_suara=True):
    """Video sintetis: kecerahan frame ke-i = 10 + 2*i (penanda waktu), kotak putih di kiri/kanan."""
    sementara = jalur.with_suffix(".sunyi.mp4")
    w = cv2.VideoWriter(str(sementara), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LEBAR, TINGGI))
    for i in range(detik * FPS):
        f = np.full((TINGGI, LEBAR, 3), min(10 + 2 * i, 250), np.uint8)
        w.write(f)
    w.release()
    if not dengan_suara:
        sementara.replace(jalur)
        return jalur
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(sementara), "-f", "lavfi",
                    "-i", f"sine=frequency=440:duration={detik}", "-c:v", "copy", "-c:a", "aac", "-shortest",
                    str(jalur)], check=True)
    sementara.unlink()
    return jalur


def info(jalur):
    import av
    with av.open(str(jalur)) as c:
        v = c.streams.video[0]
        return {"w": v.codec_context.width, "h": v.codec_context.height, "audio": len(c.streams.audio),
                "codec": v.codec_context.name, "durasi": float(c.duration) / 1_000_000 if c.duration else 0.0}


def kecerahan_frame(jalur, nomor):
    cap = cv2.VideoCapture(str(jalur))
    cap.set(cv2.CAP_PROP_POS_FRAMES, nomor)
    ok, f = cap.read()
    cap.release()
    assert ok
    return float(f.mean())


# ---------------------------------------------------------------- tanpa FFmpeg
@pytest.mark.parametrize("rasio,hasil", [("9:16", (1080, 1920)), ("1:1", (1080, 1080)), ("4:5", (1080, 1350))])
def test_ukuran_keluaran(rasio, hasil):
    assert R.ukuran_keluaran(rasio) == hasil


@pytest.mark.parametrize("args", [("16:9", 1080), ("9:16", 0), ("9:16", 1081), ("9:16", True), ("9:16", 1.5)])
def test_ukuran_keluaran_tidak_valid(args):
    with pytest.raises(ValueError):
        R.ukuran_keluaran(*args)


def test_jalur_tengah_berada_di_tengah():
    j = R.jalur_tengah(640, 360, "9:16", 10.0)
    assert j.pada(5.0) == ((640 - 202) / 2, 0.0) and (j.lebar_potong, j.tinggi_potong) == (202, 360)


def test_video_tidak_ada(tmp_path):
    with pytest.raises(FileNotFoundError):
        R.render_klip(tmp_path / "x.mp4", 0, 1, tmp_path / "o.mp4")


@pytest.mark.parametrize("mulai,akhir", [(5, 5), (5, 1), (-1, 3), (float("nan"), 3)])
def test_rentang_salah(tmp_path, mulai, akhir):
    with pytest.raises(ValueError):
        R.render_klip(tmp_path / "x.mp4", mulai, akhir, tmp_path / "o.mp4")


def test_ffmpeg_tidak_ada(tmp_path, monkeypatch):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.setattr(R.shutil, "which", lambda _: None)
    monkeypatch.setattr(R, "BASE", tmp_path / "tidak_ada")
    with pytest.raises(RuntimeError, match="FFmpeg"):
        R.render_klip(v, 0, 1, tmp_path / "o.mp4")


# ---------------------------------------------------------------- dengan FFmpeg
@butuh_ffmpeg
def test_render_menghasilkan_mp4_9x16_dengan_suara(tmp_path):
    v = buat_video(tmp_path / "v.mp4")
    out = tmp_path / "hasil" / "k.mp4"
    r = R.render_klip(v, 1.0, 3.0, out, rasio="9:16", lebar_keluaran=360)
    i = info(out)
    assert (i["w"], i["h"]) == (360, 640) and i["codec"] == "h264" and i["audio"] == 1
    assert r["ukuran"] == (360, 640) and abs(r["durasi"] - 2.0) < 0.1
    assert abs(i["durasi"] - 2.0) < 0.2


@butuh_ffmpeg
@pytest.mark.parametrize("rasio,ukuran", [("1:1", (360, 360)), ("4:5", (360, 450))])
def test_rasio_lain(tmp_path, rasio, ukuran):
    v = buat_video(tmp_path / "v.mp4", detik=3)
    out = tmp_path / "k.mp4"
    R.render_klip(v, 0.5, 2.0, out, rasio=rasio, lebar_keluaran=360)
    i = info(out)
    assert (i["w"], i["h"]) == ukuran


@butuh_ffmpeg
def test_awal_klip_sesuai_waktu_mulai(tmp_path):
    """Frame pertama klip harus berasal dari sekitar detik `mulai` (kecerahan = 10 + 2 * nomor frame)."""
    v = buat_video(tmp_path / "v.mp4", detik=4)
    out = tmp_path / "k.mp4"
    R.render_klip(v, 2.0, 3.0, out, rasio="1:1", lebar_keluaran=180)
    harapan = 10 + 2 * (2.0 * FPS)
    assert abs(kecerahan_frame(out, 0) - harapan) < 8


@butuh_ffmpeg
def test_video_tanpa_suara_tetap_bisa_dirender(tmp_path):
    v = buat_video(tmp_path / "v.mp4", detik=3, dengan_suara=False)
    out = tmp_path / "k.mp4"
    R.render_klip(v, 0.0, 1.5, out, lebar_keluaran=180)
    assert info(out)["audio"] == 0


@butuh_ffmpeg
def test_jalur_bergerak_dipakai(tmp_path):
    """Jendela bergerak dari kiri ke kanan; isi frame diwarnai agar terbaca di keluaran."""
    sementara = tmp_path / "w.mp4"
    w = cv2.VideoWriter(str(sementara), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LEBAR, TINGGI))
    for _ in range(3 * FPS):
        f = np.zeros((TINGGI, LEBAR, 3), np.uint8)
        f[:, :LEBAR // 2] = (0, 0, 255)       # kiri merah
        f[:, LEBAR // 2:] = (255, 0, 0)       # kanan biru (BGR)
        w.write(f)
    w.release()
    wp, hp = 100, 180
    jalur = Jalur([(0.0, 0.0, 0.0), (2.9, float(LEBAR - wp), 0.0)], wp, hp, LEBAR, TINGGI, "9:16", 1.0)
    out = tmp_path / "k.mp4"
    R.render_klip(sementara, 0.0, 2.9, out, rasio="9:16", jalur=jalur, lebar_keluaran=180)
    awal, akhir = cv2.VideoCapture(str(out)), cv2.VideoCapture(str(out))
    akhir.set(cv2.CAP_PROP_POS_FRAMES, 80)
    _, f0 = awal.read()
    _, f1 = akhir.read()
    assert f0[:, :, 2].mean() > f0[:, :, 0].mean() + 100        # awal: dominan merah
    assert f1[:, :, 0].mean() > f1[:, :, 2].mean() + 100        # akhir: dominan biru


@butuh_ffmpeg
def test_jalur_ukuran_salah_ditolak(tmp_path):
    v = buat_video(tmp_path / "v.mp4", detik=2)
    salah = Jalur([(0.0, 0.0, 0.0)], 10, 10, 999, 999, "1:1", 1.0)
    with pytest.raises(ValueError):
        R.render_klip(v, 0, 1, tmp_path / "k.mp4", jalur=salah)
    assert not (tmp_path / "k.mp4").exists()


@butuh_ffmpeg
def test_terminal_merender_semua_klip(tmp_path, capsys):
    v = buat_video(tmp_path / "v.mp4", detik=4)
    daftar = tmp_path / "klip.json"
    daftar.write_text(json.dumps([{"mulai": 0.5, "akhir": 1.5}, {"mulai": 2.0, "akhir": 3.0}]), encoding="utf-8")
    kode = R.main([str(v), str(daftar), "--tengah", "--folder", str(tmp_path / "h"), "--lebar", "180"])
    assert kode == 0
    assert (tmp_path / "h" / "klip_01_9x16.mp4").is_file() and (tmp_path / "h" / "klip_02_9x16.mp4").is_file()
    keluar = capsys.readouterr().out
    assert "[2/2]" in keluar
    persen = [int(m) for m in re.findall(r"^\[PROGRES\] (\d+) ", keluar, re.M)]
    assert persen and persen[0] == 0 and persen == sorted(persen) and persen[-1] < 100     # naik terus, 100 tidak dicetak
    assert "[PROGRES]" in keluar and "Merender video" in keluar


@butuh_ffmpeg
def test_render_klip_melapor_kemajuan_antara_0_dan_1(tmp_path):
    v = buat_video(tmp_path / "v.mp4", detik=4)
    bagian = []
    R.render_klip(v, 0, 3, tmp_path / "k.mp4", lebar_keluaran=180, pada_kemajuan=bagian.append)
    assert bagian and all(0 <= b <= 1 for b in bagian) and bagian == sorted(bagian)


def test_terminal_klip_json_rusak(tmp_path, capsys):
    f = tmp_path / "k.json"
    f.write_text('{"bukan": "daftar"}', encoding="utf-8")
    assert R.main([str(tmp_path / "v.mp4"), str(f)]) == 1
    assert "[GAGAL]" in capsys.readouterr().out


@butuh_ffmpeg
def test_tampilan_lebar_dipakai_pada_selang_waktu(tmp_path):
    v = buat_video(tmp_path / "v.mp4", detik=4)
    jalur = Jalur([(0.0, 0.0, 0.0), (3.0, 0.0, 0.0)], 100, 180, LEBAR, TINGGI, "9:16", 1.0, ((1.0, 2.0),))
    out = tmp_path / "k.mp4"
    R.render_klip(v, 0.0, 3.0, out, rasio="9:16", jalur=jalur, lebar_keluaran=180)

    def baris(nomor):
        c = cv2.VideoCapture(str(out)); c.set(cv2.CAP_PROP_POS_FRAMES, nomor); ok, f = c.read(); c.release()
        assert ok
        return float(f[5].mean()), float(f[f.shape[0] // 2].mean())
    atas, tengah = baris(10)                       # detik ~0,3: potongan biasa, seragam
    assert abs(atas - tengah) < 6
    atas, tengah = baris(45)                       # detik ~1,5: tampilan lebar, latar atas digelapkan
    assert atas < tengah * 0.8


# ---------------------------------------------------------------- pusat zoom campuran
def _jalur_campuran(mata=120.0, tinggi=360):
    return Jalur([(0.0, 200.0, 0.0), (10.0, 200.0, 0.0)], 202, tinggi, 640, tinggi, "9:16", 1.0, (), ((2.0, 6.0),),
                 1.25, ((0.0, 400.0, 180.0), (10.0, 400.0, 180.0)), "campuran",
                 titik_mata=((0.0, mata), (10.0, mata)))


def test_pusat_zoom_mata_di_sepertiga_atas():
    j = _jalur_campuran(mata=140.0)
    hz = 288.0
    cx, cy = R.pusat_jendela_zoom(j, 4.0, hz, 1.0, 1.0)
    assert cx == pytest.approx(400.0)                                    # ikut wajah
    atas = cy - hz / 2
    assert 140.0 - atas == pytest.approx(hz / 3)                         # mata tepat di 1/3 tinggi jendela


def test_pusat_zoom_bobot_nol_sama_dengan_jendela_biasa():
    j = _jalur_campuran()
    cx, cy = R.pusat_jendela_zoom(j, 4.0, 288.0, 0.0, 0.0)
    assert (cx, cy) == (pytest.approx(301.0), pytest.approx(180.0))


def test_pusat_zoom_napas_x_tidak_ikut_wajah():
    j = _jalur_campuran()
    cx, _ = R.pusat_jendela_zoom(j, 4.0, 333.0, 0.0, 1.0, ikut_wajah_x=False)
    assert cx == pytest.approx(301.0)


def test_potong_zoom_campuran_ukuran_dan_posisi():
    frame = np.zeros((360, 640, 3), np.uint8)
    frame[:, :, :] = 0
    frame[:, 350:450] = 255                                              # kolom terang di sekitar wajah (x 400)
    keluar = R.potong_zoom(frame, _jalur_campuran(), 4.0, 108, 192)
    assert keluar.shape == (192, 108, 3)
    assert keluar[:, 40:70].mean() > 200                                 # wajah ada di tengah jendela zoom
    j = _jalur_campuran()
    assert R._ada_zoom(j, 4.0) and not R._ada_zoom(j, 8.0) and not R._ada_zoom(j, 2.0)   # ramp mulai dari 1,0


def test_potong_zoom_dengan_zoom_dasar_memperbesar_wajah():
    import numpy as np
    from core import render as R
    from core.face import Jalur
    frame = np.zeros((360, 640, 3), np.uint8)
    frame[130:230, 270:370] = 255                                  # "wajah" 100x100 di tengah
    dasar = ((0.0, 1.8), (5.0, 1.8))
    j = Jalur([(0.0, 219.0, 0.0), (5.0, 219.0, 0.0)], 202, 360, 640, 360, "9:16", 1.0, gaya="campuran",
              titik_zoom=((0.0, 320.0, 180.0), (5.0, 320.0, 180.0)), titik_dasar=dasar)
    polos = Jalur([(0.0, 219.0, 0.0), (5.0, 219.0, 0.0)], 202, 360, 640, 360, "9:16", 1.0, gaya="campuran")
    a = R.potong_zoom(frame, j, 1.0, 270, 480)
    b = R.potong_zoom(frame, polos, 1.0, 270, 480) if R._ada_zoom(polos, 1.0) else None
    assert R._ada_zoom(j, 1.0) and b is None
    assert a.shape == (480, 270, 3) and (a > 200).mean() > 0.3          # kotak putih mengisi sebagian besar bingkai


@butuh_ffmpeg
def test_potongan_ukuran_gambar_berganti_langsung_bukan_bertahap(tmp_path):
    """Wajah tiruan (lingkaran) di video 640x360; jalur dari susun_jalur(potongan=True): ukuran wajah di layar harus
    melompat dalam satu frame saat potongan, dan tidak berubah bertahap di antaranya."""
    import cv2
    from core import pembicara as P
    from core.face import Kotak
    L, T, FPS = 640, 360, 25
    v = tmp_path / "w.mp4"
    w = cv2.VideoWriter(str(v), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (L, T))
    for _ in range(9 * FPS):
        f = np.zeros((T, L, 3), np.uint8)
        f[:] = (60, 70, 50)
        cv2.circle(f, (320, 150), 40, (170, 190, 225), -1)
        w.write(f)
    w.release()
    sampel = [P.Sampel(round(i * 0.1, 3), (P.Pengamatan(1, Kotak(280, 110, 80, 80, 0.9, 140), 3.0, 1.0),), False, 0.0)
              for i in range(90)]
    jalur, _ = P.susun_jalur(sampel, [1] * 90, set(), L, T, "9:16", gaya="campuran", potongan=True)
    assert jalur.titik_dasar
    k = tmp_path / "k.mp4"
    R.render_klip(v, 0, 8.5, k, rasio="9:16", jalur=jalur, lebar_keluaran=180)
    cap = cv2.VideoCapture(str(k))
    lebar_wajah = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        m = (abs(f[..., 0].astype(int) - 170) < 30) & (abs(f[..., 1].astype(int) - 190) < 30) & (abs(f[..., 2].astype(int) - 225) < 30)
        xs = np.where(m.any(0))[0]
        lebar_wajah.append(int(xs.max() - xs.min()) if len(xs) else 0)
    selisih = [abs(b - a) for a, b in zip(lebar_wajah, lebar_wajah[1:])]
    lompatan = [x for x in selisih if x > 8]
    assert len(lompatan) >= 1                                              # ada potongan yang terlihat
    assert all(x <= 3 or x > 8 for x in selisih)                           # tidak ada perubahan ukuran yang bertahap


@butuh_ffmpeg
def test_buang_jeda_memperpendek_gambar_dan_suara_dengan_sinkron(tmp_path):
    v = buat_video(tmp_path / "v.mp4")
    out = tmp_path / "k.mp4"
    r = R.render_klip(v, 0.0, 4.0, out, rasio="9:16", lebar_keluaran=360, buang=[(1.0, 2.0)])
    assert abs(r["durasi"] - 3.0) < 0.1 and r["frame"] == 90
    import av
    with av.open(str(out)) as c:
        durasi_suara = sum(float(p.duration * p.time_base) for p in c.demux(c.streams.audio[0]) if p.duration)
    assert abs(durasi_suara - 3.0) < 0.15
    assert abs(kecerahan_frame(out, 29) - kecerahan_frame(v, 29)) < 6      # sebelum lubang: frame sumber 29
    assert abs(kecerahan_frame(out, 30) - kecerahan_frame(v, 60)) < 6      # setelah lubang: loncat ke frame sumber 60 (t = 2,0 dtk)


@butuh_ffmpeg
def test_buang_jeda_semua_klip_ditolak(tmp_path):
    v = buat_video(tmp_path / "v.mp4")
    with pytest.raises(ValueError, match="terbuang"):
        R.render_klip(v, 1.0, 3.0, tmp_path / "k.mp4", lebar_keluaran=360, buang=[(0.0, 4.0)])


@butuh_ffmpeg
def test_buang_jeda_subtitle_ikut_bergeser(tmp_path, monkeypatch):
    v = buat_video(tmp_path / "v.mp4")
    ditangkap = {}
    asli = R.buat_ass
    monkeypatch.setattr(R, "buat_ass", lambda kata, mulai, akhir, *a, **k: ditangkap.update(kata=kata, akhir=akhir) or asli(kata, mulai, akhir, *a, **k))
    kata = [{"w": "satu", "s": 0.2, "e": 0.8}, {"w": "dua", "s": 2.5, "e": 3.0}]
    R.render_klip(v, 0.0, 4.0, tmp_path / "k.mp4", lebar_keluaran=360, kata=kata, buang=[(1.0, 2.0)])
    assert [round(k["s"], 2) for k in ditangkap["kata"]] == [0.2, 1.5] and abs(ditangkap["akhir"] - 3.0) < 0.05


@butuh_ffmpeg
@pytest.mark.parametrize("dengan_suara", [True, False])
def test_terminal_buang_jeda_dengan_subtitle_dan_tanpa_suara(tmp_path, dengan_suara):
    """Jalur yang dipakai worker: python -m core.render ... --kata kata.json --buang [[a,b]] (kata dibaca sebagai objek Word)."""
    v = buat_video(tmp_path / "v.mp4", detik=10, dengan_suara=dengan_suara)
    (tmp_path / "k.json").write_text(json.dumps([{"mulai": 3.3, "akhir": 9.2}]))
    (tmp_path / "kata.json").write_text(json.dumps([{"w": "x", "s": 3.4, "e": 3.8}, {"w": "y", "s": 6.0, "e": 6.5}]))
    r = subprocess.run([sys.executable, "-m", "core.render", str(v), str(tmp_path / "k.json"), "--folder", str(tmp_path / "o"),
                        "--kata", str(tmp_path / "kata.json"), "--mode", "tengah", "--buang", "[[4.1, 5.7]]", "--lebar", "360"],
                       capture_output=True, text=True, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stdout + r.stderr
    hasil = next((tmp_path / "o").glob("klip_*.mp4"))
    assert abs(info(hasil)["durasi"] - (5.9 - 1.6)) < 0.3


def test_terminal_potongan_kamera_mati_bawaan_dan_hidup_bila_diminta(monkeypatch, tmp_path):
    """Bawaan: kamera mengikuti wajah dengan gerak halus (tanpa potongan langsung). Potongan hanya bila --potongan-kamera."""
    from core import pembicara as PB
    diterima = []
    def palsu(*a, **k):
        diterima.append(k.get("potongan"))
        raise ValueError("berhenti di sini")
    monkeypatch.setattr(PB, "lacak_pembicara", palsu)
    (tmp_path / "v.mp4").write_bytes(b"x")
    (tmp_path / "k.json").write_text(json.dumps([{"mulai": 0.0, "akhir": 5.0}]))
    for tambahan in ([], ["--potongan-kamera"]):
        assert R.main([str(tmp_path / "v.mp4"), str(tmp_path / "k.json"), "--folder", str(tmp_path / "o"), "--tanpa-zoom", *tambahan]) == 1
    assert diterima == [False, True]
