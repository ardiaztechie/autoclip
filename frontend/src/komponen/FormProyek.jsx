import { useRef, useState } from "react";
import { buatProyekDariTautan, unggahProyek } from "../api.js";
import { PILIHAN_KEPADATAN, PILIHAN_PANJANG, formatUkuran } from "../format.js";

const KOLOM = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500";

/** Form proyek baru: dari berkas atau dari link YouTube. padaSelesai dipanggil setelah proyek dibuat. */
export default function FormProyek({ padaSelesai, padaKeluar }) {
  const [sumber, setSumber] = useState("berkas"); // "berkas" | "link"
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

  return (
    <form onSubmit={kirim} className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 space-y-4">
      <div role="tablist" className="inline-flex rounded-lg bg-slate-100 p-1 text-sm">
        {[["berkas", "Dari berkas"], ["link", "Dari link YouTube"]].map(([k, nama]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={sumber === k}
            disabled={mengunggah}
            onClick={() => setSumber(k)}
            className={`rounded-md px-3 py-1.5 ${sumber === k ? "bg-white shadow-sm font-medium" : "text-slate-600"}`}
          >
            {nama}
          </button>
        ))}
      </div>

      {sumber === "link" && (
        <label className="block">
          <span className="text-sm font-medium">Link YouTube</span>
          <input
            type="url"
            value={tautan}
            maxLength={500}
            disabled={mengunggah}
            onChange={(e) => setTautan(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            className={KOLOM}
          />
          <span className="text-xs text-slate-500">
            Pakai video milikmu sendiri atau yang kamu punya izinnya. Video diunduh oleh server, jadi proses lebih lama.
          </span>
        </label>
      )}

      {sumber === "berkas" && <label className="block">
        <span className="text-sm font-medium">Video</span>
        <input
          ref={masukanBerkas}
          type="file"
          accept=".mp4,.mov,.mkv,.webm,.avi,video/*"
          disabled={mengunggah}
          onChange={(e) => setBerkas(e.target.files?.[0] ?? null)}
          className="mt-1 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-4 file:py-2 file:text-indigo-700 hover:file:bg-indigo-100"
        />
        {berkas && <span className="text-xs text-slate-500">{berkas.name} · {formatUkuran(berkas.size)}</span>}
      </label>}

      <label className="block">
        <span className="text-sm font-medium">Judul proyek (opsional)</span>
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
          <span className="text-sm font-medium">Jumlah klip</span>
          <select value={kepadatan} disabled={mengunggah} onChange={(e) => setKepadatan(e.target.value)} className={KOLOM}>
            {PILIHAN_KEPADATAN.map(([nilai, nama]) => (
              <option key={nilai} value={nilai}>{nama}</option>
            ))}
          </select>
          <span className="text-xs text-slate-500">Jumlahnya otomatis, menyesuaikan durasi video dan bagian yang layak dijadikan klip.</span>
        </label>
        <label className="block">
          <span className="text-sm font-medium">Durasi klip</span>
          <select value={panjang} disabled={mengunggah} onChange={(e) => setPanjang(e.target.value)} className={KOLOM}>
            {PILIHAN_PANJANG.map(([nilai, nama]) => (
              <option key={nilai} value={nilai}>{nama}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <label className="block">
          <span className="text-sm font-medium">Rasio</span>
          <select value={rasio} disabled={mengunggah} onChange={(e) => setRasio(e.target.value)} className={KOLOM}>
            <option value="9:16">9:16 (vertikal)</option>
            <option value="1:1">1:1 (persegi)</option>
            <option value="4:5">4:5</option>
          </select>
        </label>
        <label className="block">
          <span className="text-sm font-medium">Bahasa video</span>
          <select value={bahasa} disabled={mengunggah} onChange={(e) => setBahasa(e.target.value)} className={KOLOM}>
            <option value="auto">Otomatis</option>
            <option value="id">Indonesia</option>
            <option value="en">Inggris</option>
          </select>
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={wajah} disabled={mengunggah} onChange={(e) => setWajah(e.target.checked)} />
        Ikuti wajah pembicara
      </label>

      {galatUnggah && (
        <p role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {galatUnggah}
        </p>
      )}

      {mengunggah && sumber === "berkas" && (
        <div>
          <div className="flex justify-between text-xs text-slate-500 mb-1">
            <span>{kemajuan < 100 ? "Mengunggah..." : "Menyimpan..."}</span>
            <span>{kemajuan}%</span>
          </div>
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full bg-indigo-500 transition-all" style={{ width: `${kemajuan}%` }} />
          </div>
        </div>
      )}

      <button
        type="submit"
        disabled={(sumber === "berkas" ? !berkas : !tautan.trim()) || mengunggah}
        className="rounded-lg bg-indigo-600 text-white font-medium px-5 py-2.5 hover:bg-indigo-700 disabled:opacity-50"
      >
        {mengunggah ? (sumber === "berkas" ? "Mengunggah..." : "Mengirim...") : sumber === "berkas" ? "Unggah dan buat klip" : "Ambil dari YouTube dan buat klip"}
      </button>
    </form>
  );
}
