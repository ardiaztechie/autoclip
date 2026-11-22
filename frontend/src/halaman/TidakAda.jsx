import { alamat } from "../rute.js";

export default function TidakAda({ judul = "Halaman tidak ditemukan", isi = "Alamat ini tidak ada." }) {
  return (
    <section className="text-center py-16">
      <h1 className="text-xl font-bold text-slate-900">{judul}</h1>
      <p className="text-slate-600 mt-2">{isi}</p>
      <a href={alamat.beranda()} className="inline-block mt-4 text-indigo-600 hover:underline">Kembali ke Beranda</a>
    </section>
  );
}
