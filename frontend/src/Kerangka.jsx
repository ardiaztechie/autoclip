import { keluar } from "./api.js";
import { alamat } from "./rute.js";
import TombolTema from "./komponen/TombolTema.jsx";

const MENU = [
  { nama: "beranda", teks: "Beranda", href: alamat.beranda(), ikon: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10" },
  { nama: "proyek", teks: "Proyek", href: alamat.proyek(), ikon: "M4 6h16M4 12h16M4 18h10" },
];

function Logo() {
  return (
    <a href={alamat.beranda()} className="flex items-center gap-2.5 font-semibold text-white tracking-tight">
      <span className="grid place-items-center w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500">
        <svg viewBox="0 0 24 24" className="w-4.5 h-4.5" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 5l12 7-12 7z" />
        </svg>
      </span>
      AutoClip
    </a>
  );
}

function Menu({ rute, mendatar, admin }) {
  const menu = admin ? [...MENU, { nama: "cms", teks: "Landing (CMS)", href: alamat.cms(), ikon: "M4 5h16v14H4zM4 10h16M9 10v9" }] : MENU;
  const aktif = (nama) => rute.nama === nama || (nama === "proyek" && rute.nama === "detail");
  return (
    <nav className={mendatar ? "flex gap-1 md:hidden px-3 pb-2" : "space-y-1"} aria-label="Menu utama">
      {menu.map((m) => (
        <a
          key={m.nama}
          href={m.href}
          aria-current={aktif(m.nama) ? "page" : undefined}
          className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${
            aktif(m.nama)
              ? "bg-violet-500/15 text-violet-300 font-medium ring-1 ring-inset ring-violet-500/30"
              : "text-zinc-400 hover:bg-zinc-800/70 hover:text-zinc-100"
          }`}
        >
          <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d={m.ikon} />
          </svg>
          {m.teks}
        </a>
      ))}
    </nav>
  );
}

/** Tata letak yang sama untuk semua halaman setelah masuk: sidebar + header + isi. */
export default function Kerangka({ pengguna, rute, padaKeluar, children }) {
  async function logout() {
    try {
      await keluar();
    } finally {
      padaKeluar();
    }
  }

  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden md:flex md:w-60 shrink-0 flex-col bg-zinc-900/60 border-r border-zinc-800 p-4 gap-6 sticky top-0 h-screen">
        <div className="px-2 pt-1"><Logo /></div>
        <a
          href={alamat.beranda()}
          className="flex items-center justify-center gap-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium py-2.5 transition-colors"
        >
          <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
          Proyek baru
        </a>
        <Menu rute={rute} admin={pengguna.role === "admin"} />
      </aside>

      <div className="flex-1 min-w-0">
        <header className="sticky top-0 z-10 bg-zinc-950/80 backdrop-blur border-b border-zinc-800">
          <div className="px-4 md:px-8 py-3 flex items-center justify-between">
            <div className="md:invisible"><Logo /></div>
            <div className="flex items-center gap-3 text-sm">
              <span className="flex items-center gap-2 text-zinc-300">
                <span className="grid place-items-center w-7 h-7 rounded-full bg-zinc-800 text-xs font-semibold text-violet-300">
                  {(pengguna.name || "?").slice(0, 1).toUpperCase()}
                </span>
                <span className="hidden sm:inline">{pengguna.name}</span>
                {pengguna.role === "admin" && (
                  <span className="text-xs rounded-full bg-violet-500/15 text-violet-300 px-2 py-0.5">admin</span>
                )}
              </span>
              <TombolTema />
              <button onClick={logout} className="rounded-lg border border-zinc-700 px-3 py-1.5 text-zinc-300 hover:bg-zinc-800 transition-colors">
                Keluar
              </button>
            </div>
          </div>
          <Menu rute={rute} mendatar admin={pengguna.role === "admin"} />
        </header>
        <main className="max-w-6xl mx-auto px-4 md:px-8 py-8 space-y-8">{children}</main>
      </div>
    </div>
  );
}
