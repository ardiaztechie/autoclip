import { useEffect, useMemo, useRef, useState } from "react";
import { renderUlangKlip, simpanSubtitle, subtitleSemua } from "../api.js";
import { ANIMASI_SUBTITLE, GAYA_SUBTITLE, POSISI_SUBTITLE, UKURAN_SUBTITLE, daftarKoreksi, kataDalamRentang, petaKoreksi } from "../format.js";

const TOMBOL = "rounded-xl border border-zinc-700 text-zinc-200 text-sm px-3 py-2 hover:bg-zinc-800 transition-colors disabled:opacity-50";
const UTAMA = "rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium px-4 py-2 transition-colors disabled:opacity-50";
const BAWAAN = { gaya: "klasik", posisi: "bawah", ukuran: "sedang", animasi: "tanpa", aktif: true };

const BAYANGAN = "0 0 2px #000, 0 0 2px #000, 1px 1px 2px #000";

/** Contoh teks tiap gaya (hanya gambaran kasar dengan CSS; hasil sebenarnya dibakar FFmpeg saat render ulang). */
function Contoh({ gaya }) {
  const dasar = { fontWeight: 800, textShadow: BAYANGAN };
  if (gaya === "kuning") return <span style={{ ...dasar, color: "#ffeb00" }}>Contoh teks</span>;
  if (gaya === "kotak") return <span style={{ ...dasar, color: "#fff", background: "rgba(0,0,0,.75)", padding: "1px 6px", textShadow: "none" }}>Contoh teks</span>;
  if (gaya === "sorot")
    return (
      <span style={{ ...dasar, color: "#fff" }}>
        <span style={{ color: "#ffd700" }}>Contoh</span> teks
      </span>
    );
  if (gaya === "minimal") return <span style={{ color: "#fff", fontWeight: 400, textShadow: "1px 1px 1px #000" }}>Contoh teks</span>;
  return <span style={{ ...dasar, color: "#fff" }}>Contoh teks</span>;
}

