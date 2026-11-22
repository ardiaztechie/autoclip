// Fungsi kecil untuk tampilan. Murni (tanpa React), jadi mudah dites dengan `npm test`.

/** Pesan galat dari backend: detail bisa teks (HTTPException) atau daftar (galat validasi 422). */
export function pesanGalat(detail, kodeStatus) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const bagian = detail.map((d) => {
      const kolom = Array.isArray(d?.loc) ? d.loc.filter((x) => x !== "body").join(".") : "";
      const isi = typeof d?.msg === "string" ? d.msg : "isian tidak valid";
      return kolom ? `${kolom}: ${isi}` : isi;
    });
    return bagian.join("; ");
  }
  return kodeStatus ? `Terjadi kesalahan (kode ${kodeStatus})` : "Terjadi kesalahan";
}

const LABEL_STATUS = { queued: "Antre", processing: "Diproses", done: "Selesai", failed: "Gagal" };

export function labelStatus(status) {
  return LABEL_STATUS[status] ?? status;
}

/** Proyek yang masih berjalan: halaman perlu memuat ulang daftar secara berkala. */
export function masihBerjalan(proyek) {
  return proyek.status === "queued" || proyek.status === "processing";
}

export function formatUkuran(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** "2026-11-22 14:20:05" (waktu server, UTC) -> "22 Nov 2026 21.20" (waktu setempat). */
export function formatWaktu(teks) {
  if (!teks) return "";
  const d = new Date(String(teks).replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return String(teks);
  return d.toLocaleString("id-ID", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** 75.4 -> "1:15". Dibulatkan ke detik terdekat. */
export function formatDurasi(detik) {
  if (!Number.isFinite(detik) || detik < 0) return "";
  const total = Math.round(detik);
  const j = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const d = total % 60;
  const dd = String(d).padStart(2, "0");
  return j > 0 ? `${j}:${String(m).padStart(2, "0")}:${dd}` : `${m}:${dd}`;
}

/** (10, 40) -> "0:10 - 0:40" */
export function formatRentang(mulai, akhir) {
  return `${formatDurasi(mulai)} - ${formatDurasi(akhir)}`;
}

/** Komponen skor 0-1 -> persen bulat untuk lebar batang; di luar rentang dibatasi. */
export function persen(nilai) {
  if (!Number.isFinite(nilai)) return 0;
  return Math.round(Math.min(1, Math.max(0, nilai)) * 100);
}

/** Hashtag yang belum tertulis di caption (worker biasanya sudah menaruhnya di akhir caption). */
export function hashtagTersisa(klip) {
  const caption = klip.caption ?? "";
  return (klip.hashtags ?? []).filter((h) => !caption.includes(h));
}

/** Caption siap tempel: caption lalu hashtag (bila caption belum memuatnya). */
export function teksSalin(klip) {
  return [(klip.caption ?? "").trim(), hashtagTersisa(klip).join(" ")].filter(Boolean).join("\n\n");
}

// Pilihan jumlah dan durasi klip. Nilainya harus sama dengan yang dikenali backend (core/pipeline.py).
export const PILIHAN_KEPADATAN = [
  ["jarang", "Jarang (sekitar 1 klip tiap 2 menit video)"],
  ["sedang", "Sedang (sekitar 1 klip tiap 75 detik)"],
  ["rapat", "Rapat (sekitar 1 klip tiap 50 detik)"],
];
export const PILIHAN_PANJANG = [
  ["otomatis", "Otomatis (sekitar 30-80 detik)"],
  ["pendek", "Pendek (15-30 detik)"],
  ["sedang", "Sedang (30-60 detik)"],
  ["panjang", "Panjang (60-90 detik)"],
];

const NAMA_KEPADATAN = { jarang: "jarang", sedang: "sedang", rapat: "rapat" };
const NAMA_PANJANG = { otomatis: "otomatis", pendek: "pendek", sedang: "sedang", panjang: "panjang" };

/** "8 klip" bila jumlahnya dipilih pasti, selain itu "jumlah otomatis (rapat)". */
export function labelJumlah(proyek) {
  if (Number.isInteger(proyek.n_clips)) return `${proyek.n_clips} klip`;
  return `jumlah otomatis (${NAMA_KEPADATAN[proyek.clip_density] ?? "sedang"})`;
}

export function labelPanjang(proyek) {
  return `durasi ${NAMA_PANJANG[proyek.clip_length] ?? "otomatis"}`;
}
