import { useState } from "react";
import { alamatVideo, batalRenderKlip, hapusKlip, ubahKlip } from "../api.js";
import DialogKonfirmasi from "./DialogKonfirmasi.jsx";
import { alamat } from "../rute.js";
import KemajuanRender from "./KemajuanRender.jsx";
import { formatDurasi, formatRentang, hashtagTersisa, persen, teksSalin, tingkatSkor, uraiHashtag } from "../format.js";

const WARNA_SKOR = {
  tinggi: "bg-emerald-500/15 text-emerald-300",
  sedang: "bg-amber-500/15 text-amber-300",
  rendah: "bg-zinc-800 text-zinc-300",
};

const KOMPONEN = [
  ["hook", "Hook"],
  ["flow", "Flow"],
  ["value", "Value"],
  ["trend", "Intensitas"],
];

const KOLOM = "mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500/60";

export default function KartuKlip({ klip, nomor, padaUbah, padaHapus, padaKeluar }) {
  const [konfirmasi, setKonfirmasi] = useState(false);
  const [menghapus, setMenghapus] = useState(false);
  const [galatHapus, setGalatHapus] = useState("");
  async function hapus() {
    setMenghapus(true);
    setGalatHapus("");
    try {
      await hapusKlip(klip.project_id, klip.id);
      padaHapus?.(klip.id);
    } catch (err) {
      if (err.status === 401) padaKeluar?.();
      else setGalatHapus(err.message);
      setMenghapus(false);
    }
  }

  const [tersalin, setTersalin] = useState(false);
  const [mengedit, setMengedit] = useState(false);
  const [judul, setJudul] = useState("");
  const [caption, setCaption] = useState("");
  const [tagar, setTagar] = useState("");
  const [menyimpan, setMenyimpan] = useState(false);
  const [galat, setGalat] = useState("");
  const dirender = klip.status === "rendering";
  const [membatalkan, setMembatalkan] = useState(false);

  async function batalRender() {
    setMembatalkan(true);
    setGalat("");
    try {
      padaUbah?.(await batalRenderKlip(klip.project_id, klip.id));
    } catch (err) {
      if (err.status === 401) padaKeluar?.();
      else setGalat(err.message);
    } finally {
      setMembatalkan(false);
    }
  }

  function mulaiEdit() {
    setJudul(klip.title);
    setCaption(klip.caption);
    setTagar(klip.hashtags.join(" "));
    setGalat("");
    setMengedit(true);
  }

  async function simpan(e) {
    e.preventDefault();
    setMenyimpan(true);
    setGalat("");
    try {
      const baru = await ubahKlip(klip.project_id, klip.id, { title: judul, caption, hashtags: uraiHashtag(tagar) });
      padaUbah?.(baru);
      setMengedit(false);
    } catch (err) {
      if (err.status === 401) padaKeluar?.();
      else setGalat(err.message);
    } finally {
      setMenyimpan(false);
    }
  }

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
    <li className="bg-zinc-900 rounded-2xl border border-zinc-800 overflow-hidden flex flex-col hover:border-zinc-700 transition-colors">
      <div className="relative bg-black aspect-[9/16] max-h-[30rem] w-full flex items-center justify-center">
        {klip.ada_video ? (
          <video
            controls
            preload="metadata"
            src={alamatVideo(klip.project_id, klip.id, false, klip.size_bytes)}
            className="w-full h-full object-contain"
            aria-label={`Klip ${nomor}`}
          />
        ) : (
          <p className="text-xs text-zinc-400 p-6 text-center">Video belum tersedia</p>
        )}
        {dirender && (
          <div className="absolute inset-x-0 bottom-0 bg-black/70 backdrop-blur text-xs text-violet-200 py-2 px-3 space-y-2">
            <KemajuanRender kemajuan={klip.kemajuan} />
            <button type="button" onClick={batalRender} disabled={membatalkan}
              className="rounded-lg border border-white/20 px-2 py-0.5 text-white hover:bg-white/10 disabled:opacity-50 block mx-auto">
              {membatalkan ? "Membatalkan..." : "Batal"}
            </button>
          </div>
        )}
        <div className={`absolute top-3 left-3 rounded-xl px-2.5 py-1 text-center backdrop-blur ${WARNA_SKOR[tingkatSkor(klip.score)]}`} title="Skor akhir 0-100">
          <div className="text-base font-bold leading-none">{Math.round(klip.score)}</div>
          <div className="text-[10px]">skor</div>
        </div>
      </div>

      <div className="p-4 space-y-3 min-w-0 flex-1 flex flex-col">
        <div>
          <p className="text-xs text-zinc-500">
            Klip {nomor} · {formatRentang(klip.start_sec, klip.end_sec)} · {formatDurasi(klip.duration_sec)}
          </p>
          {!mengedit && <h3 className="font-semibold text-white leading-snug mt-0.5">{klip.title || `Klip ${nomor}`}</h3>}
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
          {KOMPONEN.map(([kunci, nama]) => (
            <div key={kunci}>
              <dt className="flex justify-between text-[11px] text-zinc-400">
                <span>{nama}</span>
                <span>{persen(klip[kunci])}%</span>
              </dt>
              <dd className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                <div className="h-full bg-violet-500" style={{ width: `${persen(klip[kunci])}%` }} />
              </dd>
            </div>
          ))}
        </dl>

        {klip.status === "failed" && (
          <p role="alert" className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
            Render ulang gagal. Video lama masih tersedia; buka Editor untuk mencoba lagi.
          </p>
        )}

        {mengedit ? (
          <form onSubmit={simpan} className="space-y-3">
            <label className="block text-xs text-zinc-400">
              Judul
              <input value={judul} maxLength={200} onChange={(e) => setJudul(e.target.value)} className={KOLOM} />
            </label>
            <label className="block text-xs text-zinc-400">
              Caption <span className="text-zinc-600">({caption.length}/500)</span>
              <textarea value={caption} maxLength={500} rows={5} onChange={(e) => setCaption(e.target.value)} className={KOLOM} />
            </label>
            <label className="block text-xs text-zinc-400">
              Hashtag (pisahkan dengan spasi)
              <input value={tagar} onChange={(e) => setTagar(e.target.value)} placeholder="#seru #podcast" className={KOLOM} />
            </label>
            {galat && <p role="alert" className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{galat}</p>}
            <div className="flex gap-2">
              <button type="submit" disabled={menyimpan} className="rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 disabled:opacity-60">
                {menyimpan ? "Menyimpan..." : "Simpan"}
              </button>
              <button type="button" disabled={menyimpan} onClick={() => setMengedit(false)} className="rounded-xl border border-zinc-700 text-zinc-200 text-sm px-4 py-2 hover:bg-zinc-800">
                Batal
              </button>
            </div>
          </form>
        ) : (
          <>
            {klip.caption && <p className="text-sm text-zinc-300 whitespace-pre-line line-clamp-4">{klip.caption}</p>}
            {hashtagTersisa(klip).length > 0 && (
              <p className="flex flex-wrap gap-1.5">
                {hashtagTersisa(klip).map((h) => (
                  <span key={h} className="text-xs rounded-full bg-violet-500/15 text-violet-300 px-2 py-0.5">{h}</span>
                ))}
              </p>
            )}
            <div className="flex flex-wrap gap-2 pt-1 mt-auto">
              {klip.ada_video && (
                <a
                  href={alamatVideo(klip.project_id, klip.id, true)}
                  className="rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 transition-colors"
                >
                  Unduh
                </a>
              )}
              <a href={alamat.editor(klip.project_id, klip.id)} className="rounded-xl border border-zinc-700 text-zinc-200 text-sm px-4 py-2 hover:bg-zinc-800 transition-colors">
                Editor
              </a>
              <button onClick={mulaiEdit} className="rounded-xl border border-zinc-700 text-zinc-200 text-sm px-4 py-2 hover:bg-zinc-800 transition-colors">
                Edit teks
              </button>
              <button onClick={salin} className="rounded-xl border border-zinc-700 text-zinc-200 text-sm px-4 py-2 hover:bg-zinc-800 transition-colors">
                {tersalin ? "Tersalin" : "Salin caption"}
              </button>
              {klip.status !== "rendering" && (
                <button onClick={() => setKonfirmasi(true)} className="rounded-xl border border-zinc-700 text-zinc-400 hover:text-red-300 hover:border-red-500/50 text-sm px-3 py-2 transition-colors">
                  Hapus
                </button>
              )}
            </div>
          </>
        )}
      </div>
      {konfirmasi && (
        <DialogKonfirmasi judul="Hapus klip ini?" sibuk={menghapus} galat={galatHapus} padaYa={hapus} padaBatal={() => setKonfirmasi(false)}
          isi={<><p>Klip <b>{klip.title || `#${nomor}`}</b> dan berkas videonya akan dihapus.</p><p>Tindakan ini tidak bisa dibatalkan.</p></>} />
      )}
    </li>
  );
}