function Pilihan({ nama, daftar, nilai, ubah, mati }) {
  return (
    <div>
      <p className="text-xs text-zinc-400 mb-1.5">{nama}</p>
      <div className="inline-flex rounded-lg border border-zinc-700 overflow-hidden text-xs" role="group" aria-label={nama}>
        {daftar.map(([id, teks]) => (
          <button key={id} type="button" disabled={mati} aria-pressed={nilai === id} onClick={() => ubah(id)}
            className={`px-3 py-1.5 disabled:opacity-50 ${nilai === id ? "bg-violet-600 text-white" : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800"}`}>
            {teks}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Tab Subtitle di editor: gaya, posisi, ukuran, nyala/mati, dan koreksi kata. Perubahan baru terlihat di video setelah
 * render ulang (subtitle dibakar ke video). `kata` = transkrip di sekitar klip; mulai/akhir = batas klip yang sedang diatur.
 */
export default function PanelSubtitle({ id, idKlip, klip, kata, mulai, akhir, galatBatas, dirender, padaKlip, padaMuat, padaKeluar }) {
  const [pilihan, setPilihan] = useState(klip.subtitle ?? BAWAAN);
  const [koreksi, setKoreksi] = useState(petaKoreksi(klip.koreksi));
  const [sibuk, setSibuk] = useState(false);
  const [pesan, setPesan] = useState("");
  const [yakinSemua, setYakinSemua] = useState(false);
  const [diantre, setDiantre] = useState(null);
  const [workerLama, setWorkerLama] = useState(false);
  const statusLalu = useRef(klip.status);

  // Render baru saja selesai tetapi gaya tersimpan tetap dianggap belum ada di video: worker kemungkinan masih versi lama.
  useEffect(() => {
    if (statusLalu.current === "rendering" && klip.status === "done") setWorkerLama(!!klip.subtitle_perlu_render);
    if (klip.status === "rendering") setWorkerLama(false);
    statusLalu.current = klip.status;
  }, [klip.status, klip.subtitle_perlu_render]);

  // Ikuti data server saat klip berganti atau selesai dirender (bukan tiap polling, supaya ketikan tidak terhapus).
  useEffect(() => {
    setPilihan(klip.subtitle ?? BAWAAN);
    setKoreksi(petaKoreksi(klip.koreksi));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [klip.id, klip.status]);

  const kataKlip = useMemo(() => kataDalamRentang(kata, mulai, akhir), [kata, mulai, akhir]);
  const daftar = useMemo(() => daftarKoreksi(koreksi, kataKlip), [koreksi, kataKlip]);
  const asli = klip.subtitle ?? BAWAAN;
  const berubah =
    ["gaya", "posisi", "ukuran", "animasi", "aktif"].some((k) => pilihan[k] !== asli[k]) ||
    JSON.stringify(daftar.map((d) => [d.s, d.w])) !== JSON.stringify(petaKoreksiKeDaftar(klip.koreksi, kataKlip));
  const mati = sibuk || dirender;
  const perluRender = berubah || !!klip.subtitle_perlu_render;      // gaya tersimpan tetapi belum dibakar ke video juga dihitung

  function ubah(kunci, nilai) {
    setPilihan((p) => ({ ...p, [kunci]: nilai }));
    setYakinSemua(false);
    setDiantre(null);
  }

  async function jalankan(kerja) {
    setSibuk(true);
    setPesan("");
    try {
      await kerja();
    } catch (e) {
      if (e.status === 401) padaKeluar();
      else setPesan(e.message);
    } finally {
      setSibuk(false);
    }
  }

  const simpan = () => simpanSubtitle(id, idKlip, { ...pilihan, koreksi: daftar });

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-400">
        Pilih gaya subtitle, lalu <b className="text-zinc-200">render ulang</b>: subtitle dibakar ke video, jadi perubahan baru terlihat setelah render selesai.
      </p>
      {workerLama && !dirender && (
        <p role="alert" className="text-sm text-red-200 bg-red-500/10 border border-red-500/30 rounded-xl px-3 py-2">
          Render selesai, tetapi gaya subtitle tidak terpasang. Hampir pasti <b>worker Anda masih versi lama</b>: matikan jendela
          worker (<code>Ctrl+C</code>), nyalakan lagi dengan <code>python -m backend.worker</code>, lalu render ulang.
          Worker yang benar mencetak baris <code>Fitur render ulang: ... gaya subtitle ...</code> saat dinyalakan.
        </p>
      )}
      {klip.subtitle_perlu_render && !dirender && !berubah && !workerLama && (
        <p role="status" className="text-sm text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-xl px-3 py-2">
          Gaya ini sudah tersimpan tetapi <b>belum ada di video</b>. Tekan <b>Render ulang</b> di bawah, lalu tunggu sampai selesai.
        </p>
      )}
      {pesan && <p role="alert" className="text-sm text-red-300 bg-red-500/10 rounded-xl px-3 py-2">{pesan}</p>}

      <label className="flex items-center gap-2 text-sm text-zinc-200">
        <input type="checkbox" checked={pilihan.aktif} disabled={mati} onChange={(e) => ubah("aktif", e.target.checked)} className="accent-violet-500" />
        Tampilkan subtitle
      </label>

      {pilihan.aktif && (
        <>
          <div className="grid grid-cols-2 gap-2" role="group" aria-label="Gaya subtitle">
            {GAYA_SUBTITLE.map(([g, nama]) => (
              <button key={g} type="button" disabled={mati} aria-pressed={pilihan.gaya === g} onClick={() => ubah("gaya", g)}
                className={`rounded-xl border p-2 text-center disabled:opacity-50 bg-gradient-to-b from-zinc-700 to-zinc-800 ${pilihan.gaya === g ? "border-violet-400 ring-1 ring-violet-400" : "border-zinc-700 hover:border-zinc-500"}`}>
                <div className="text-sm leading-6"><Contoh gaya={g} /></div>
                <div className="text-[11px] text-zinc-300 mt-1">{nama}</div>
              </button>
            ))}
          </div>
          <Pilihan nama="Posisi" daftar={POSISI_SUBTITLE} nilai={pilihan.posisi} ubah={(v) => ubah("posisi", v)} mati={mati} />
          <Pilihan nama="Ukuran" daftar={UKURAN_SUBTITLE} nilai={pilihan.ukuran} ubah={(v) => ubah("ukuran", v)} mati={mati} />
          <Pilihan nama="Animasi teks" daftar={ANIMASI_SUBTITLE} nilai={pilihan.animasi} ubah={(v) => ubah("animasi", v)} mati={mati} />
        </>
      )}

      <div>
        <p className="text-xs text-zinc-400 mb-1.5">Perbaiki kata subtitle (kosongkan kata untuk membuangnya)</p>
        {kataKlip.length === 0 ? (
          <p className="text-xs text-zinc-500">Transkrip untuk rentang ini tidak tersedia.</p>
        ) : (
          <div className="flex flex-wrap gap-1 max-h-48 overflow-y-auto rounded-xl border border-zinc-800 p-2">
            {kataKlip.map((k) => {
              const nilai = koreksi[String(k.s)] ?? k.w;
              const diubah = nilai.trim() !== k.w.trim();
              return (
                <input key={k.s} value={nilai} disabled={mati} aria-label={`Kata pada detik ${k.s}`}
                  onChange={(e) => setKoreksi((p) => ({ ...p, [String(k.s)]: e.target.value }))}
                  size={Math.max(2, nilai.length)}
                  className={`rounded-md bg-zinc-950 border px-1.5 py-0.5 text-xs text-zinc-100 focus:outline-none focus:ring-1 focus:ring-violet-500 ${diubah ? "border-amber-400/60" : "border-zinc-800"}`} />
              );
            })}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={mati || !perluRender || !!galatBatas} className={UTAMA}
          onClick={() => jalankan(async () => {
            if (berubah) await simpan();
            padaKlip(await renderUlangKlip(id, idKlip, Math.round(mulai * 100) / 100, Math.round(akhir * 100) / 100));
          })}>
          {sibuk ? "Mengirim..." : berubah ? "Simpan & render ulang" : "Render ulang"}
        </button>
        <button type="button" disabled={mati || !berubah} className={TOMBOL}
          onClick={() => jalankan(async () => padaKlip(await simpan()))}>
          Simpan saja
        </button>
      </div>
      {galatBatas && <p className="text-xs text-red-300">{galatBatas}</p>}

      <div className="border-t border-zinc-800 pt-3 space-y-2">
        <p className="text-xs text-zinc-400">Pakai gaya, posisi, ukuran, dan animasi ini untuk <b className="text-zinc-200">semua klip</b> proyek (koreksi kata tiap klip tidak berubah).</p>
        {!yakinSemua ? (
          <button type="button" disabled={mati} className={TOMBOL} onClick={() => setYakinSemua(true)}>Terapkan ke semua klip</button>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-amber-300">Semua klip akan dirender ulang satu per satu dan bisa lama. Lanjut?</span>
            <button type="button" disabled={mati} className={UTAMA}
              onClick={() => jalankan(async () => {
                const hasil = await subtitleSemua(id, { gaya: pilihan.gaya, posisi: pilihan.posisi, ukuran: pilihan.ukuran, animasi: pilihan.animasi, aktif: pilihan.aktif });
                setDiantre(hasil.diantre);
                setYakinSemua(false);
                await padaMuat();
              })}>
              Ya, render semua
            </button>
            <button type="button" className={TOMBOL} onClick={() => setYakinSemua(false)}>Batal</button>
          </div>
        )}
        {diantre !== null && <p className="text-xs text-emerald-300">{diantre} klip masuk antrean render ulang.</p>}
      </div>
    </div>
  );
}

/** Koreksi tersimpan di server dalam bentuk yang sama dengan daftarKoreksi (hanya kata di rentang yang sedang tampil). */
function petaKoreksiKeDaftar(koreksiServer, kataKlip) {
  return daftarKoreksi(petaKoreksi(koreksiServer), kataKlip).map((d) => [d.s, d.w]);
}
