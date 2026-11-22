import { formatWaktu, labelJumlah, labelPanjang, labelStatus, masihBerjalan } from "../format.js";
import { alamat } from "../rute.js";

const WARNA_STATUS = {
  queued: "bg-slate-100 text-slate-700",
  processing: "bg-amber-100 text-amber-800",
  done: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-700",
};

export default function KartuProyek({ p }) {
  return (
    <li className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-slate-900 truncate">
            <a href={alamat.detail(p.id)} className="hover:text-indigo-700 hover:underline">
              {p.title || (p.source_type === "link" ? "Video YouTube" : "Tanpa judul")}
            </a>
          </h3>
          <p className="text-xs text-slate-500 truncate">{p.source_ref}</p>
        </div>
        <span className={`shrink-0 text-xs font-medium rounded-full px-2.5 py-1 ${WARNA_STATUS[p.status] ?? WARNA_STATUS.queued}`}>
          {labelStatus(p.status)}
        </span>
      </div>

      {masihBerjalan(p) && (
        <div>
          <div className="flex justify-between text-xs text-slate-500 mb-1">
            <span>{p.stage}</span>
            <span>{p.progress}%</span>
          </div>
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full bg-indigo-500 transition-all" style={{ width: `${p.progress}%` }} />
          </div>
        </div>
      )}

      {p.status === "failed" && p.error && (
        <p className="text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">{p.error}</p>
      )}

      {p.status === "done" && (
        <a href={alamat.detail(p.id)} className="inline-block rounded-lg bg-indigo-600 text-white text-sm font-medium px-4 py-1.5 hover:bg-indigo-700">
          Lihat klip
        </a>
      )}

      <p className="text-xs text-slate-500">
        {labelJumlah(p)} · {labelPanjang(p)} · rasio {p.ratio} · bahasa {p.language === "auto" ? "otomatis" : p.language} ·{" "}
        {p.face_tracking ? "ikuti wajah" : "tanpa ikuti wajah"} · {formatWaktu(p.created_at)}
      </p>
    </li>
  );
}
