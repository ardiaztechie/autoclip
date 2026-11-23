import { perkiraanSisa } from "../format.js";

/** Bar kemajuan render ulang. kemajuan = {persen, tahap, berjalan_detik} dari API, atau null/undefined bila worker belum melapor. */
export default function KemajuanRender({ kemajuan }) {
  const persen = kemajuan?.persen ?? 0;
  const sisa = kemajuan ? perkiraanSisa(kemajuan.persen, kemajuan.berjalan_detik) : null;
  return (
    <div className="space-y-1" role="status" aria-live="polite">
      <div className="flex justify-between text-xs text-zinc-300">
        <span>{kemajuan ? kemajuan.tahap : "Menunggu worker..."}</span>
        <span>{kemajuan ? `${persen}%` : ""}</span>
      </div>
      <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={persen}>
        <div className="h-full bg-violet-500 transition-all duration-500" style={{ width: `${persen}%` }} />
      </div>
      <p className="text-[11px] text-zinc-500">{sisa ? `Perkiraan: ${sisa} (kasar)` : "Perkiraan sisa waktu muncul sesudah beberapa saat."}</p>
    </div>
  );
}
