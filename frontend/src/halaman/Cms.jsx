import { useCallback, useEffect, useMemo, useState } from "react";
import { ambilLandingAdmin, simpanLanding } from "../api.js";
import IsiLanding from "../komponen/IsiLanding.jsx";
import { alamat } from "../rute.js";

const NAMA = { hero: "Bagian atas (hero)", fitur: "Fitur", cara_kerja: "Cara kerja", faq: "Pertanyaan umum (FAQ)", footer: "Footer" };
const KOLOM = "mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500/60";
const TOMBOL = "rounded-lg border border-zinc-700 text-zinc-200 text-xs px-3 py-1.5 hover:bg-zinc-800 transition-colors disabled:opacity-40";
const UTAMA = "rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 transition-colors disabled:opacity-40";
const salin = (x) => JSON.parse(JSON.stringify(x));

function Isian({ nama, nilai, ubah, maks, baris }) {
  const Tag = baris ? "textarea" : "input";
  return (
    <label className="block text-xs text-zinc-400">
      {nama} <span className="text-zinc-600">({nilai.length}/{maks})</span>
      <Tag value={nilai} maxLength={maks} rows={baris} onChange={(e) => ubah(e.target.value)} className={KOLOM} />
    </label>
  );
}

/** Formulir isi satu bagian; bentuknya mengikuti jenis bagian (sama dengan validasi di backend/landing.py). */
function Formulir({ kunci, isi, ubah }) {
  const setItem = (daftar, i, nilai) => ubah({ ...isi, [daftar]: isi[daftar].map((x, j) => (j === i ? nilai : x)) });
  const hapusItem = (daftar, i) => ubah({ ...isi, [daftar]: isi[daftar].filter((_, j) => j !== i) });
  const tambah = (daftar, baru) => ubah({ ...isi, [daftar]: [...isi[daftar], baru] });
  const Hapus = ({ padaKlik }) => <button type="button" onClick={padaKlik} className={`${TOMBOL} hover:text-red-300`}>Hapus</button>;

  if (kunci === "hero")
    return (
      <div className="space-y-3">
        <Isian nama="Judul" nilai={isi.title} maks={120} ubah={(v) => ubah({ ...isi, title: v })} />
        <Isian nama="Keterangan" nilai={isi.subtitle} maks={300} baris={3} ubah={(v) => ubah({ ...isi, subtitle: v })} />
        <Isian nama="Teks tombol" nilai={isi.cta_text} maks={30} ubah={(v) => ubah({ ...isi, cta_text: v })} />
      </div>
    );
  if (kunci === "footer") return <Isian nama="Teks" nilai={isi.text} maks={200} ubah={(v) => ubah({ ...isi, text: v })} />;
  if (kunci === "fitur")
    return (
      <div className="space-y-3">
        {isi.items.map((f, i) => (
          <div key={i} className="rounded-xl border border-zinc-800 p-3 space-y-2">
            <Isian nama={`Judul ${i + 1}`} nilai={f.title} maks={60} ubah={(v) => setItem("items", i, { ...f, title: v })} />
            <Isian nama="Isi" nilai={f.text} maks={200} baris={2} ubah={(v) => setItem("items", i, { ...f, text: v })} />
            <Hapus padaKlik={() => hapusItem("items", i)} />
          </div>
        ))}
        <button type="button" className={TOMBOL} disabled={isi.items.length >= 8} onClick={() => tambah("items", { title: "Fitur baru", text: "" })}>+ Tambah fitur</button>
      </div>
    );
  if (kunci === "cara_kerja")
    return (
      <div className="space-y-2">
        {isi.steps.map((s, i) => (
          <div key={i} className="flex items-end gap-2">
            <div className="flex-1"><Isian nama={`Langkah ${i + 1}`} nilai={s} maks={150} ubah={(v) => ubah({ ...isi, steps: isi.steps.map((x, j) => (j === i ? v : x)) })} /></div>
            <Hapus padaKlik={() => hapusItem("steps", i)} />
          </div>
        ))}
        <button type="button" className={TOMBOL} disabled={isi.steps.length >= 8} onClick={() => tambah("steps", "Langkah baru")}>+ Tambah langkah</button>
      </div>
    );
  return (
    <div className="space-y-3">
      {isi.items.map((f, i) => (
        <div key={i} className="rounded-xl border border-zinc-800 p-3 space-y-2">
          <Isian nama={`Pertanyaan ${i + 1}`} nilai={f.q} maks={150} ubah={(v) => setItem("items", i, { ...f, q: v })} />
          <Isian nama="Jawaban" nilai={f.a} maks={600} baris={3} ubah={(v) => setItem("items", i, { ...f, a: v })} />
          <Hapus padaKlik={() => hapusItem("items", i)} />
        </div>
      ))}
      <button type="button" className={TOMBOL} disabled={isi.items.length >= 12} onClick={() => tambah("items", { q: "Pertanyaan baru", a: "" })}>+ Tambah pertanyaan</button>
    </div>
  );
}

