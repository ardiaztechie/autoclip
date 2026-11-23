// Perutean sederhana berbasis hash (#/proyek), tanpa pustaka tambahan. Murni, jadi bisa dites.

/** "#/proyek/12" -> { nama: "detail", id: 12 }; "#/proyek/12/klip/5" -> { nama: "editor", id: 12, klip: 5 }. Alamat tak dikenal -> { nama: "tidakada" }. */
export function uraiRute(hash) {
  const jalur = String(hash ?? "").replace(/^#/, "").split("?")[0].replace(/\/+$/, "");
  if (jalur === "" || jalur === "/") return { nama: "beranda" };
  if (jalur === "/proyek") return { nama: "proyek" };
  if (jalur === "/masuk") return { nama: "masuk" };
  if (jalur === "/cms") return { nama: "cms" };
  if (jalur === "/landing") return { nama: "landing" };
  const m = /^\/proyek\/(\d{1,9})$/.exec(jalur);
  if (m) return { nama: "detail", id: Number(m[1]) };
  const e = /^\/proyek\/(\d{1,9})\/klip\/(\d{1,9})$/.exec(jalur);
  if (e) return { nama: "editor", id: Number(e[1]), klip: Number(e[2]) };
  return { nama: "tidakada" };
}

export const alamat = {
  beranda: () => "#/",
  masuk: () => "#/masuk",
  cms: () => "#/cms",
  landing: () => "#/landing",
  proyek: () => "#/proyek",
  detail: (id) => `#/proyek/${id}`,
  editor: (id, klip) => `#/proyek/${id}/klip/${klip}`,
};
