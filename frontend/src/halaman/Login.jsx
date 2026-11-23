import { useState } from "react";
import { masuk } from "../api.js";
import TombolTema from "../komponen/TombolTema.jsx";
import { alamat } from "../rute.js";

const KOLOM = "mt-1.5 w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3.5 py-2.5 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500/60 focus:border-violet-500";

export default function Login({ galatAwal = "", padaMasuk }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [galat, setGalat] = useState(galatAwal);
  const [sibuk, setSibuk] = useState(false);

  async function kirim(e) {
    e.preventDefault();
    setGalat("");
    setSibuk(true);
    try {
      padaMasuk(await masuk(email, password));
    } catch (err) {
      setGalat(err.message);
      setSibuk(false);
    }
  }

  return (
    <main className="relative min-h-screen flex items-center justify-center p-4 bg-[radial-gradient(ellipse_at_top,rgba(139,92,246,0.18),transparent_60%)]">
      <div className="absolute top-4 right-4"><TombolTema /></div>
      <form onSubmit={kirim} className="w-full max-w-sm bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl p-8 space-y-5">
        <div>
          <span className="grid place-items-center w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 mb-4">
            <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 5l12 7-12 7z" /></svg>
          </span>
          <h1 className="text-2xl font-bold text-white tracking-tight">AutoClip</h1>
          <p className="text-sm text-zinc-400 mt-1">Ubah video panjang menjadi klip pendek.</p>
        </div>

        <label className="block">
          <span className="text-sm font-medium text-zinc-300">Email</span>
          <input type="email" required autoFocus autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className={KOLOM} />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-zinc-300">Password</span>
          <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className={KOLOM} />
        </label>

        {galat && (
          <p role="alert" className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">{galat}</p>
        )}

        <button type="submit" disabled={sibuk} className="w-full rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-medium py-2.5 transition-colors disabled:opacity-60">
          {sibuk ? "Memeriksa..." : "Masuk"}
        </button>
      </form>
      <a href={alamat.landing()} className="absolute top-4 left-4 text-sm text-zinc-400 hover:text-zinc-200">&larr; Beranda situs</a>
    </main>
  );
}
