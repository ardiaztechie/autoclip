import { useState } from "react";
import { bacaTema, simpanTema } from "../tema.js";

/** Tombol ganti mode terang/gelap. */
export default function TombolTema({ className = "" }) {
  const [tema, setTema] = useState(bacaTema);
  const terang = tema === "terang";
  function ganti() {
    const baru = terang ? "gelap" : "terang";
    simpanTema(baru);
    setTema(baru);
  }
  return (
    <button type="button" onClick={ganti} aria-label={terang ? "Ganti ke mode gelap" : "Ganti ke mode terang"} title={terang ? "Mode gelap" : "Mode terang"}
      className={`grid place-items-center w-9 h-9 rounded-lg border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors ${className}`}>
      {terang ? (
        <svg viewBox="0 0 24 24" className="w-4.5 h-4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" className="w-4.5 h-4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
      )}
    </button>
  );
}
