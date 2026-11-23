import KartuProyek from "./KartuProyek.jsx";

/** Daftar kartu proyek dengan keadaan memuat/kosong/galat yang sama di semua halaman. */
export default function DaftarProyek({ daftar, galat, batas, kosong, padaHapus }) {
  const tampil = batas && daftar ? daftar.slice(0, batas) : daftar;
  return (
    <div>
      {galat && (
        <p role="alert" className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2 mb-3">
          {galat}
        </p>
      )}
      {tampil === null ? (
        <p className="text-sm text-zinc-500">Memuat...</p>
      ) : tampil.length === 0 ? (
        <p className="text-sm text-zinc-500 rounded-2xl border border-dashed border-zinc-800 px-4 py-8 text-center">{kosong}</p>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {tampil.map((p) => (
            <KartuProyek key={p.id} p={p} padaHapus={padaHapus} />
          ))}
        </ul>
      )}
    </div>
  );
}
