import DaftarProyek from "../komponen/DaftarProyek.jsx";
import { alamat } from "../rute.js";

export default function Proyek({ daftar, galat, muat }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-bold text-white tracking-tight">Proyek saya</h1>
        <a href={alamat.beranda()} className="rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 transition-colors">
          Proyek baru
        </a>
      </div>
      <DaftarProyek daftar={daftar} galat={galat} padaHapus={muat} kosong="Belum ada proyek. Buat yang pertama dari Beranda." />
    </section>
  );
}
