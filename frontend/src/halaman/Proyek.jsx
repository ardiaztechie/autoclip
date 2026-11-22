import DaftarProyek from "../komponen/DaftarProyek.jsx";
import { alamat } from "../rute.js";

export default function Proyek({ daftar, galat }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-xl font-bold text-slate-900">Proyek saya</h1>
        <a href={alamat.beranda()} className="rounded-lg bg-indigo-600 text-white text-sm font-medium px-4 py-2 hover:bg-indigo-700">
          Proyek baru
        </a>
      </div>
      <DaftarProyek daftar={daftar} galat={galat} kosong="Belum ada proyek. Buat yang pertama dari Beranda." />
    </section>
  );
}