/** CMS sederhana (admin): ubah isi, tampil/sembunyi, dan urutan bagian landing page. */
export default function Cms({ pengguna, padaKeluar }) {
  const [bagian, setBagian] = useState(null);   // yang tersimpan di server
  const [draf, setDraf] = useState({});         // isi yang sedang diedit, per kunci
  const [galat, setGalat] = useState("");
  const [pesan, setPesan] = useState("");
  const [sibuk, setSibuk] = useState("");

  const muat = useCallback(async () => {
    try {
      const b = await ambilLandingAdmin();
      setBagian(b);
      setDraf(Object.fromEntries(b.map((x) => [x.key, salin(x.content)])));
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setGalat(e.message);
    }
  }, [padaKeluar]);
  useEffect(() => {
    muat();
  }, [muat]);

  async function kirim(kunci, perubahan, sukses) {
    const b = bagian.find((x) => x.key === kunci);
    setSibuk(kunci);
    setGalat("");
    setPesan("");
    try {
      const hasil = await simpanLanding(kunci, { content: b.content, is_visible: b.is_visible, sort_order: b.sort_order, ...perubahan });
      setBagian((lama) => lama.map((x) => (x.key === kunci ? { ...x, content: hasil.content, is_visible: hasil.is_visible, sort_order: hasil.sort_order } : x)));
      if (perubahan.content) setDraf((d) => ({ ...d, [kunci]: salin(hasil.content) }));
      setPesan(sukses);
      return true;
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setGalat(e.message);
      return false;
    } finally {
      setSibuk("");
    }
  }

  async function pindah(i, arah) {
    const j = i + arah;
    if (j < 0 || j >= bagian.length) return;
    const urut = [...bagian];
    [urut[i], urut[j]] = [urut[j], urut[i]];
    setSibuk("urutan");
    setGalat("");
    try {
      const hasil = [];
      for (let n = 0; n < urut.length; n += 1) {
        const b = urut[n];
        if (b.sort_order === n + 1) {
          hasil.push(b);
          continue;
        }
        const r = await simpanLanding(b.key, { content: b.content, is_visible: b.is_visible, sort_order: n + 1 });
        hasil.push({ ...b, sort_order: r.sort_order });
      }
      setBagian(hasil);
      setPesan("Urutan disimpan.");
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setGalat(e.message);
      muat();
    } finally {
      setSibuk("");
    }
  }

  const pratinjau = useMemo(() => (bagian ?? []).filter((b) => b.is_visible).map((b) => ({ key: b.key, content: draf[b.key] ?? b.content })), [bagian, draf]);

  if (pengguna.role !== "admin") return <p className="text-sm text-zinc-400">Halaman ini hanya untuk admin.</p>;
  if (bagian === null) return galat ? <p role="alert" className="text-sm text-red-300">{galat}</p> : <p className="text-sm text-zinc-500">Memuat...</p>;

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Landing page (CMS)</h1>
          <p className="text-sm text-zinc-400 mt-1">Ubah isi halaman depan yang dilihat pengunjung. Perubahan baru tampil setelah tombol Simpan ditekan.</p>
        </div>
        <a href={alamat.landing()} target="_blank" rel="noreferrer" className={`${TOMBOL} !text-sm !px-4 !py-2`}>Buka landing &nearr;</a>
      </div>
      {galat && <p role="alert" className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">{galat}</p>}
      {pesan && <p role="status" className="text-sm text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-xl px-3 py-2">{pesan}</p>}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          {bagian.map((b, i) => {
            const berubah = JSON.stringify(draf[b.key]) !== JSON.stringify(b.content);
            return (
              <article key={b.key} className={`rounded-2xl border bg-zinc-900 p-4 space-y-4 ${b.is_visible ? "border-zinc-800" : "border-zinc-800 opacity-70"}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold text-white flex-1 min-w-0">{NAMA[b.key]}</h2>
                  <button type="button" className={TOMBOL} disabled={!!sibuk || i === 0} onClick={() => pindah(i, -1)} aria-label={`Naikkan ${NAMA[b.key]}`}>↑</button>
                  <button type="button" className={TOMBOL} disabled={!!sibuk || i === bagian.length - 1} onClick={() => pindah(i, 1)} aria-label={`Turunkan ${NAMA[b.key]}`}>↓</button>
                  <label className="flex items-center gap-1.5 text-xs text-zinc-300">
                    <input type="checkbox" checked={b.is_visible} disabled={!!sibuk} onChange={(e) => kirim(b.key, { is_visible: e.target.checked }, e.target.checked ? "Bagian ditampilkan." : "Bagian disembunyikan.")} className="accent-violet-500" />
                    Tampil
                  </label>
                </div>
                <Formulir kunci={b.key} isi={draf[b.key]} ubah={(v) => setDraf((d) => ({ ...d, [b.key]: v }))} />
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={UTAMA} disabled={!!sibuk || !berubah} onClick={() => kirim(b.key, { content: draf[b.key] }, `${NAMA[b.key]} disimpan.`)}>
                    {sibuk === b.key ? "Menyimpan..." : "Simpan"}
                  </button>
                  <button type="button" className={TOMBOL} disabled={!!sibuk || !berubah} onClick={() => setDraf((d) => ({ ...d, [b.key]: salin(b.content) }))}>Batalkan perubahan</button>
                  <button type="button" className={TOMBOL} disabled={!!sibuk} onClick={() => setDraf((d) => ({ ...d, [b.key]: salin(b.bawaan) }))}>Isi bawaan</button>
                </div>
              </article>
            );
          })}
        </div>
        <div className="xl:sticky xl:top-20 self-start">
          <p className="text-xs text-zinc-500 mb-2">Pratinjau (ikut berubah saat kamu mengetik, sebelum disimpan)</p>
          <div className="rounded-2xl border border-zinc-800 p-5 max-h-[80vh] overflow-y-auto scale-100 origin-top">
            <div className="[&_h1]:!text-3xl [&_h2]:!text-xl"><IsiLanding bagian={pratinjau} hrefCta="#" /></div>
          </div>
        </div>
      </div>
    </section>
  );
}
