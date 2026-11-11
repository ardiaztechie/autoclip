"""ukur_durasi.py: pengukur HANYA-BACA untuk pembentukan calon clip.

Skrip ini TIDAK mengubah apa pun: tidak menulis ke berkas masukan, tidak
mengubah core/, scoring, maupun selection. Ia hanya membaca kata.json,
memanggil split_sentences dan build_candidates apa adanya, lalu menghitung
statistik. Laporan opsional ditulis ke berkas BARU lewat --simpan.

Yang diukur:
  1. panjang kalimat (detik dan jumlah kata)
  2. jeda antar kata dan jeda antar kalimat
  3. durasi calon clip yang benar-benar dibuat build_candidates
  4. alasan berhenti tiap titik awal (per_start / maks_sec / habis kalimat / tanpa calon)
  5. titik akhir sah yang TIDAK dibuat karena per_start (ruang yang terlewat)
  6. seberapa jauh titik akhir pertama yang ditolak max_sec melewati batas
     (menjawab: apakah toleransi di atas max_sec akan menambah pilihan?)
  7. (opsional) durasi klip terpilih dari klip.json

Cara pakai (dari folder proyek, .venv aktif):
    python tools/ukur_durasi.py storage/uji2/kata.json
    python tools/ukur_durasi.py storage/uji2/kata.json --klip storage/uji2/klip.json
    python tools/ukur_durasi.py storage/uji2/kata.json --min-detik 20 --maks-detik 60 --simpan storage/uji2/ukur.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# agar bisa dijalankan sebagai skrip biasa dari folder proyek
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import TANDA_AKHIR  # noqa: E402
from core.segments import JEDA_MAKS_CALON_BAWAAN, build_candidates, split_sentences  # noqa: E402
from core.transcribe import dari_json  # noqa: E402


# --------------------------------------------------------------------------
# statistik sederhana (tanpa numpy)
# --------------------------------------------------------------------------
def persentil(nilai: list[float], p: float) -> float | None:
    """Persentil dengan interpolasi linear. p dalam 0..100."""
    if not nilai:
        return None
    s = sorted(nilai)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * p / 100.0
    bawah = int(pos)
    atas = min(bawah + 1, len(s) - 1)
    return s[bawah] + (s[atas] - s[bawah]) * (pos - bawah)


def ringkas(nilai: list[float]) -> dict:
    if not nilai:
        return {"n": 0}
    return {
        "n": len(nilai),
        "min": min(nilai),
        "p10": persentil(nilai, 10),
        "median": persentil(nilai, 50),
        "rata2": sum(nilai) / len(nilai),
        "p90": persentil(nilai, 90),
        "maks": max(nilai),
    }


def _f(x) -> str:
    return "-" if x is None else f"{x:.2f}"


def _baris(nama: str, r: dict, satuan: str = "") -> str:
    if r["n"] == 0:
        return f"  {nama}: tidak ada data"
    return (f"  {nama}: n={r['n']}  min={_f(r['min'])}  p10={_f(r['p10'])}  "
            f"median={_f(r['median'])}  rata2={_f(r['rata2'])}  p90={_f(r['p90'])}  "
            f"maks={_f(r['maks'])} {satuan}").rstrip()


def histogram(nilai: list[float], batas: list[float]) -> list[tuple[str, int]]:
    """Hitung jumlah nilai per rentang [batas[i], batas[i+1]); rentang terakhir terbuka."""
    hasil = []
    for i, b in enumerate(batas):
        if i + 1 < len(batas):
            n = sum(1 for x in nilai if b <= x < batas[i + 1])
            hasil.append((f"{b:g}-{batas[i + 1]:g}", n))
        else:
            hasil.append((f">={b:g}", sum(1 for x in nilai if x >= b)))
    return hasil


def _cetak_hist(judul: str, h: list[tuple[str, int]], total: int) -> list[str]:
    out = [f"  {judul}"]
    for nama, n in h:
        persen = 100 * n / total if total else 0
        out.append(f"    {nama:>9} dtk : {n:5d}  ({persen:5.1f}%)  {'#' * int(persen / 2)}")
    return out


# --------------------------------------------------------------------------
# analisis per titik awal (meniru loop build_candidates TANPA mengubahnya)
# --------------------------------------------------------------------------
def analisis_awal(kalimat, min_sec: float, max_sec: float, per_start: int,
                  jeda_maks_calon: float | None = None) -> dict:
    """Untuk tiap kalimat awal, catat titik akhir sah dan alasan berhenti.

    Aturan sama persis dengan build_candidates: titik akhir sah bila
    min_sec <= durasi <= max_sec; loop berhenti bila durasi > max_sec.
    """
    alasan = Counter()
    n_diambil_total = 0
    n_sah_total = 0
    hilang_per_start = 0           # titik akhir sah yang tak dibuat karena per_start
    durasi_terpanjang_diambil: list[float] = []
    durasi_terpanjang_sah: list[float] = []
    selisih_terlewat: list[float] = []   # terpanjang sah - terpanjang diambil
    lewat_batas: list[float] = []        # (durasi titik akhir pertama yang >max) - max
    jeda_setelah_diambil: list[float] = []
    jeda_setelah_hilang: list[float] = []
    akhir_diambil_bertanda = 0
    akhir_hilang_bertanda = 0
    n = len(kalimat)

    for awal in range(n):
        sah: list[tuple[float, int]] = []    # (durasi, indeks akhir)
        berhenti_karena_maks = False
        durasi_lewat = None
        for akhir in range(awal, n):
            if (jeda_maks_calon is not None and akhir > awal
                    and kalimat[akhir].start - kalimat[akhir - 1].end > jeda_maks_calon):
                break
            durasi = kalimat[akhir].end - kalimat[awal].start
            if durasi > max_sec:
                berhenti_karena_maks = True
                durasi_lewat = durasi
                break
            if durasi >= min_sec:
                sah.append((durasi, akhir))
        # alasan berhenti pada build_candidates yang asli
        if not sah:
            alasan["tanpa_calon"] += 1
        elif len(sah) >= per_start:
            alasan["per_start"] += 1
        elif berhenti_karena_maks:
            alasan["maks_sec"] += 1
        else:
            alasan["habis_kalimat"] += 1

        diambil = sah[:per_start]
        hilang = sah[per_start:]
        n_diambil_total += len(diambil)
        n_sah_total += len(sah)
        hilang_per_start += len(hilang)

        if sah:
            durasi_terpanjang_diambil.append(diambil[-1][0])
            durasi_terpanjang_sah.append(sah[-1][0])
            selisih_terlewat.append(sah[-1][0] - diambil[-1][0])
        if berhenti_karena_maks and durasi_lewat is not None:
            lewat_batas.append(durasi_lewat - max_sec)

        def _jeda_setelah(idx: int) -> float:
            return (kalimat[idx + 1].start - kalimat[idx].end) if idx + 1 < n else 0.0

        def _bertanda(idx: int) -> bool:
            return kalimat[idx].words[-1].text.rstrip().endswith(TANDA_AKHIR)

        for _, idx in diambil:
            jeda_setelah_diambil.append(_jeda_setelah(idx))
            akhir_diambil_bertanda += _bertanda(idx)
        for _, idx in hilang:
            jeda_setelah_hilang.append(_jeda_setelah(idx))
            akhir_hilang_bertanda += _bertanda(idx)

    return {
        "n_awal": n,
        "alasan": dict(alasan),
        "n_diambil": n_diambil_total,
        "n_sah_tanpa_batas_per_start": n_sah_total,
        "n_hilang_per_start": hilang_per_start,
        "terpanjang_diambil": durasi_terpanjang_diambil,
        "terpanjang_sah": durasi_terpanjang_sah,
        "selisih_terlewat": selisih_terlewat,
        "lewat_batas": lewat_batas,
        "jeda_setelah_diambil": jeda_setelah_diambil,
        "jeda_setelah_hilang": jeda_setelah_hilang,
        "akhir_diambil_bertanda": akhir_diambil_bertanda,
        "akhir_hilang_bertanda": akhir_hilang_bertanda,
    }


# --------------------------------------------------------------------------
# laporan
# --------------------------------------------------------------------------
def ukur(kata, min_sec: float = 20, max_sec: float = 60, per_start: int = 3,
         jeda_maks: float = 0.8, jeda_maks_calon: float | None = None) -> dict:
    kalimat = split_sentences(kata, jeda_maks=jeda_maks)
    calon = build_candidates(kalimat, min_sec=min_sec, max_sec=max_sec, per_start=per_start,
                             jeda_maks_calon=jeda_maks_calon)

    # --- kalimat
    dur_kalimat = [k.end - k.start for k in kalimat]
    kata_per_kalimat = [float(len(k.words)) for k in kalimat]
    bertanda = sum(1 for k in kalimat if k.words[-1].text.rstrip().endswith(TANDA_AKHIR))

    # --- jeda
    jeda_kata = [kata[i + 1].start - kata[i].end for i in range(len(kata) - 1)]
    jeda_kata_pos = [j for j in jeda_kata if j > 0]
    jeda_kalimat = [kalimat[i + 1].start - kalimat[i].end for i in range(len(kalimat) - 1)]
    jeda_dalam_kalimat = []
    for k in kalimat:
        for i in range(len(k.words) - 1):
            jeda_dalam_kalimat.append(k.words[i + 1].start - k.words[i].end)

    # --- calon
    dur_calon = [c.duration for c in calon]
    analisis = analisis_awal(kalimat, min_sec, max_sec, per_start, jeda_maks_calon)

    # pemeriksaan diri: tiruan loop harus sama dengan fungsi asli
    cocok = analisis["n_diambil"] == len(calon)

    jeda_panjang = analisis_jeda_panjang(kata, kalimat, calon, min_sec, max_sec, jeda_maks)

    return {
        "parameter": {"min_sec": min_sec, "max_sec": max_sec, "per_start": per_start, "jeda_maks": jeda_maks,
                      "jeda_maks_calon": jeda_maks_calon},
        "video": {"n_kata": len(kata), "durasi_detik": (kata[-1].end - kata[0].start) if kata else 0.0},
        "kalimat": {
            "n": len(kalimat),
            "durasi": ringkas(dur_kalimat),
            "kata_per_kalimat": ringkas(kata_per_kalimat),
            "persen_bertanda_akhir": (100 * bertanda / len(kalimat)) if kalimat else 0.0,
            "_durasi_mentah": dur_kalimat,
        },
        "jeda": {
            "antar_kata_positif": ringkas(jeda_kata_pos),
            "antar_kalimat": ringkas(jeda_kalimat),
            "dalam_kalimat": ringkas(jeda_dalam_kalimat),
            "n_jeda_lebih_dari_jeda_maks": sum(1 for j in jeda_kata if j > jeda_maks),
            "_antar_kalimat_mentah": jeda_kalimat,
        },
        "calon": {
            "n": len(calon),
            "durasi": ringkas(dur_calon),
            "_durasi_mentah": dur_calon,
            "pemeriksaan_tiruan_cocok": cocok,
        },
        "awal": analisis,
        "jeda_panjang": jeda_panjang,
    }


def analisis_jeda_panjang(kata, kalimat, calon, min_sec: float, max_sec: float,
                          jeda_maks: float, top: int = 3, ambang: float = 1.0) -> list[dict]:
    """Temukan `top` jeda antar kata terpanjang (>= `ambang` dtk) dan hitung calon yang melintasinya.

    Calon 'melintasi' jeda bila jeda berada seluruhnya di dalam rentang calon
    (awal calon < awal jeda dan akhir calon > akhir jeda).
    Dihitung dua versi: calon yang benar-benar dibuat, dan calon sah bila per_start tak dibatasi.
    """
    gaps = [(kata[i + 1].start - kata[i].end, kata[i].end, kata[i + 1].start)
            for i in range(len(kata) - 1)]
    gaps = sorted((g for g in gaps if g[0] >= ambang), reverse=True)[:top]
    if not gaps:
        return []

    n = len(kalimat)
    hasil = []
    for dur, g_awal, g_akhir in gaps:
        dibuat = sum(1 for c in calon if c.start < g_awal and c.end > g_akhir)
        sah = 0
        for a in range(n):
            if kalimat[a].start >= g_akhir:
                break
            for b in range(a, n):
                d = kalimat[b].end - kalimat[a].start
                if d > max_sec:
                    break
                if d >= min_sec and kalimat[a].start < g_awal and kalimat[b].end > g_akhir:
                    sah += 1
        hasil.append({
            "durasi": dur, "posisi_mulai": g_awal, "posisi_akhir": g_akhir,
            "memecah_kalimat": dur > jeda_maks,
            "calon_dibuat_melintasi": dibuat,
            "calon_sah_melintasi_tanpa_batas_per_start": sah,
        })
    return hasil


def _mmss(d: float) -> str:
    return f"{int(d // 60):02d}:{int(d % 60):02d}"


# nama kunci yang dikenali pada klip.json (hasil core.pipeline memakai mulai/akhir)
_PASANGAN_KUNCI = (("mulai", "akhir"), ("start", "end"))


def durasi_klip(item: dict) -> float | None:
    """Durasi satu klip dari kunci mulai/akhir atau start/end; bila tak ada, dari kunci 'durasi'."""
    if not isinstance(item, dict):
        return None
    for a, b in _PASANGAN_KUNCI:
        if a in item and b in item:
            try:
                return float(item[b]) - float(item[a])
            except (TypeError, ValueError):
                return None
    try:
        return float(item["durasi"]) if "durasi" in item else None
    except (TypeError, ValueError):
        return None


def cetak(h: dict, klip: list | None = None) -> str:
    p = h["parameter"]
    out: list[str] = []
    out.append("=" * 72)
    out.append("LAPORAN PENGUKURAN (hanya-baca)")
    out.append("=" * 72)
    out.append(f"Parameter: min={p['min_sec']:g} dtk, maks={p['max_sec']:g} dtk, "
               f"per_start={p['per_start']}, jeda_maks kalimat={p['jeda_maks']:g} dtk, "
               f"jeda_maks_calon={'mati' if p.get('jeda_maks_calon') is None else format(p['jeda_maks_calon'], 'g') + ' dtk'}")
    v = h["video"]
    out.append(f"Transkrip: {v['n_kata']} kata, rentang {v['durasi_detik'] / 60:.1f} menit")

    out.append("\n[1] KALIMAT")
    k = h["kalimat"]
    out.append(f"  jumlah kalimat: {k['n']}   bertanda akhir (. ? ! …): {k['persen_bertanda_akhir']:.1f}%")
    out.append(_baris("durasi kalimat", k["durasi"], "dtk"))
    out.append(_baris("kata/kalimat  ", k["kata_per_kalimat"], "kata"))
    out += _cetak_hist("sebaran durasi kalimat:", histogram(k["_durasi_mentah"], [0, 3, 6, 10, 15, 20, 30]), k["n"])

    out.append("\n[2] JEDA")
    j = h["jeda"]
    out.append(_baris("antar kata (>0)  ", j["antar_kata_positif"], "dtk"))
    out.append(_baris("dalam kalimat    ", j["dalam_kalimat"], "dtk"))
    out.append(_baris("antar kalimat    ", j["antar_kalimat"], "dtk"))
    out.append(f"  jeda antar kata > {p['jeda_maks']:g} dtk (memecah kalimat): {j['n_jeda_lebih_dari_jeda_maks']}")
    if j["_antar_kalimat_mentah"]:
        out += _cetak_hist("sebaran jeda antar kalimat:",
                           histogram(j["_antar_kalimat_mentah"], [0, 0.2, 0.5, 1.0, 2.0]),
                           len(j["_antar_kalimat_mentah"]))

    out.append("\n[3] CALON CLIP (hasil build_candidates asli)")
    c = h["calon"]
    out.append(f"  jumlah calon: {c['n']}   tiruan loop cocok dengan fungsi asli: "
               f"{'YA' if c['pemeriksaan_tiruan_cocok'] else 'TIDAK (periksa skrip!)'}")
    out.append(_baris("durasi calon", c["durasi"], "dtk"))
    if c["n"]:
        batas = [p["min_sec"], 25, 30, 35, 40, 50, p["max_sec"]]
        batas = sorted(set(b for b in batas if b <= p["max_sec"]))
        out += _cetak_hist("sebaran durasi calon:", histogram(c["_durasi_mentah"], batas), c["n"])

    out.append("\n[4] MENGAPA PEMBENTUKAN BERHENTI (per titik awal)")
    a = h["awal"]
    n = a["n_awal"]
    nama = {
        "per_start": "berhenti karena sudah ada per_start calon",
        "maks_sec": "berhenti karena melewati maks_sec",
        "habis_kalimat": "kalimat habis (akhir video)",
        "tanpa_calon": "tanpa calon sama sekali",
    }
    for kunci in ("per_start", "maks_sec", "habis_kalimat", "tanpa_calon"):
        jml = a["alasan"].get(kunci, 0)
        out.append(f"  {nama[kunci]:<46}: {jml:5d}  ({100 * jml / n if n else 0:5.1f}%)")

    out.append("\n[5] PILIHAN YANG TERLEWAT KARENA per_start")
    out.append(f"  titik akhir sah yang dibuat       : {a['n_diambil']}")
    out.append(f"  titik akhir sah jika per_start tak dibatasi: {a['n_sah_tanpa_batas_per_start']}")
    out.append(f"  titik akhir sah yang tidak dibuat : {a['n_hilang_per_start']}")
    out.append(_baris("terpanjang yang dibuat per awal ", ringkas(a["terpanjang_diambil"]), "dtk"))
    out.append(_baris("terpanjang yang sah per awal    ", ringkas(a["terpanjang_sah"]), "dtk"))
    out.append(_baris("selisih (sah - dibuat)          ", ringkas(a["selisih_terlewat"]), "dtk"))
    if a["n_diambil"]:
        out.append(f"  akhir yang dibuat & bertanda akhir : {100 * a['akhir_diambil_bertanda'] / a['n_diambil']:.1f}%")
    if a["n_hilang_per_start"]:
        out.append(f"  akhir yang hilang & bertanda akhir : {100 * a['akhir_hilang_bertanda'] / a['n_hilang_per_start']:.1f}%")
    out.append(_baris("jeda setelah akhir yang dibuat  ", ringkas(a["jeda_setelah_diambil"]), "dtk"))
    out.append(_baris("jeda setelah akhir yang hilang  ", ringkas(a["jeda_setelah_hilang"]), "dtk"))

    out.append("\n[6] APAKAH TOLERANSI DI ATAS maks_sec AKAN MENAMBAH PILIHAN?")
    lb = a["lewat_batas"]
    if lb:
        out.append(f"  titik awal yang akan menabrak maks_sec bila per_start tak dibatasi: {len(lb)} dari {n}")
        out.append(_baris("titik akhir pertama yang ditolak melewati batas", ringkas(lb), "dtk"))
        for lim in (10, 20):
            jml = sum(1 for x in lb if x <= lim)
            out.append(f"    ditolak tetapi hanya lewat <= {lim} dtk: {jml}  ({100 * jml / len(lb):.1f}% dari yang menabrak)")
    else:
        out.append("  tidak ada titik awal yang menabrak maks_sec")

    out.append("\n[6b] JEDA TERPANJANG (>= 1 dtk) DAN CALON YANG MELINTASINYA")
    jp = h.get("jeda_panjang", [])
    if not jp:
        out.append("  tidak ada jeda >= 1 dtk")
    for g in jp:
        letak = "memecah kalimat" if g["memecah_kalimat"] else "di dalam kalimat"
        out.append(f"  jeda {g['durasi']:.2f} dtk pada {_mmss(g['posisi_mulai'])} ({letak}): "
                   f"calon dibuat yang melintasi = {g['calon_dibuat_melintasi']}, "
                   f"calon sah tanpa batas per_start yang melintasi = {g['calon_sah_melintasi_tanpa_batas_per_start']}")

    if klip is not None:
        durs = [d for d in (durasi_klip(x) for x in klip) if d is not None]
        out.append("\n[7] KLIP TERPILIH (dari klip.json)")
        if durs:
            out.append(_baris("durasi klip terpilih", ringkas(durs), "dtk"))
            if len(durs) < len(klip):
                out.append(f"  (peringatan: {len(klip) - len(durs)} dari {len(klip)} klip tak punya kunci durasi yang dikenali)")
        else:
            out.append("  tidak ada klip dengan kunci mulai/akhir, start/end, atau durasi")

    out.append("")
    return "\n".join(out)


def _bersihkan_untuk_json(h: dict) -> dict:
    """Buang kunci mentah berawalan '_' agar berkas laporan kecil."""
    if isinstance(h, dict):
        return {k: _bersihkan_untuk_json(v) for k, v in h.items() if not k.startswith("_")}
    return h


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pengukur hanya-baca pembentukan calon clip.")
    ap.add_argument("kata_json", help="berkas JSON hasil core.transcribe --simpan")
    ap.add_argument("--klip", default=None, help="klip.json hasil core.pipeline (opsional)")
    ap.add_argument("--min-detik", type=float, default=20)
    ap.add_argument("--maks-detik", type=float, default=60)
    ap.add_argument("--per-start", type=int, default=3)
    ap.add_argument("--jeda-maks-calon", type=float, default=JEDA_MAKS_CALON_BAWAAN,
                    help="sama seperti core.pipeline; 0 = mati (perilaku lama)")
    ap.add_argument("--simpan", default=None, help="tulis laporan JSON ke berkas BARU ini (tidak menimpa data asli)")
    arg = ap.parse_args(argv)

    try:
        kata = dari_json(Path(arg.kata_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Gagal membaca {arg.kata_json}: {e}")
        return 1
    if not kata:
        print("Transkrip kosong.")
        return 1

    klip = None
    if arg.klip:
        try:
            klip = json.loads(Path(arg.klip).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"Peringatan: klip.json tidak terbaca ({e}); bagian [7] dilewati.")

    h = ukur(kata, arg.min_detik, arg.maks_detik, arg.per_start,
             jeda_maks_calon=arg.jeda_maks_calon if arg.jeda_maks_calon > 0 else None)
    print(cetak(h, klip))

    if arg.simpan:
        tujuan = Path(arg.simpan)
        masukan = {Path(arg.kata_json).resolve(), Path(arg.klip).resolve() if arg.klip else None}
        if tujuan.resolve() in masukan:
            print("Menolak: --simpan tidak boleh sama dengan berkas masukan.")
            return 1
        tujuan.write_text(json.dumps(_bersihkan_untuk_json(h), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Laporan JSON disimpan: {tujuan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
