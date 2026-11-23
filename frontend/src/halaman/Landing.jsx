import { useEffect, useState } from "react";
import { ambilLanding } from "../api.js";
import IsiLanding from "../komponen/IsiLanding.jsx";
import TombolTema from "../komponen/TombolTema.jsx";
import { alamat } from "../rute.js";

/** Landing page publik. Isinya dari CMS (GET /landing). Tombol utama: Masuk (belum login) atau Buka aplikasi (sudah login). */
export default function Landing({ pengguna }) {
  const [bagian, setBagian] = useState(null);
  const [galat, setGalat] = useState("");
  useEffect(() => {
    ambilLanding().then(setBagian).catch((e) => setGalat(e.message));
  }, []);
  const tujuan = pengguna ? alamat.beranda() : alamat.masuk();
  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,rgba(139,92,246,0.18),transparent_55%)]">
      <header className="max-w-6xl mx-auto px-4 md:px-8 py-4 flex items-center justify-between">
        <span className="flex items-center gap-2.5 font-semibold text-white tracking-tight">
          <span className="grid place-items-center w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500">
            <svg viewBox="0 0 24 24" className="w-4.5 h-4.5" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 5l12 7-12 7z" /></svg>
          </span>
          AutoClip
        </span>
        <div className="flex items-center gap-2">
          <TombolTema />
          <a href={tujuan} className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-800 transition-colors">
            {pengguna ? "Buka aplikasi" : "Masuk"}
          </a>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 md:px-8 pb-16 pt-6">
        {galat ? (
          <p role="alert" className="text-center text-sm text-red-300 mt-16">{galat}</p>
        ) : bagian === null ? (
          <p className="text-center text-sm text-zinc-500 mt-16">Memuat...</p>
        ) : (
          <IsiLanding bagian={bagian} hrefCta={tujuan} labelCta={pengguna ? "Buka aplikasi" : undefined} />
        )}
      </main>
    </div>
  );
}
