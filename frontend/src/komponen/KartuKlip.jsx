import { useState } from "react";
import { alamatVideo } from "../api.js";
import { formatDurasi, formatRentang, hashtagTersisa, persen, teksSalin } from "../format.js";

const KOMPONEN = [
  ["hook", "Hook"],
  ["flow", "Flow"],
  ["value", "Value"],
  ["trend", "Intensitas"],
];

export default function KartuKlip({ klip, nomor }) {
  const [tersalin, setTersalin] = useState(false);

  async function salin() {
    try {
      await navigator.clipboard.writeText(teksSalin(klip));
      setTersalin(true);
      setTimeout(() => setTersalin(false), 2000);
    } catch {
      /* izin papan klip ditolak: tombol tetap seperti semula */
    }
  }

  return (
    <li className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden sm:flex">
      <div className="bg-black sm:w-56 shrink-0 flex items-center justify-center">
        {klip.ada_video ? (
          <video
            controls
            preload="metadata"
            src={alamatVideo(klip.project_id, klip.id)}
            className="w-full max-h-96 sm:max-h-none sm:h-full object-contain"
            aria-label={`Klip ${nomor}`}
          />
        ) : (
          <p className="text-xs text-slate-300 p-6 text-center">Video belum tersedia</p>
        )}
      </div>

      <div className="p-4 space-y-3 min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs text-slate-500">
              Klip {nomor} · {formatRentang(klip.start_sec, klip.end_sec)} · {formatDurasi(klip.duration_sec)}
            </p>
            <h3 className="font-semibold text-slate-900">{klip.title || `Klip ${nomor}`}</h3>
          </div>
          <div className="shrink-0 text-center rounded-lg bg-indigo-50 px-3 py-1.5" title="Skor akhir 0-100">
            <div className="text-lg font-bold text-indigo-700 leading-none">{Math.round(klip.score)}</div>
            <div className="text-[10px] text-indigo-600">skor</div>
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5">
          {KOMPONEN.map(([kunci, nama]) => (
            <div key={kunci}>
              <dt className="flex justify-between text-[11px] text-slate-500">
                <span>{nama}</span>
                <span>{persen(klip[kunci])}%</span>
              </dt>
              <dd className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div className="h-full bg-indigo-400" style={{ width: `${persen(klip[kunci])}%` }} />
              </dd>
            </div>
          ))}
        </dl>

        {klip.caption && <p className="text-sm text-slate-700 whitespace-pre-line">{klip.caption}</p>}
        {hashtagTersisa(klip).length > 0 && <p className="text-xs text-indigo-600 break-words">{hashtagTersisa(klip).join(" ")}</p>}

        <div className="flex flex-wrap gap-2 pt-1">
          {klip.ada_video && (
            <a
              href={alamatVideo(klip.project_id, klip.id, true)}
              className="rounded-lg bg-indigo-600 text-white text-sm font-medium px-4 py-2 hover:bg-indigo-700"
            >
              Unduh
            </a>
          )}
          <button onClick={salin} className="rounded-lg border border-slate-300 text-sm px-4 py-2 hover:bg-slate-50">
            {tersalin ? "Tersalin" : "Salin caption"}
          </button>
        </div>
      </div>
    </li>
  );
}
