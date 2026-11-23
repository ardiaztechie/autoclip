import FormProyek from "../komponen/FormProyek.jsx";
import DaftarProyek from "../komponen/DaftarProyek.jsx";
import { alamat } from "../rute.js";

export default function Beranda({ pengguna, daftar, galat, muat, padaKeluar }) {
  return (
    <>
      <section className="max-w-3xl">
        <p className="text-sm text-violet-300">Halo, {pengguna.name}</p>
        <h1 className="text-3xl md:text-4xl font-bold text-white tracking-tight mt-1">
          Klip terbaikmu dimulai di sini
        </h1>
        <p className="text-zinc-400 mt-2">Tempel link YouTube atau unggah video, lalu sistem memilih momen terbaik dan memotongnya jadi klip pendek.</p>
      </section>

      <section className="max-w-3xl">
        <FormProyek padaSelesai={muat} padaKeluar={padaKeluar} />
      </section>

      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Proyek terbaru</h2>
          <a href={alamat.proyek()} className="text-sm text-violet-300 hover:text-violet-200">Lihat semua &rarr;</a>
        </div>
        <DaftarProyek daftar={daftar} galat={galat} batas={3} padaHapus={muat} kosong="Belum ada proyek. Mulai dari form di atas." />
      </section>
    </>
  );
}
