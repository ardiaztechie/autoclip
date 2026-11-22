import KartuProyek from "./KartuProyek.jsx";

/** Daftar kartu proyek dengan keadaan memuat/kosong/galat yang sama di semua halaman. */
export default function DaftarProyek({ daftar, galat, batas, kosong }) {
  const tampil = batas && daftar ? daftar.slice(0, batas) : daftar;
  return (
    <div>
      {galat && (
        <p role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-3">
          {galat}
        </p>
      )}
      {tampil === null ? (
        <p className="text-sm text-slate-500">Memuat...</p>
      ) : tampil.length === 0 ? (
        <p className="text-sm text-slate-500">{kosong}</p>
      ) : (
        <ul className="space-y-3">
          {tampil.map((p) => (
            <KartuProyek key={p.id} p={p} />
          ))}
        </ul>
      )}
    </div>
  );
}
