import { alamat } from "../rute.js";

export default function TidakAda({ judul = "Halaman tidak ditemukan", isi = "Alamat ini tidak ada." }) {
  return (
    <section className="text-center py-20">
      <h1 className="text-2xl font-bold text-white">{judul}</h1>
      <p className="text-zinc-400 mt-2">{isi}</p>
      <a href={alamat.beranda()} className="inline-block mt-5 text-violet-300 hover:text-violet-200">Kembali ke Beranda</a>
    </section>
  );
}
