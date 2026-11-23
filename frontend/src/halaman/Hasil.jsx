import { useCallback, useEffect, useState } from "react";
import { batalProyek, daftarKlip, detailProyek, hapusProyek } from "../api.js";
import DialogKonfirmasi from "../komponen/DialogKonfirmasi.jsx";
import KartuKlip from "../komponen/KartuKlip.jsx";
import { dibatalkan, labelProyek, masihBerjalan, urutkanKlip } from "../format.js";
import { alamat } from "../rute.js";
import TidakAda from "./TidakAda.jsx";

/** Hasil satu proyek: progres selama diproses, lalu daftar klip (urut menurut menit video). */
export default function Hasil({ id, padaKeluar, padaHapus }) {
  const [konfirmasi, setKonfirmasi] = useState(false);
  const [menghapus, setMenghapus] = useState(false);
  const [galatHapus, setGalatHapus] = useState("");
  const [proyek, setProyek] = useState(undefined); // undefined = memuat, null = tidak ada
  const [klip, setKlip] = useState(null);
  const [galat, setGalat] = useState("");
  const [urutan, setUrutan] = useState("menit");

  const muat = useCallback(async () => {
    try {
      const p = await detailProyek(id);
      setProyek(p);
      setGalat("");
      if (p.status === "done") setKlip(await daftarKlip(id));
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else if (e.status === 404) setProyek(null);
      else setGalat(e.message);
    }
  }, [id, padaKeluar]);

  useEffect(() => {
    setProyek(undefined);
    setKlip(null);
    muat();
  }, [muat]);

  const berjalan = proyek ? masihBerjalan(proyek) : false;
  const [membatalkan, setMembatalkan] = useState(false);

  async function batal() {
    setMembatalkan(true);
    try {
      setProyek(await batalProyek(id));
      setGalat("");
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setGalat(e.message);
    } finally {
      setMembatalkan(false);
    }
  }
  async function hapus() {
    setMenghapus(true);
    setGalatHapus("");
    try {
      await hapusProyek(id);
      padaHapus?.();
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setGalatHapus(e.message);
      setMenghapus(false);
    }
  }

  useEffect(() => {
    if (!berjalan) return undefined;
    const t = setInterval(muat, 3000);
    return () => clearInterval(t);
  }, [berjalan, muat]);

  const adaRender = klip ? klip.some((k) => k.status === "rendering") : false;
  useEffect(() => {
    if (!adaRender) return undefined;
    const t = setInterval(async () => {
      try {
        setKlip(await daftarKlip(id));
      } catch (e) {
        if (e.status === 401) padaKeluar();
      }
    }, 3000);
    return () => clearInterval(t);
  }, [adaRender, id, padaKeluar]);

  if (proyek === null) return <TidakAda judul="Proyek tidak ditemukan" isi="Proyek ini tidak ada atau bukan milikmu." />;
  if (proyek === undefined)
    return galat ? (
      <p role="alert" className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">{galat}</p>
    ) : (
      <p className="text-sm text-zinc-500">Memuat...</p>
    );

  return (
    <section className="space-y-4">
      <a href={alamat.proyek()} className="text-sm text-violet-300 hover:text-violet-200">&larr; Semua proyek</a>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-white tracking-tight">
            {proyek.title || (proyek.source_type === "link" ? "Video YouTube" : "Tanpa judul")}
          </h1>
          <p className="text-xs text-zinc-500 break-all">{proyek.source_ref}</p>
        </div>
        {!berjalan && (
          <button type="button" onClick={() => setKonfirmasi(true)} className="shrink-0 rounded-xl border border-zinc-700 text-zinc-300 hover:text-red-300 hover:border-red-500/50 text-sm px-4 py-2 transition-colors">
            Hapus proyek
          </button>
        )}
      </div>
      {konfirmasi && (
        <DialogKonfirmasi judul="Hapus proyek ini?" sibuk={menghapus} galat={galatHapus} padaYa={hapus} padaBatal={() => setKonfirmasi(false)}
          isi={<><p>Proyek ini akan dihapus bersama <b>semua klipnya</b> dan berkas videonya di server (video asli dan hasil).</p><p>Tindakan ini tidak bisa dibatalkan.</p></>} />
      )}

      {galat && (
        <p role="alert" className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">{galat}</p>
      )}

      {berjalan && (
        <div className="bg-zinc-900 rounded-2xl border border-zinc-800 p-4">
          <div className="flex justify-between text-sm mb-2">
            <span className="font-medium">{labelProyek(proyek)}: {proyek.stage}</span>
            <span className="text-zinc-400">{proyek.progress}%</span>
          </div>
          <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-violet-500 to-fuchsia-500 transition-all" style={{ width: `${proyek.progress}%` }} />
          </div>
          <p className="text-xs text-zinc-500 mt-2">Halaman ini diperbarui otomatis. Kamu boleh menutupnya dan kembali nanti.</p>
          <button type="button" onClick={batal} disabled={membatalkan}
            className="mt-3 rounded-xl border border-zinc-700 text-zinc-200 text-sm px-3 py-1.5 hover:bg-zinc-800 disabled:opacity-50">
            {membatalkan ? "Membatalkan..." : "Batalkan proses"}
          </button>
        </div>
      )}

      {dibatalkan(proyek) && (
        <p className="text-sm text-zinc-300 bg-zinc-900 border border-zinc-800 rounded-xl px-3 py-2">
          Proses dibatalkan. Proyek ini tidak dilanjutkan; buat proyek baru dari Beranda bila ingin mencoba lagi.
        </p>
      )}

      {proyek.status === "failed" && !dibatalkan(proyek) && (
        <p className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">
          Proses gagal{proyek.error ? `: ${proyek.error}` : "."}
        </p>
      )}

      {proyek.status === "done" &&
        (klip === null ? (
          <p className="text-sm text-zinc-500">Memuat klip...</p>
        ) : klip.length === 0 ? (
          <p className="text-sm text-zinc-500">Proses selesai tetapi tidak ada klip yang dihasilkan.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-zinc-400">
                {klip.length} klip · skor tertinggi {Math.round(Math.max(...klip.map((k) => k.score)))}
              </p>
              <div className="inline-flex rounded-lg border border-zinc-700 overflow-hidden text-sm" role="group" aria-label="Urutan klip">
                {[["menit", "Menit video"], ["skor", "Skor tertinggi"]].map(([nilai, teks]) => (
                  <button
                    key={nilai}
                    onClick={() => setUrutan(nilai)}
                    aria-pressed={urutan === nilai}
                    className={`px-3 py-1.5 ${urutan === nilai ? "bg-violet-600 text-white" : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800"}`}
                  >
                    {teks}
                  </button>
                ))}
              </div>
            </div>
            <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {urutkanKlip(klip, urutan).map((k) => (
                <KartuKlip
                  key={k.id}
                  klip={k}
                  nomor={klip.findIndex((x) => x.id === k.id) + 1}
                  padaUbah={(baru) => setKlip((lama) => lama.map((x) => (x.id === baru.id ? baru : x)))}
                  padaHapus={(idKlip) => setKlip((lama) => lama.filter((x) => x.id !== idKlip))}
                  padaKeluar={padaKeluar}
                />
              ))}
            </ul>
          </>
        ))}
    </section>
  );
}
