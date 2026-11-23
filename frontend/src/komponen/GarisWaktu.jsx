import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { formatDurasi, rapatkanKeKata } from "../format.js";

const LANGKAH_TANDA = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800];
const PX_MIN = 0.5;       // px per detik terkecil (seluruh video panjang muat di layar)
const PX_MAKS = 120;      // px per detik terbesar
const PX_AWAL = 14;
const LEBAR_PEGANGAN = 12;

/**
 * Garis waktu SELURUH video: bisa digeser kiri-kanan (gulir, atau seret ruang kosong dengan tombol geser), diperbesar/dikecilkan,
 * balok kata, area klip dengan dua pegangan (merapat ke batas kata), dan pita jeda yang akan dibuang.
 * padaTampak(dari, sampai) dipanggil saat bagian yang terlihat berubah, supaya induk memuat transkrip bagian itu.
 */
export default function GarisWaktu({ total, kata, mulai, akhir, kepala, padaUbah, padaKlik, padaTampak, jedaBuang = [], potong = [], titikBagi = [], segmenPilih = null, nonaktif, idKlip, alat = null }) {
  const gulir = useRef(null);
  const dalam = useRef(null);
  const [px, setPx] = useState(PX_AWAL);
  const [tampak, setTampak] = useState({ a: 0, b: 60 });
  const [seret, setSeret] = useState(null); // "mulai" | "akhir" | null
  const sudahPusat = useRef(null);
  const [geserKepala, setGeserKepala] = useState(false);
  const padaTampakRef = useRef(padaTampak);       // disimpan di ref agar fungsi induk yang berubah tiap render tidak memicu pengulangan
  padaTampakRef.current = padaTampak;

  const lebarTotal = Math.max(total * px, 1);

  const hitungTampak = useCallback(() => {
    const el = gulir.current;
    if (!el) return;
    const a = el.scrollLeft / px;
    const b = (el.scrollLeft + el.clientWidth) / px;
    setTampak((lama) => (Math.abs(lama.a - a) < 0.05 && Math.abs(lama.b - b) < 0.05 ? lama : { a, b }));
    padaTampakRef.current?.(a, b);
  }, [px]);

  // Awal (dan saat klip berganti): gulirkan agar klip ada di tengah.
  useLayoutEffect(() => {
    const el = gulir.current;
    if (!el || !(total > 0) || sudahPusat.current === idKlip) return;
    sudahPusat.current = idKlip;
    const tengah = ((mulai + akhir) / 2) * px;
    el.scrollLeft = Math.max(0, tengah - el.clientWidth / 2);
    hitungTampak();
  }, [total, idKlip, mulai, akhir, px, hitungTampak]);

  useEffect(() => {
    hitungTampak();
  }, [hitungTampak]);

  function zoom(faktor) {
    const el = gulir.current;
    const tengah = el ? (el.scrollLeft + el.clientWidth / 2) / px : 0;
    const baru = Math.min(PX_MAKS, Math.max(PX_MIN, px * faktor));
    setPx(baru);
    requestAnimationFrame(() => {
      if (gulir.current) gulir.current.scrollLeft = Math.max(0, tengah * baru - gulir.current.clientWidth / 2);
    });
  }

  function fokusKe(a, b) {
    const el = gulir.current;
    if (!el) return;
    const baru = Math.min(PX_MAKS, Math.max(PX_MIN, el.clientWidth / Math.max(b - a, 1)));
    setPx(baru);
    requestAnimationFrame(() => {
      if (gulir.current) gulir.current.scrollLeft = Math.max(0, a * baru);
    });
  }

  const pasKlip = () => fokusKe(Math.max(0, mulai - 8), akhir + 8);
  const semua = () => fokusKe(0, total);

  function waktuDari(e) {
    const kotak = dalam.current.getBoundingClientRect();
    return Math.min(total, Math.max(0, (e.clientX - kotak.left) / px));
  }

  function gerak(e) {
    if (!seret || nonaktif) return;
    const el = gulir.current;
    const tepi = el.getBoundingClientRect();
    if (e.clientX > tepi.right - 40) el.scrollLeft += 18;                 // dekat tepi: gulir otomatis
    else if (e.clientX < tepi.left + 40) el.scrollLeft -= 18;
    const t = rapatkanKeKata(kata, waktuDari(e), seret);
    if (seret === "mulai") padaUbah(Math.min(t, akhir - 0.5), akhir);
    else padaUbah(mulai, Math.max(t, mulai + 0.5));
  }

  const pegangan = (jenis, t) => (
    <button
      type="button"
      aria-label={jenis === "mulai" ? "Geser batas mulai" : "Geser batas selesai"}
      disabled={nonaktif}
      onPointerDown={(e) => {
        e.stopPropagation();
        e.currentTarget.setPointerCapture(e.pointerId);
        setSeret(jenis);
      }}
      onPointerMove={gerak}
      onPointerUp={() => setSeret(null)}
      className="absolute top-0 bottom-0 rounded-md bg-violet-400 hover:bg-violet-300 cursor-ew-resize touch-none disabled:cursor-not-allowed disabled:opacity-50 z-10"
      style={{ left: t * px - LEBAR_PEGANGAN / 2, width: LEBAR_PEGANGAN }}
    />
  );

  // Tanda waktu: langkah terkecil yang jaraknya >= 70 px.
  const langkah = LANGKAH_TANDA.find((l) => l * px >= 70) ?? LANGKAH_TANDA[LANGKAH_TANDA.length - 1];
  const tanda = [];
  for (let t = Math.max(0, Math.floor((tampak.a - langkah) / langkah) * langkah); t <= Math.min(total, tampak.b + langkah); t += langkah) tanda.push(t);
  const kataTampak = kata.filter((k) => k.e >= tampak.a - 2 && k.s <= tampak.b + 2);
  const tombol = "rounded-lg border border-zinc-700 text-zinc-300 text-xs px-2.5 py-1 hover:bg-zinc-800 transition-colors";

  return (
    <div className="select-none">
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1.5 mb-2">
        {alat}
        <div className="ml-auto flex items-center gap-1.5" role="group" aria-label="Perbesar garis waktu">
          <button type="button" className={tombol} onClick={() => zoom(1 / 1.6)} aria-label="Perkecil garis waktu">−</button>
          <button type="button" className={tombol} onClick={() => zoom(1.6)} aria-label="Perbesar garis waktu">+</button>
          <button type="button" className={tombol} onClick={pasKlip}>Pas klip</button>
          <button type="button" className={tombol} onClick={semua}>Seluruh video</button>
        </div>
      </div>
      <div ref={gulir} onScroll={hitungTampak} className="overflow-x-auto overflow-y-hidden rounded-lg border border-zinc-800 bg-zinc-900" data-garis-waktu>
        <div ref={dalam} style={{ width: lebarTotal }} className="relative">
          <div className="relative h-5 text-[10px] text-zinc-500">
            {tanda.map((t) => (
              <span key={t} className="absolute top-0.5 border-l border-zinc-700 pl-1" style={{ left: t * px }}>
                {formatDurasi(t)}
              </span>
            ))}
          </div>
          <div
            className="relative h-16 cursor-pointer"
            onPointerDown={(e) => {
              if (e.target === e.currentTarget || e.target.dataset.kata || e.target.dataset.pita) {
                e.currentTarget.setPointerCapture(e.pointerId);
                setGeserKepala(true);
                padaKlik?.(waktuDari(e));
              }
            }}
            onPointerMove={(e) => {
              if (!geserKepala) return;
              const el = gulir.current;
              const tepi = el.getBoundingClientRect();
              if (e.clientX > tepi.right - 30) el.scrollLeft += 14;
              else if (e.clientX < tepi.left + 30) el.scrollLeft -= 14;
              padaKlik?.(waktuDari(e));
            }}
            onPointerUp={() => setGeserKepala(false)}
          >
            {kataTampak.map((k) => {
              const di = k.e > mulai && k.s < akhir;
              return (
                <span
                  key={k.s}
                  data-kata="1"
                  className={`absolute top-3 bottom-3 rounded-sm ${di ? "bg-violet-500/70" : "bg-zinc-700"}`}
                  style={{ left: k.s * px, width: Math.max(2, (k.e - k.s) * px) }}
                />
              );
            })}
            <div className="absolute top-0 bottom-0 border-y-2 border-violet-400 bg-violet-400/10 pointer-events-none"
              style={{ left: mulai * px, width: Math.max((akhir - mulai) * px, 0) }} />
            {segmenPilih && !nonaktif && (
              <div className="absolute top-0 bottom-0 border-2 border-white/80 pointer-events-none rounded-sm"
                style={{ left: segmenPilih.a * px, width: Math.max(2, (segmenPilih.b - segmenPilih.a) * px) }} />
            )}
            {potong.map(([a, b]) => (
              <div key={`p${a}`} data-pita="1" title={`Dipotong ${(b - a).toFixed(1)} dtk`}
                className="absolute top-0 bottom-0 border-x border-zinc-400 bg-zinc-950/80"
                style={{ left: a * px, width: Math.max(2, (b - a) * px), backgroundImage: "repeating-linear-gradient(45deg, rgba(239,68,68,.35) 0 4px, transparent 4px 9px)" }} />
            ))}
            {titikBagi.map((t) => (
              <div key={`b${t}`} className="absolute top-0 bottom-0 w-0.5 bg-amber-300 pointer-events-none" style={{ left: t * px - 1 }} />
            ))}
            {jedaBuang.map(([a, b]) => (
              <div key={a} title={`Jeda dibuang ${(b - a).toFixed(1)} dtk`} className="absolute top-0 bottom-0 bg-red-500/40 border-x border-red-400 pointer-events-none"
                style={{ left: a * px, width: Math.max(2, (b - a) * px) }} />
            ))}
            {kepala !== null && kepala >= 0 && kepala <= total && (
              <div className="absolute -top-5 bottom-0 w-0.5 bg-white pointer-events-none z-20" style={{ left: kepala * px - 1 }}>
                <span className="absolute -top-0.5 -left-1.5 w-3.5 h-3 bg-white" style={{ clipPath: "polygon(0 0,100% 0,50% 100%)" }} />
              </div>
            )}
            {pegangan("mulai", mulai)}
            {pegangan("akhir", akhir)}
          </div>
        </div>
      </div>
    </div>
  );
}
