import { useEffect } from "react";

/** Kotak konfirmasi untuk tindakan yang tidak bisa dibatalkan. Esc atau klik di luar = batal. */
export default function DialogKonfirmasi({ judul, isi, labelYa = "Hapus", sibuk = false, galat = "", padaYa, padaBatal }) {
  useEffect(() => {
    const tekan = (e) => e.key === "Escape" && !sibuk && padaBatal();
    window.addEventListener("keydown", tekan);
    return () => window.removeEventListener("keydown", tekan);
  }, [sibuk, padaBatal]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-black/60" onMouseDown={(e) => e.target === e.currentTarget && !sibuk && padaBatal()}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="judul-dialog" className="w-full max-w-md rounded-2xl bg-zinc-900 border border-zinc-700 p-6 shadow-2xl space-y-4">
        <h2 id="judul-dialog" className="text-lg font-semibold text-white">{judul}</h2>
        <div className="text-sm text-zinc-300 space-y-2">{isi}</div>
        {galat && <p role="alert" className="text-sm text-red-300 bg-red-500/10 rounded-xl px-3 py-2">{galat}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={padaBatal} disabled={sibuk} autoFocus className="rounded-xl border border-zinc-700 text-zinc-200 text-sm px-4 py-2 hover:bg-zinc-800 disabled:opacity-50">
            Batal
          </button>
          <button type="button" onClick={padaYa} disabled={sibuk} className="rounded-xl bg-red-600 hover:bg-red-500 text-white text-sm font-medium px-4 py-2 disabled:opacity-60">
            {sibuk ? "Menghapus..." : labelYa}
          </button>
        </div>
      </div>
    </div>
  );
}
