"""Pengujian core/render.py dengan video sintetis (butuh FFmpeg; dilewati bila tidak ada).

Jalankan: python -m pytest tests/test_render.py -v
"""
import json
import shutil
import subprocess

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
    assert "[2/2]" in capsys.readouterr().out


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
