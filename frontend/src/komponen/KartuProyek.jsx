import { useState } from "react";
import { batalProyek, hapusProyek } from "../api.js";
import DialogKonfirmasi from "./DialogKonfirmasi.jsx";
import { dibatalkan, formatWaktu, labelJumlah, labelPanjang, labelProyek, masihBerjalan } from "../format.js";
import { alamat } from "../rute.js";

const WARNA_STATUS = {
  queued: "bg-zinc-800 text-zinc-300",
  processing: "bg-amber-500/15 text-amber-300",
  done: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-red-500/15 text-red-300",
};

export default function KartuProyek({ p: dariDaftar, padaHapus }) {
  const [konfirmasi, setKonfirmasi] = useState(false);
  const [menghapus, setMenghapus] = useState(false);
  const [galatHapus, setGalatHapus] = useState("");
  const [lokal, setLokal] = useState(null);
  const [membatalkan, setMembatalkan] = useState(false);
  const [galat, setGalat] = useState("");
  // Setelah dibatalkan, tampilkan hasilnya langsung (tanpa menunggu daftar dimuat ulang) selama daftar masih menganggapnya berjalan.
  const p = lokal && lokal.id === dariDaftar.id && masihBerjalan(dariDaftar) ? lokal : dariDaftar;

  async function batal() {
    setMembatalkan(true);
    setGalat("");
    try {
      setLokal(await batalProyek(p.id));
    } catch (e) {
      setGalat(e.status === 401 ? "Sesi habis. Muat ulang halaman lalu masuk lagi." : e.message);
    } finally {
      setMembatalkan(false);
    }
  }

  async function hapus() {
    setMenghapus(true);
    setGalatHapus("");
    try {
      await hapusProyek(p.id);
      setKonfirmasi(false);
      padaHapus?.(p.id);
    } catch (e) {
      setGalatHapus(e.status === 401 ? "Sesi habis. Muat ulang halaman lalu masuk lagi." : e.message);
    } finally {
      setMenghapus(false);
    }
  }

  return (
    <li className="bg-zinc-900 rounded-2xl border border-zinc-800 p-4 space-y-3 flex flex-col hover:border-zinc-700 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-white truncate">
            <a href={alamat.detail(p.id)} className="hover:text-violet-300">
              {p.title || (p.source_type === "link" ? "Video YouTube" : "Tanpa judul")}
            </a>
          </h3>
          <p className="text-xs text-zinc-500 truncate">{p.source_ref}</p>
        </div>
        <span className={`shrink-0 text-xs font-medium rounded-full px-2.5 py-1 ${dibatalkan(p) ? WARNA_STATUS.queued : WARNA_STATUS[p.status] ?? WARNA_STATUS.queued}`}>
          {labelProyek(p)}
        </span>
      </div>

      {masihBerjalan(p) && (
        <div>
          <div className="flex justify-between text-xs text-zinc-400 mb-1">
            <span>{p.stage}</span>
            <span>{p.progress}%</span>
          </div>
          <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-violet-500 to-fuchsia-500 transition-all" style={{ width: `${p.progress}%` }} />
          </div>
          <button type="button" onClick={batal} disabled={membatalkan}
            className="mt-2 rounded-lg border border-zinc-700 text-zinc-300 text-xs px-3 py-1 hover:bg-zinc-800 disabled:opacity-50">
            {membatalkan ? "Membatalkan..." : "Batalkan"}
          </button>
        </div>
      )}

      {galat && <p role="alert" className="text-sm text-red-300 bg-red-500/10 rounded-xl px-3 py-2">{galat}</p>}

      {p.status === "failed" && !dibatalkan(p) && p.error && (
        <p className="text-sm text-red-300 bg-red-500/10 rounded-xl px-3 py-2">{p.error}</p>
      )}

      <p className="text-xs text-zinc-500 mt-auto">
        {labelJumlah(p)} · {labelPanjang(p)} · rasio {p.ratio} · bahasa {p.language === "auto" ? "otomatis" : p.language} ·{" "}
        {p.face_tracking ? "ikuti wajah" : "tanpa ikuti wajah"} · {formatWaktu(p.created_at)}
      </p>

      <div className="flex items-center gap-2">
        {p.status === "done" && (
          <a href={alamat.detail(p.id)} className="inline-block rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 transition-colors">
            Lihat klip
          </a>
        )}
        {!masihBerjalan(p) && (
          <button type="button" onClick={() => setKonfirmasi(true)} className="rounded-xl border border-zinc-700 text-zinc-400 hover:text-red-300 hover:border-red-500/50 text-sm px-3 py-2 transition-colors">
            Hapus
          </button>
        )}
      </div>
      {konfirmasi && (
        <DialogKonfirmasi judul="Hapus proyek ini?" sibuk={menghapus} galat={galatHapus} padaYa={hapus} padaBatal={() => setKonfirmasi(false)}
          isi={<><p><b>{p.title || "Proyek tanpa judul"}</b> akan dihapus bersama semua klip dan berkas videonya di server.</p><p>Tindakan ini tidak bisa dibatalkan.</p></>} />
      )}
    </li>
  );
}
