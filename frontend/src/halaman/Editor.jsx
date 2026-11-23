import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { alamatSumber, alamatVideo, batalRenderKlip, daftarKlip, detailProyek, kataRentang, renderUlangKlip, simpanPotong, ubahKlip } from "../api.js";
import {
  formatDurasi,
  formatWaktuDetail,
  hitungJeda,
  kurangiSelang,
  tambahSelang,
  segmenDi,
  segmenKlip,
  selangDalam,
  totalJeda,
  jedaSebelum,
  pesanBatasKlip,
  persen,
  tingkatSkor,
  uraiHashtag,
  uraiWaktu,
} from "../format.js";
import { alamat } from "../rute.js";
import GarisWaktu from "../komponen/GarisWaktu.jsx";
import TombolTema from "../komponen/TombolTema.jsx";
import BilahPotong from "../komponen/BilahPotong.jsx";
import StatusRender from "../komponen/StatusRender.jsx";
import PanelSubtitle from "../komponen/PanelSubtitle.jsx";
import TidakAda from "./TidakAda.jsx";

const BAGIAN_KATA = 120; // detik per permintaan transkrip untuk garis waktu
const MARGIN = 30; // detik di kiri/kanan klip yang ikut ditampilkan (transkrip dan timeline)
const KOLOM = "mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-violet-500/60";
const TOMBOL = "rounded-xl border border-zinc-700 text-zinc-200 text-sm px-3 py-2 hover:bg-zinc-800 transition-colors disabled:opacity-50";
const UTAMA = "rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 transition-colors disabled:opacity-50";
const WARNA_SKOR = { tinggi: "text-emerald-300", sedang: "text-amber-300", rendah: "text-zinc-300" };
const KOMPONEN = [["hook", "Hook"], ["flow", "Flow"], ["value", "Value"], ["trend", "Intensitas"]];

function Galat({ children }) {
  return <p role="alert" className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">{children}</p>;
}

