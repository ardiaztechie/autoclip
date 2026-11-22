import { useCallback, useEffect, useState } from "react";
import { daftarKlip, detailProyek } from "../api.js";
import KartuKlip from "../komponen/KartuKlip.jsx";
import { labelStatus, masihBerjalan } from "../format.js";
import { alamat } from "../rute.js";
import TidakAda from "./TidakAda.jsx";

/** Hasil satu proyek: progres selama diproses, lalu daftar klip (skor tertinggi dulu). */
export default function Hasil({ id, padaKeluar }) {
  const [proyek, setProyek] = useState(undefined); // undefined = memuat, null = tidak ada
  const [klip, setKlip] = useState(null);
  const [galat, setGalat] = useState("");

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
  useEffect(() => {
    if (!berjalan) return undefined;
    const t = setInterval(muat, 3000);
    return () => clearInterval(t);
  }, [berjalan, muat]);

  if (proyek === null) return <TidakAda judul="Proyek tidak ditemukan" isi="Proyek ini tidak ada atau bukan milikmu." />;
  if (proyek === undefined)
    return galat ? (
      <p role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{galat}</p>
    ) : (
      <p className="text-sm text-slate-500">Memuat...</p>
    );

  return (
    <section className="space-y-4">
      <a href={alamat.proyek()} className="text-sm text-indigo-600 hover:underline">&larr; Semua proyek</a>
      <div>
        <h1 className="text-xl font-bold text-slate-900">
          {proyek.title || (proyek.source_type === "link" ? "Video YouTube" : "Tanpa judul")}
        </h1>
        <p className="text-xs text-slate-500 break-all">{proyek.source_ref}</p>
      </div>

      {galat && (
        <p role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{galat}</p>
      )}

      {berjalan && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex justify-between text-sm mb-2">
            <span className="font-medium">{labelStatus(proyek.status)}: {proyek.stage}</span>
            <span className="text-slate-500">{proyek.progress}%</span>
          </div>
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full bg-indigo-500 transition-all" style={{ width: `${proyek.progress}%` }} />
          </div>
          <p className="text-xs text-slate-500 mt-2">Halaman ini diperbarui otomatis. Kamu boleh menutupnya dan kembali nanti.</p>
        </div>
      )}

      {proyek.status === "failed" && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          Proses gagal{proyek.error ? `: ${proyek.error}` : "."}
        </p>
      )}

      {proyek.status === "done" &&
        (klip === null ? (
          <p className="text-sm text-slate-500">Memuat klip...</p>
        ) : klip.length === 0 ? (
          <p className="text-sm text-slate-500">Proses selesai tetapi tidak ada klip yang dihasilkan.</p>
        ) : (
          <>
            <p className="text-sm text-slate-600">{klip.length} klip, diurutkan dari skor tertinggi.</p>
            <ul className="space-y-4">
              {klip.map((k, i) => (
                <KartuKlip key={k.id} klip={k} nomor={i + 1} />
              ))}
            </ul>
          </>
        ))}
    </section>
  );
}
