import FormProyek from "../komponen/FormProyek.jsx";
import DaftarProyek from "../komponen/DaftarProyek.jsx";
import { alamat } from "../rute.js";

export default function Beranda({ pengguna, daftar, galat, muat, padaKeluar }) {
  return (
    <>
      <section>
        <h1 className="text-2xl font-bold text-slate-900">Halo, {pengguna.name}</h1>
        <p className="text-slate-600 mt-1">Tempel link YouTube atau unggah video, lalu sistem membuat klip pendek untukmu.</p>
      </section>

      <section>
        <h2 className="text-base font-semibold mb-3">Proyek baru</h2>
        <FormProyek padaSelesai={muat} padaKeluar={padaKeluar} />
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">Proyek terbaru</h2>
          <a href={alamat.proyek()} className="text-sm text-indigo-600 hover:underline">Lihat semua</a>
        </div>
        <DaftarProyek daftar={daftar} galat={galat} batas={3} kosong="Belum ada proyek. Mulai dari form di atas." />
      </section>
    </>
  );
}
