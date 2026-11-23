import { useRef, useState } from "react";
import { buatProyekDariTautan, unggahProyek } from "../api.js";
import { PILIHAN_KEPADATAN, PILIHAN_PANJANG, formatUkuran } from "../format.js";

const KOLOM = "mt-1.5 w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3.5 py-2.5 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500/60 focus:border-violet-500 disabled:opacity-60";
const LABEL = "text-sm font-medium text-zinc-300";
const BANTU = "text-xs text-zinc-500 mt-1 block";

/** Form proyek baru: dari berkas atau dari link YouTube. padaSelesai dipanggil setelah proyek dibuat. */
export default function FormProyek({ padaSelesai, padaKeluar }) {
  const [sumber, setSumber] = useState("link"); // "link" | "berkas"
  const [berkas, setBerkas] = useState(null);
  const [tautan, setTautan] = useState("");
  const [judul, setJudul] = useState("");
  const [kepadatan, setKepadatan] = useState("sedang");
  const [panjang, setPanjang] = useState("otomatis");
  const [rasio, setRasio] = useState("9:16");
  const [bahasa, setBahasa] = useState("auto");
  const [wajah, setWajah] = useState(true);
  const [kemajuan, setKemajuan] = useState(null); // null = tidak sedang mengunggah
  const [galatUnggah, setGalatUnggah] = useState("");
  const masukanBerkas = useRef(null);

  async function kirim(e) {
    e.preventDefault();
    if (sumber === "berkas" ? !berkas : !tautan.trim()) return;
    setGalatUnggah("");
    setKemajuan(0);
    const opsi = { title: judul, clip_density: kepadatan, clip_length: panjang, ratio: rasio, language: bahasa, face_tracking: wajah };
    try {
      if (sumber === "berkas") await unggahProyek(berkas, opsi, setKemajuan);
      else await buatProyekDariTautan(tautan, opsi);
      setBerkas(null);
      setTautan("");
      setJudul("");
      if (masukanBerkas.current) masukanBerkas.current.value = "";
      await padaSelesai();
    } catch (err) {
      if (err.status === 401) padaKeluar();
      else setGalatUnggah(err.message);
    } finally {
      setKemajuan(null);
    }
  }

  const mengunggah = kemajuan !== null;
  const siap = sumber === "berkas" ? !!berkas : !!tautan.trim();

  return (
    <form onSubmit={kirim} className="bg-zinc-900 rounded-2xl border border-zinc-800 shadow-xl shadow-black/20 overflow-hidden">
      <div className="px-5 pt-5">
        <div role="tablist" className="inline-flex rounded-xl bg-zinc-950 border border-zinc-800 p-1 text-sm">
          {[["link", "Link YouTube"], ["berkas", "Unggah berkas"]].map(([k, nama]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={sumber === k}
              disabled={mengunggah}
              onClick={() => setSumber(k)}
              className={`rounded-lg px-4 py-1.5 transition-colors ${sumber === k ? "bg-violet-600 text-white font-medium" : "text-zinc-400 hover:text-zinc-200"}`}
            >
              {nama}
            </button>
          ))}
        </div>
      </div>

      <div className="p-5 space-y-5">
        {sumber === "link" && (
          <label className="block">
            <span className={LABEL}>Link YouTube</span>
            <input
              type="url"
              value={tautan}
              maxLength={500}
              disabled={mengunggah}
              onChange={(e) => setTautan(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              className={`${KOLOM} text-base py-3`}
            />
            <span className={BANTU}>
              Pakai video milikmu sendiri atau yang kamu punya izinnya. Video diunduh oleh server, jadi proses lebih lama.
            </span>
          </label>
        )}

        {sumber === "berkas" && (
          <label className="block">
            <span className={LABEL}>Video</span>
            <div className="mt-1.5 rounded-xl border border-dashed border-zinc-700 bg-zinc-950 px-4 py-6 text-center hover:border-violet-500/60 transition-colors">
              <input
                ref={masukanBerkas}
                type="file"
                accept=".mp4,.mov,.mkv,.webm,.avi,video/*"
                disabled={mengunggah}
                onChange={(e) => setBerkas(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-zinc-400 file:mr-3 file:rounded-lg file:border-0 file:bg-violet-500/15 file:px-4 file:py-2 file:text-violet-300 hover:file:bg-violet-500/25"
              />
              {berkas && <span className="text-xs text-zinc-400 mt-2 block">{berkas.name} · {formatUkuran(berkas.size)}</span>}
            </div>
          </label>
        )}

        <details className="group rounded-xl border border-zinc-800 bg-zinc-950/50">
          <summary className="cursor-pointer select-none px-4 py-3 text-sm text-zinc-300 flex items-center justify-between list-none">
            <span>Pengaturan klip</span>
            <span className="text-xs text-zinc-500 group-open:hidden">Jumlah, durasi, rasio, bahasa</span>
          </summary>
          <div className="px-4 pb-4 space-y-4">
            <label className="block">
              <span className={LABEL}>Judul proyek (opsional)</span>
              <input
                value={judul}
                maxLength={200}
                disabled={mengunggah}
                onChange={(e) => setJudul(e.target.value)}
                placeholder={sumber === "link" ? "Kosong = memakai judul dari YouTube" : "Kosong = memakai nama berkas"}
                className={KOLOM}
              />
            </label>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block">
                <span className={LABEL}>Jumlah klip</span>
                <select value={kepadatan} disabled={mengunggah} onChange={(e) => setKepadatan(e.target.value)} className={KOLOM}>
                  {PILIHAN_KEPADATAN.map(([nilai, nama]) => (
                    <option key={nilai} value={nilai}>{nama}</option>
                  ))}
                </select>
                <span className={BANTU}>Otomatis, menyesuaikan durasi video dan bagian yang layak dijadikan klip.</span>
              </label>
              <label className="block">
                <span className={LABEL}>Durasi klip</span>
                <select value={panjang} disabled={mengunggah} onChange={(e) => setPanjang(e.target.value)} className={KOLOM}>
                  {PILIHAN_PANJANG.map(([nilai, nama]) => (
                    <option key={nilai} value={nilai}>{nama}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className={LABEL}>Rasio</span>
                <select value={rasio} disabled={mengunggah} onChange={(e) => setRasio(e.target.value)} className={KOLOM}>
                  <option value="9:16">9:16 (vertikal)</option>
                  <option value="1:1">1:1 (persegi)</option>
                  <option value="4:5">4:5</option>
                </select>
              </label>
              <label className="block">
                <span className={LABEL}>Bahasa video</span>
                <select value={bahasa} disabled={mengunggah} onChange={(e) => setBahasa(e.target.value)} className={KOLOM}>
                  <option value="auto">Otomatis</option>
                  <option value="id">Indonesia</option>
                  <option value="en">Inggris</option>
                </select>
              </label>
            </div>

            <label className="flex items-center gap-2 text-sm text-zinc-300">
              <input type="checkbox" className="accent-violet-500 w-4 h-4" checked={wajah} disabled={mengunggah} onChange={(e) => setWajah(e.target.checked)} />
              Ikuti wajah pembicara
            </label>
          </div>
        </details>

        {galatUnggah && (
          <p role="alert" className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">
            {galatUnggah}
          </p>
        )}

        {mengunggah && sumber === "berkas" && (
          <div>
            <div className="flex justify-between text-xs text-zinc-400 mb-1">
              <span>{kemajuan < 100 ? "Mengunggah..." : "Menyimpan..."}</span>
              <span>{kemajuan}%</span>
            </div>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-violet-500 to-fuchsia-500 transition-all" style={{ width: `${kemajuan}%` }} />
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={!siap || mengunggah}
          className="w-full sm:w-auto rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-medium px-6 py-3 transition-colors disabled:opacity-40 disabled:hover:bg-violet-600"
        >
          {mengunggah ? (sumber === "berkas" ? "Mengunggah..." : "Mengirim...") : sumber === "berkas" ? "Unggah dan buat klip" : "Ambil dari YouTube dan buat klip"}
        </button>
      </div>
    </form>
  );
}