export default function Editor({ id, idKlip, padaKeluar }) {
  const [proyek, setProyek] = useState(undefined); // undefined = memuat, null = tidak ada
  const [klip, setKlip] = useState(null);
  const [kataSemua, setKataSemua] = useState([]); // transkrip yang sudah dimuat (bagian demi bagian), urut menurut waktu
  const terMuat = useRef(new Set());              // nomor bagian (tiap BAGIAN_KATA detik) yang sudah/sedang dimuat
  const [galat, setGalat] = useState("");
  const [tab, setTab] = useState("subtitle");
  const [potong, setPotong] = useState([]);       // bagian yang dihapus secara manual: [[a, b], ...] detik video asli
  const [titikBagi, setTitikBagi] = useState([]); // titik bagi yang belum diikuti penghapusan (hanya di layar)
  const [riwayat, setRiwayat] = useState({ lalu: [], depan: [] }); // untuk Urungkan/Ulangi
  const [posisi, setPosisi] = useState(null);     // playhead terakhir (tetap ada saat video dijeda)
  const [mulai, setMulai] = useState(0);
  const [akhir, setAkhir] = useState(0);
  const [judul, setJudul] = useState("");
  const [caption, setCaption] = useState("");
  const [tagar, setTagar] = useState("");
  const [sibuk, setSibuk] = useState(false);
  const [pesan, setPesan] = useState("");
  const [kepala, setKepala] = useState(null);
  useEffect(() => {
    if (kepala !== null) setPosisi(kepala);
  }, [kepala]);
  const [lihatSumber, setLihatSumber] = useState(false); // false: video klip hasil render; true: video asli di posisi batas
  const [sumberHilang, setSumberHilang] = useState(false);
  const videoRef = useRef(null);
  const tertunda = useRef(null);   // waktu (detik video asli) yang harus ditampilkan begitu video asli siap
  const bingkai = useRef(0);
  const daftarKataRef = useRef(null);

  const sinkronkanDraf = useCallback((k) => {
    setMulai(k.start_sec);
    setAkhir(k.end_sec);
    setPotong(k.potong ?? []);
    setTitikBagi([]);
    setRiwayat({ lalu: [], depan: [] });
  }, []);

  const muat = useCallback(async () => {
    try {
      const [p, daftar] = await Promise.all([detailProyek(id), daftarKlip(id)]);
      const k = daftar.find((x) => x.id === idKlip);
      if (!k) {
        setProyek(null);
        return;
      }
      setProyek(p);
      setKlip(k);
      setGalat("");
      return k;
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else if (e.status === 404) setProyek(null);
      else setGalat(e.message);
    }
    return undefined;
  }, [id, idKlip, padaKeluar]);

  // Memuat transkrip bagian [a, b] (detik video asli) bila belum; hasilnya digabung ke kataSemua tanpa duplikat.
  const pastikanKata = useCallback(async (a, b) => {
    const dari = Math.max(0, Math.floor(a / BAGIAN_KATA));
    const sampai = Math.max(dari, Math.floor(b / BAGIAN_KATA));
    for (let n = dari; n <= sampai && n < dari + 12; n += 1) {
      if (terMuat.current.has(n)) continue;
      terMuat.current.add(n);
      try {
        const r = await kataRentang(id, Math.max(0, n * BAGIAN_KATA - 1), (n + 1) * BAGIAN_KATA + 1);
        setKataSemua((lama) => {
          const peta = new Map(lama.map((k) => [k.s, k]));
          for (const k of r.kata) peta.set(k.s, k);
          return [...peta.values()].sort((x, y) => x.s - y.s);
        });
      } catch (e) {
        terMuat.current.delete(n);
        if (e.status === 401) padaKeluar();
      }
    }
  }, [id, padaKeluar]);

  // Muat pertama: klip, lalu transkrip di sekitarnya.
  useEffect(() => {
    let batal = false;
    setProyek(undefined);
    muat().then(async (k) => {
      if (!k || batal) return;
      sinkronkanDraf(k);
      setJudul(k.title);
      setCaption(k.caption);
      setTagar(k.hashtags.join(" "));
      terMuat.current = new Set();
      setKataSemua([]);
      if (!batal) pastikanKata(k.start_sec - MARGIN, k.end_sec + MARGIN);
    });
    return () => {
      batal = true;
    };
  }, [id, idKlip, muat, sinkronkanDraf, pastikanKata]);

  // Hasil render: pita berhasil/gagal setelah status berpindah dari 'rendering'. Dibatalkan sendiri tidak dihitung.
  const [hasil, setHasil] = useState(null);
  const statusLalu = useRef(null);
  const dibatalkanSendiri = useRef(false);
  useEffect(() => {
    const lalu = statusLalu.current;
    statusLalu.current = klip?.status ?? null;
    if (lalu !== "rendering" || !klip || klip.status === "rendering") return;
    if (dibatalkanSendiri.current) {
      dibatalkanSendiri.current = false;
      return;
    }
    if (klip.status === "failed") setHasil({ jenis: "gagal", pesan: klip.galat_render });
    else {
      setHasil({ jenis: klip.subtitle_perlu_render ? "lama" : "ok" });
      setLihatSumber(false);
    }
  }, [klip]);

  // Selama dirender ulang: periksa tiap 3 detik; setelah selesai, draf mengikuti batas yang baru.
  const dirender = klip?.status === "rendering";
  useEffect(() => {
    if (!dirender) return undefined;
    const t = setInterval(async () => {
      const k = await muat();
      if (k && k.status !== "rendering") {
        sinkronkanDraf(k);
      }
    }, 3000);
    return () => clearInterval(t);
  }, [dirender, muat, sinkronkanDraf]);

  // Render ulang yang lama tidak dilaporkan worker (> 60 detik): kemungkinan worker mati atau sibuk dengan pekerjaan lain.
  const [menungguLama, setMenungguLama] = useState(false);
  const sudahLapor = !!klip?.kemajuan;
  useEffect(() => {
    setMenungguLama(false);
    if (!dirender || sudahLapor) return undefined;
    const t = setTimeout(() => setMenungguLama(true), 60000);
    return () => clearTimeout(t);
  }, [dirender, sudahLapor]);

  // Gulir daftar kata ke kata pertama di dalam klip (sekali, saat transkrip pertama tiba).
  const sudahAdaKata = kataSemua.length > 0;
  useEffect(() => {
    const pertama = daftarKataRef.current?.querySelector("[data-dalam='1']");
    if (pertama) pertama.scrollIntoView({ block: "center" });
  }, [sudahAdaKata]);

  const galatBatas = pesanBatasKlip(mulai, akhir, proyek?.duration_sec ?? null);
  const batasBerubah = klip ? Math.abs(mulai - klip.start_sec) > 0.01 || Math.abs(akhir - klip.end_sec) > 0.01 : false;
  const teksBerubah = klip ? judul !== klip.title || caption !== klip.caption || uraiHashtag(tagar).join(" ") !== klip.hashtags.join(" ") : false;
  const akhirTranskrip = kataSemua.length ? kataSemua[kataSemua.length - 1].e : 0;
  const posisiKepala = Math.min(akhir, Math.max(mulai, posisi ?? mulai));
  const segmen = useMemo(() => segmenKlip(mulai, akhir, titikBagi, potong), [mulai, akhir, titikBagi, potong]);
  const segmenPilih = segmenDi(segmen, posisiKepala);
  const potongKlip = useMemo(() => selangDalam(potong, mulai, akhir), [potong, mulai, akhir]);
  const dibuangSemua = useMemo(() => totalJeda(potongKlip), [potongKlip]);
  const potongBerubah = JSON.stringify(potong) !== JSON.stringify(klip?.potong ?? []);
  const total = Math.max(proyek?.duration_sec ?? 0, akhirTranskrip, (klip?.end_sec ?? 0) + MARGIN);

  const aturDiam = useCallback((m, a) => {
    setMulai(m);
    setAkhir(a);
  }, []);

  // Pratinjau mengikuti batas: video di atas menampilkan bingkai tepat di posisi batas yang sedang diatur (seperti CapCut).
  const lihat = useCallback((t) => {
    setPosisi(Math.max(0, t));
    if (sumberHilang) return;
    tertunda.current = Math.max(0, t);
    setLihatSumber(true);
    cancelAnimationFrame(bingkai.current);
    bingkai.current = requestAnimationFrame(() => {
      const v = videoRef.current;
      if (v && v.dataset.sumber === "1" && v.readyState >= 1 && tertunda.current !== null) {
        v.pause();
        v.currentTime = tertunda.current;
        setKepala(tertunda.current);
      }
    });
  }, [sumberHilang]);

  const atur = useCallback((m, a) => {
    if (Math.abs(m - mulai) > 1e-6) lihat(m);
    else if (Math.abs(a - akhir) > 1e-6) lihat(Math.max(m, a - 0.04));
    aturDiam(m, a);
  }, [mulai, akhir, lihat, aturDiam]);

  function putarBatas() {
    const v = videoRef.current;
    if (!lihatSumber || !v || v.readyState < 1) {
      lihat(mulai);
      return;
    }
    v.currentTime = mulai;
    v.play();
  }

  function klikKata(k) {
    if (!dirender) lihat(k.s);
  }



  // Urungkan/Ulangi: tiap perubahan potongan disimpan sebagai satu langkah.
  const ubahPotongan = useCallback((potongBaru, titikBaru) => {
    setRiwayat((r) => ({ lalu: [...r.lalu.slice(-49), { potong, titik: titikBagi }], depan: [] }));
    setPotong(potongBaru);
    setTitikBagi(titikBaru);
  }, [potong, titikBagi]);

  const urung = useCallback(() => {
    setRiwayat((r) => {
      if (!r.lalu.length) return r;
      const langkah = r.lalu[r.lalu.length - 1];
      setPotong(langkah.potong);
      setTitikBagi(langkah.titik);
      return { lalu: r.lalu.slice(0, -1), depan: [...r.depan, { potong, titik: titikBagi }] };
    });
  }, [potong, titikBagi]);

  const ulang = useCallback(() => {
    setRiwayat((r) => {
      if (!r.depan.length) return r;
      const langkah = r.depan[r.depan.length - 1];
      setPotong(langkah.potong);
      setTitikBagi(langkah.titik);
      return { lalu: [...r.lalu, { potong, titik: titikBagi }], depan: r.depan.slice(0, -1) };
    });
  }, [potong, titikBagi]);

  const bisaBagi = !dirender && posisiKepala > mulai + 0.05 && posisiKepala < akhir - 0.05 && !segmen.some((x) => Math.abs(x.a - posisiKepala) < 0.05);

  const bagi = useCallback(() => {
    if (!bisaBagi) return;
    ubahPotongan(potong, [...titikBagi, Math.round(posisiKepala * 100) / 100].sort((x, y) => x - y));
  }, [bisaBagi, ubahPotongan, potong, titikBagi, posisiKepala]);

  const hapusSegmen = useCallback(() => {
    if (dirender || !segmenPilih) return;
    ubahPotongan(segmenPilih.hapus ? kurangiSelang(potong, segmenPilih.a, segmenPilih.b) : tambahSelang(potong, segmenPilih.a, segmenPilih.b), titikBagi);
  }, [dirender, segmenPilih, ubahPotongan, potong, titikBagi]);

  const jedaOtomatis = useCallback(() => {
    const selang = hitungJeda(kataSemua, mulai, akhir, 0.6);
    if (!selang.length) {
      setPesan("Tidak ada jeda yang cukup panjang di klip ini.");
      return;
    }
    setPesan("");
    ubahPotongan(selang.reduce((hasil, [a, b]) => tambahSelang(hasil, a, b), potong), titikBagi);
  }, [kataSemua, mulai, akhir, ubahPotongan, potong, titikBagi]);

  // Pintasan keyboard seperti CapCut (tidak aktif saat mengetik di kolom isian).
  useEffect(() => {
    function tekan(e) {
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z")) {
        e.preventDefault();
        if (e.shiftKey) ulang();
        else urung();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === "y" || e.key === "Y")) {
        e.preventDefault();
        ulang();
      } else if (e.ctrlKey || e.metaKey || e.altKey) {
        return;
      } else if (e.key === "s" || e.key === "S") {
        e.preventDefault();
        bagi();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        hapusSegmen();
      }
    }
    window.addEventListener("keydown", tekan);
    return () => window.removeEventListener("keydown", tekan);
  }, [bagi, hapusSegmen, urung, ulang]);

  async function renderUlang() {
    if (galatBatas || !(batasBerubah || potongBerubah || klip.subtitle_perlu_render)) return;
    setHasil(null);
    setSibuk(true);
    setPesan("");
    try {
      if (potongBerubah) setKlip(await simpanPotong(id, idKlip, potong));
      setKlip(await renderUlangKlip(id, idKlip, Math.round(mulai * 100) / 100, Math.round(akhir * 100) / 100));
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setPesan(e.message);
    } finally {
      setSibuk(false);
    }
  }

  async function batalRender() {
    setSibuk(true);
    setPesan("");
    dibatalkanSendiri.current = true;
    try {
      const k = await batalRenderKlip(id, idKlip);
      setKlip(k);
      sinkronkanDraf(k);
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setPesan(e.message);
    } finally {
      setSibuk(false);
    }
  }

  async function simpanTeks(e) {
    e.preventDefault();
    setSibuk(true);
    setPesan("");
    try {
      const baru = await ubahKlip(id, idKlip, { title: judul, caption, hashtags: uraiHashtag(tagar) });
      setKlip((lama) => ({ ...lama, ...baru }));
      setTagar(baru.hashtags.join(" "));
    } catch (err) {
      if (err.status === 401) padaKeluar();
      else setPesan(err.message);
    } finally {
      setSibuk(false);
    }
  }

  // Transkrip di panel kiri: kata di sekitar batas klip yang sedang diatur (ikut bergerak saat pegangan digeser).
  const kataTampil = useMemo(() => kataSemua.filter((k) => k.e >= mulai - MARGIN && k.s <= akhir + MARGIN), [kataSemua, mulai, akhir]);

  if (proyek === null) return <TidakAda judul="Klip tidak ditemukan" isi="Klip ini tidak ada atau bukan milikmu." />;
  if (proyek === undefined || !klip)
    return galat ? <p role="alert" className="p-8 text-sm text-red-300">{galat}</p> : <p className="p-8 text-sm text-zinc-500">Memuat editor...</p>;

  const panjangBaru = akhir - mulai;
  const rasioKlip = (() => {
    const m = /^(\d+):(\d+)$/.exec(klip?.ratio ?? "");
    return m ? `${m[1]} / ${m[2]}` : "9 / 16";
  })();

  return (
    <div className="min-h-screen lg:h-screen flex flex-col bg-zinc-950 text-zinc-200">
      <header className="shrink-0 h-14 px-4 flex items-center gap-3 border-b border-zinc-800 bg-zinc-950">
        <a href={alamat.detail(id)} className="text-zinc-400 hover:text-white" aria-label="Kembali ke hasil proyek">
          <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
        </a>
        <h1 className="font-semibold text-white truncate flex-1 min-w-0">{klip.title || "Klip tanpa judul"}</h1>
        {dirender && <span className="text-xs rounded-full bg-violet-500/15 text-violet-300 px-3 py-1">Merender ulang...</span>}
        <TombolTema />
        {klip.ada_video && (
          <a href={alamatVideo(id, idKlip, true, klip.size_bytes)} className="rounded-xl bg-white text-zinc-900 text-sm font-medium px-4 py-2 hover:bg-zinc-200">
            Unduh
          </a>
        )}
      </header>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)_340px]">
        {/* Transkrip */}
        <section className="min-h-0 flex flex-col border-b lg:border-b-0 lg:border-r border-zinc-800 max-h-80 lg:max-h-none">
          <div className="shrink-0 p-3 border-b border-zinc-800 space-y-2">
            <p className="text-sm font-medium text-white">Transkrip</p>

            <p className="text-[11px] text-zinc-500">Klik sebuah kata untuk memindahkan garis putih ke kata itu, lalu tekan Bagi atau Hapus di bawah. Kata yang terang ada di dalam klip.</p>
          </div>
          <div ref={daftarKataRef} className="flex-1 min-h-0 overflow-y-auto p-3 text-[15px] leading-8">
            {kataTampil.length === 0 ? (
              <p className="text-sm text-zinc-500">Transkrip tidak tersedia untuk proyek ini. Batas tetap bisa diatur lewat waktu atau timeline.</p>
            ) : (
              kataTampil.map((k, i) => {
                const dalam = k.e > mulai && k.s < akhir;
                const jeda = jedaSebelum(kataTampil, i);
                return (
                  <span key={i}>
                    {jeda > 0 && <span className="mx-1 text-[11px] rounded bg-zinc-800 text-zinc-400 px-1.5 py-0.5">{jeda.toFixed(1)}s</span>}
                    <button
                      type="button"
                      data-dalam={dalam ? "1" : "0"}
                      onClick={() => klikKata(k)}
                      className={`rounded px-0.5 mr-1 text-left ${dalam ? "text-white hover:bg-violet-500/30" : "text-zinc-600 hover:text-zinc-300"} ${
                        Math.abs(k.s - mulai) < 0.02 || Math.abs(k.e - akhir) < 0.02 ? "bg-violet-500/40" : ""
                      }`}
                    >
                      {k.w}
                    </button>
                  </span>
                );
              })
            )}
          </div>
        </section>

        {/* Pratinjau */}
        <section className="min-h-0 flex flex-col items-center gap-3 p-4 bg-zinc-900/30 overflow-hidden">
          <div className="flex-1 min-h-0 w-full flex justify-center">
            <div className="relative bg-black rounded-2xl overflow-hidden border border-zinc-800 max-w-full max-h-full h-full" style={{ aspectRatio: rasioKlip }}>
              {lihatSumber ? (
                <video
                  key="sumber"
                  ref={videoRef}
                  data-sumber="1"
                  controls
                  muted={false}
                  preload="auto"
                  src={alamatSumber(id)}
                  className="w-full h-full object-contain"
                  onLoadedMetadata={(ev) => {
                    if (tertunda.current !== null) ev.currentTarget.currentTime = tertunda.current;
                  }}
                  onTimeUpdate={(ev) => {
                    const v = ev.currentTarget;
                    setKepala(v.currentTime);
                    const lubang = !v.paused && potong.find(([a, b]) => v.currentTime >= a && v.currentTime < b);
                    if (lubang) v.currentTime = lubang[1];                  // pratinjau melompati bagian yang dihapus
                    if (!v.paused && v.currentTime >= akhir) {
                      v.pause();
                      v.currentTime = mulai;
                    }
                  }}
                  onError={() => {
                    setSumberHilang(true);
                    setLihatSumber(false);
                  }}
                />
              ) : klip.ada_video ? (
                <video
                  key={klip.size_bytes}
                  ref={videoRef}
                  data-sumber="0"
                  controls
                  preload="metadata"
                  src={alamatVideo(id, idKlip, false, klip.size_bytes)}
                  className="w-full h-full object-contain"
                  onTimeUpdate={(ev) => setKepala(klip.start_sec + ev.currentTarget.currentTime)}
                  onPause={() => setKepala(null)}
                />
              ) : (
                <p className="absolute inset-0 grid place-items-center text-xs text-zinc-400 p-6 text-center">Video belum tersedia</p>
              )}
              {dirender && (
                <div className="absolute inset-x-0 bottom-0 bg-black/70 text-center text-xs text-violet-200 py-2">Sedang dirender ulang... video lama masih bisa diputar</div>
              )}
            </div>
          </div>
          <div className="shrink-0 flex flex-wrap items-center justify-center gap-3">
            <div className="inline-flex rounded-lg border border-zinc-700 overflow-hidden text-xs" role="group" aria-label="Sumber pratinjau">
              <button type="button" aria-pressed={!lihatSumber} onClick={() => setLihatSumber(false)}
                className={`px-3 py-1.5 ${!lihatSumber ? "bg-violet-600 text-white" : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800"}`}>
                Klip hasil
              </button>
              <button type="button" aria-pressed={lihatSumber} disabled={sumberHilang || dirender} onClick={() => lihat(mulai)}
                className={`px-3 py-1.5 disabled:opacity-50 ${lihatSumber ? "bg-violet-600 text-white" : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800"}`}>
                Video asli
              </button>
            </div>
            {lihatSumber && <button type="button" onClick={putarBatas} className={`${TOMBOL} !py-1.5 text-xs`}>Putar klip baru</button>}
          </div>
          <p className="shrink-0 text-[11px] text-zinc-500 text-center">
            {sumberHilang
              ? "Video asli tidak tersedia di server, jadi hanya klip hasil yang bisa diputar."
              : lihatSumber ? "Pratinjau dari video asli (tanpa pelacakan wajah); hasil render tetap memakai kamera otomatis."
                : `Klip ${formatDurasi(klip.start_sec)} - ${formatDurasi(klip.end_sec)} · ${formatDurasi(klip.duration_sec)} · rasio ${klip.ratio}`}
          </p>
        </section>

        {/* Panel pengaturan */}
        <aside className="min-h-0 flex flex-col border-t lg:border-t-0 lg:border-l border-zinc-800">
          <div role="tablist" className="shrink-0 grid grid-cols-3 border-b border-zinc-800 text-xs sm:text-sm">
            {[["subtitle", "Subtitle"], ["teks", "Teks"], ["skor", "Skor"]].map(([k, nama]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`relative py-3 border-b-2 ${tab === k ? "border-violet-400 text-white" : "border-transparent text-zinc-500 hover:text-zinc-300"}`}>
                {nama}
                {k === "subtitle" && klip.subtitle_perlu_render && !dirender && (
                  <span className="inline-block ml-1.5 align-middle w-2 h-2 rounded-full bg-amber-400" title="Ada pengaturan yang belum dirender ke video" />
                )}
              </button>
            ))}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
            {galat && <Galat>{galat}</Galat>}
            {pesan && <Galat>{pesan}</Galat>}
            {klip.status === "failed" && <Galat>Render ulang terakhir gagal{klip.galat_render ? `: ${klip.galat_render}` : ""}. Video lama masih tersedia; coba Render ulang lagi.</Galat>}

            {tab === "subtitle" && (
              <PanelSubtitle id={id} idKlip={idKlip} klip={klip} kata={kataSemua} mulai={mulai} akhir={akhir} galatBatas={galatBatas}
                dirender={dirender} padaKlip={(k) => setKlip((lama) => ({ ...lama, ...k }))} padaMuat={muat} padaKeluar={padaKeluar} />
            )}

            {tab === "teks" && (
              <form onSubmit={simpanTeks} className="space-y-3">
                <label className="block text-xs text-zinc-400">
                  Judul
                  <input value={judul} maxLength={200} onChange={(e) => setJudul(e.target.value)} className={KOLOM} />
                </label>
                <label className="block text-xs text-zinc-400">
                  Caption <span className="text-zinc-600">({caption.length}/500)</span>
                  <textarea value={caption} maxLength={500} rows={7} onChange={(e) => setCaption(e.target.value)} className={KOLOM} />
                </label>
                <label className="block text-xs text-zinc-400">
                  Hashtag (pisahkan dengan spasi)
                  <input value={tagar} onChange={(e) => setTagar(e.target.value)} placeholder="#seru #podcast" className={KOLOM} />
                </label>
                <button type="submit" disabled={sibuk || !teksBerubah} className={UTAMA}>{sibuk ? "Menyimpan..." : "Simpan teks"}</button>
              </form>
            )}

            {tab === "skor" && (
              <div className="space-y-4">
                <div className="text-center rounded-xl bg-zinc-900 border border-zinc-800 py-4">
                  <div className={`text-4xl font-bold ${WARNA_SKOR[tingkatSkor(klip.score)]}`}>{Math.round(klip.score)}</div>
                  <div className="text-xs text-zinc-500 mt-1">skor akhir 0-100</div>
                </div>
                <dl className="space-y-3">
                  {KOMPONEN.map(([kunci, nama]) => (
                    <div key={kunci}>
                      <dt className="flex justify-between text-xs text-zinc-400"><span>{nama}</span><span>{persen(klip[kunci])}%</span></dt>
                      <dd className="h-1.5 bg-zinc-800 rounded-full overflow-hidden mt-1"><div className="h-full bg-violet-500" style={{ width: `${persen(klip[kunci])}%` }} /></dd>
                    </div>
                  ))}
                </dl>
                <p className="text-[11px] text-zinc-500">Skor dihitung dari batas klip semula dan tidak berubah saat batas diatur ulang.</p>
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* Status render + alat potong + timeline */}
      <footer className="shrink-0 border-t border-zinc-800 bg-zinc-950 px-4 pt-3 pb-3">
        <StatusRender id={id} idKlip={idKlip} klip={klip} dirender={dirender} kemajuan={klip.kemajuan} menungguLama={menungguLama}
          hasil={hasil} tutupHasil={() => setHasil(null)} putarHasil={() => { setLihatSumber(false); setHasil(null); }}
          infoKlip={`Klip baru ${formatWaktuDetail(mulai)} - ${formatWaktuDetail(akhir)} · ${formatDurasi(panjangBaru)}${dibuangSemua > 0 ? `, jadi ${formatDurasi(Math.max(0, panjangBaru - dibuangSemua))} setelah dipotong` : ""}`}
          perluRender={batasBerubah || potongBerubah || !!klip.subtitle_perlu_render} alasanMati={galatBatas} render={renderUlang} batalRender={batalRender} sibuk={sibuk} />
        <GarisWaktu idKlip={idKlip} total={total} kata={kataSemua} mulai={mulai} akhir={akhir} kepala={posisi} padaUbah={atur} potong={potong} titikBagi={titikBagi.filter((t) => t > mulai && t < akhir)} segmenPilih={segmenPilih}
          padaKlik={lihat} padaTampak={(a, b) => pastikanKata(a - 30, b + 30)} nonaktif={dirender}
          alat={<BilahPotong bisaUrung={riwayat.lalu.length > 0} bisaUlang={riwayat.depan.length > 0} urung={urung} ulang={ulang} bagi={bagi} bisaBagi={bisaBagi}
            hapus={hapusSegmen} segmenPilih={segmenPilih} jedaOtomatis={jedaOtomatis} adaKata={kataSemua.length > 0} nonaktif={dirender} />} />
      </footer>
    </div>
  );
}
