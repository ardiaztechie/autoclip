const TOMBOL = "inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 px-2.5 py-1 text-xs text-zinc-100 hover:bg-zinc-800 disabled:opacity-35 disabled:hover:bg-transparent transition-colors";
const GARIS = <span className="w-px h-5 bg-zinc-700 mx-1.5" aria-hidden="true" />;

/**
 * Alat potong, urutannya seperti CapCut: urungkan/ulangi, Bagi, Hapus. Dipasang di baris yang sama dengan tombol zoom timeline.
 * Cara pakai: klik timeline (garis putih = playhead) -> Bagi -> segmen yang dilingkari -> Hapus.
 */
export default function BilahPotong({ bisaUrung, bisaUlang, urung, ulang, bagi, bisaBagi, hapus, segmenPilih, jedaOtomatis, adaKata, nonaktif }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="toolbar" aria-label="Alat potong">
      <button type="button" className={TOMBOL} onClick={urung} disabled={nonaktif || !bisaUrung} title="Urungkan (Ctrl+Z)">↶ Urungkan</button>
      <button type="button" className={TOMBOL} onClick={ulang} disabled={nonaktif || !bisaUlang} title="Ulangi (Ctrl+Shift+Z)">↷ Ulangi</button>
      {GARIS}
      <button type="button" className={TOMBOL} onClick={bagi} disabled={nonaktif || !bisaBagi} title="Bagi di garis putih (S)">✂ Bagi</button>
      <button type="button" className={TOMBOL} onClick={hapus} disabled={nonaktif || !segmenPilih} title="Hapus segmen yang dipilih (Delete)">
        {segmenPilih?.hapus ? "↩ Pulihkan" : "🗑 Hapus"}
      </button>
      {GARIS}
      <button type="button" className={TOMBOL} onClick={jedaOtomatis} disabled={nonaktif || !adaKata} title="Tandai semua bagian diam sebagai terhapus (bisa dipulihkan satu-satu)">
        ⚡ Hapus jeda otomatis
      </button>
    </div>
  );
}
