import { alamatVideo } from "../api.js";
import { perkiraanSisa } from "../format.js";

/**
 * Baris status di atas timeline. Satu tempat untuk semua yang berkaitan dengan render:
 * sedang dirender (persen, tahap, perkiraan sisa, Batal), hasil (berhasil/gagal), atau keterangan klip + tombol Render ulang.
 */
export default function StatusRender({ id, idKlip, klip, dirender, kemajuan, menungguLama, hasil, tutupHasil, putarHasil, infoKlip, perluRender, alasanMati, render, batalRender, sibuk }) {
  if (dirender) {
    const persen = kemajuan?.persen ?? 0;
    const sisa = kemajuan ? perkiraanSisa(kemajuan.persen, kemajuan.berjalan_detik) : null;
    return (
      <div className="mb-3 rounded-xl border border-violet-500/30 bg-violet-500/10 px-4 py-3" role="status" aria-live="polite">
        <div className="flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex justify-between text-sm text-violet-100 mb-1.5">
              <span className="truncate">{kemajuan ? kemajuan.tahap : "Menunggu worker..."}</span>
              <span className="font-semibold tabular-nums">{kemajuan ? `${persen}%` : ""}</span>
            </div>
            <div className="h-2 rounded-full bg-zinc-800 overflow-hidden" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={persen}>
              <div className="h-full bg-violet-500 transition-all duration-500" style={{ width: `${kemajuan ? Math.max(persen, 2) : 0}%` }} />
            </div>
            <p className="text-[11px] text-violet-200/70 mt-1">
              {menungguLama
                ? "Sudah lebih dari 1 menit belum diambil worker. Pastikan jendela terminal python -m backend.worker masih berjalan (atau sedang mengerjakan proyek lain)."
                : sisa ? `Perkiraan sisa ${sisa} (kasar)` : "Render ulang memakan beberapa menit. Halaman ini boleh ditinggal."}
            </p>
          </div>
          <button type="button" onClick={batalRender} disabled={sibuk}
            className="shrink-0 rounded-lg border border-violet-400/40 text-violet-100 text-sm px-4 py-2 hover:bg-violet-500/20 disabled:opacity-50">
            {sibuk ? "Membatalkan..." : "Batal"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      {hasil && (
        <div role="status" className={`mb-3 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 text-sm ${
          hasil.jenis === "ok" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-100" : hasil.jenis === "lama" ? "border-amber-500/40 bg-amber-500/10 text-amber-100" : "border-red-500/40 bg-red-500/10 text-red-100"}`}>
          <span className="flex-1 min-w-0">
            {hasil.jenis === "ok" && <><b>✓ Render selesai.</b> Video hasil sudah diperbarui dan tampil di pratinjau.</>}
            {hasil.jenis === "lama" && <><b>Render selesai, tetapi perubahan belum terlihat.</b> Kemungkinan worker masih versi lama: tutup jendela worker, jalankan lagi <code>python -m backend.worker</code>, lalu Render ulang.</>}
            {hasil.jenis === "gagal" && <><b>Render gagal.</b> Video lama masih aman. {hasil.pesan ? <span className="block mt-1 text-xs opacity-80 break-words">Alasan: {hasil.pesan}</span> : "Coba Render ulang lagi."}</>}
          </span>
          {hasil.jenis !== "gagal" && klip.ada_video && (
            <>
              <button type="button" onClick={putarHasil} className="rounded-lg bg-white/90 text-zinc-900 text-sm font-medium px-3 py-1.5 hover:bg-white">Putar hasil</button>
              <a href={alamatVideo(id, idKlip, true, klip.size_bytes)} className="rounded-lg border border-current/40 text-sm px-3 py-1.5 hover:bg-white/10">Unduh</a>
            </>
          )}
          <button type="button" onClick={tutupHasil} aria-label="Tutup pemberitahuan" className="rounded-lg px-2 py-1 hover:bg-white/10">✕</button>
        </div>
      )}
      <div className="mb-3 flex items-center gap-3">
        <p className="flex-1 min-w-0 text-xs text-zinc-400 truncate">{infoKlip}</p>
        {alasanMati && <span className="text-xs text-red-300">{alasanMati}</span>}
        <button type="button" onClick={render} disabled={sibuk || !perluRender || !!alasanMati}
          className="shrink-0 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-5 py-2 disabled:opacity-40 disabled:hover:bg-violet-600 transition-colors">
          {sibuk ? "Mengirim..." : perluRender ? "Render ulang" : "Tidak ada perubahan"}
        </button>
      </div>
    </>
  );
}
