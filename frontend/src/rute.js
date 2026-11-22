// Perutean sederhana berbasis hash (#/proyek), tanpa pustaka tambahan. Murni, jadi bisa dites.

/** "#/proyek/12" -> { nama: "detail", id: 12 }. Alamat tak dikenal -> { nama: "tidakada" }. */
export function uraiRute(hash) {
  const jalur = String(hash ?? "").replace(/^#/, "").split("?")[0].replace(/\/+$/, "");
  if (jalur === "" || jalur === "/") return { nama: "beranda" };
  if (jalur === "/proyek") return { nama: "proyek" };
  const m = /^\/proyek\/(\d{1,9})$/.exec(jalur);
  if (m) return { nama: "detail", id: Number(m[1]) };
  return { nama: "tidakada" };
}

export const alamat = {
  beranda: () => "#/",
  proyek: () => "#/proyek",
  detail: (id) => `#/proyek/${id}`,
};
