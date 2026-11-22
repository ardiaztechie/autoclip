import { keluar } from "./api.js";
import { alamat } from "./rute.js";

const MENU = [
  { nama: "beranda", teks: "Beranda", href: alamat.beranda(), ikon: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10" },
  { nama: "proyek", teks: "Proyek", href: alamat.proyek(), ikon: "M4 6h16M4 12h16M4 18h10" },
];

function Menu({ rute, mendatar }) {
  const aktif = (nama) => rute.nama === nama || (nama === "proyek" && rute.nama === "detail");
  return (
    <nav className={mendatar ? "flex gap-1 md:hidden px-3 pb-2" : "space-y-1"} aria-label="Menu utama">
      {MENU.map((m) => (
        <a
          key={m.nama}
          href={m.href}
          aria-current={aktif(m.nama) ? "page" : undefined}
          className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
            aktif(m.nama) ? "bg-indigo-50 text-indigo-700 font-medium" : "text-slate-600 hover:bg-slate-100"
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
      <aside className="hidden md:flex md:w-56 shrink-0 flex-col bg-white border-r border-slate-200 p-4 gap-6">
        <a href={alamat.beranda()} className="text-lg font-bold text-slate-900 px-3">AutoClip</a>
        <Menu rute={rute} />
      </aside>

      <div className="flex-1 min-w-0">
        <header className="bg-white border-b border-slate-200">
          <div className="px-4 py-3 flex items-center justify-between">
            <a href={alamat.beranda()} className="text-lg font-bold text-slate-900 md:invisible">AutoClip</a>
            <div className="flex items-center gap-3 text-sm">
              <span className="text-slate-600">
                {pengguna.name}
                {pengguna.role === "admin" && (
                  <span className="ml-2 text-xs rounded-full bg-indigo-100 text-indigo-700 px-2 py-0.5">admin</span>
                )}
              </span>
              <button onClick={logout} className="rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50">
                Keluar
              </button>
            </div>
          </div>
          <Menu rute={rute} mendatar />
        </header>
        <main className="max-w-3xl mx-auto px-4 py-6 space-y-8">{children}</main>
      </div>
    </div>
  );
}
