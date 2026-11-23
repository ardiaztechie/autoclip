// Tema terang/gelap: disimpan di localStorage, bawaan mengikuti pengaturan komputer. Kelas "terang" dipasang di <html>;
// css (index.css) membalik palet warna sehingga komponen tidak perlu diubah.
const KUNCI = "autoclip-tema";

/** "terang" | "gelap" dari nilai tersimpan; bila tidak ada/rusak -> mengikuti sistem. */
export function pilihTema(tersimpan, sistemTerang) {
  if (tersimpan === "terang" || tersimpan === "gelap") return tersimpan;
  return sistemTerang ? "terang" : "gelap";
}

export function bacaTema() {
  let tersimpan = null;
  try {
    tersimpan = localStorage.getItem(KUNCI);
  } catch {
    /* penyimpanan diblokir: abaikan */
  }
  const sistemTerang = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: light)").matches;
  return pilihTema(tersimpan, sistemTerang);
}

export function pasangTema(tema) {
  const terang = tema === "terang";
  document.documentElement.classList.toggle("terang", terang);
  document.documentElement.classList.toggle("dark", !terang);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", terang ? "#fafafa" : "#09090b");
}

export function simpanTema(tema) {
  try {
    localStorage.setItem(KUNCI, tema);
  } catch {
    /* abaikan */
  }
  pasangTema(tema);
}
