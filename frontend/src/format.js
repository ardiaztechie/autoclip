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

/** Proyek yang dibatalkan pengguna: di backend berstatus 'failed' dengan stage 'Dibatalkan'. */
export function dibatalkan(proyek) {
  return proyek.status === "failed" && proyek.stage === "Dibatalkan";
}

/** Label status untuk tampilan: 'Dibatalkan' bila dibatalkan, selain itu label status biasa. */
export function labelProyek(proyek) {
  return dibatalkan(proyek) ? "Dibatalkan" : labelStatus(proyek.status);
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

/** "1:15" -> 75, "1:02:03" -> 3723, "75.5" -> 75.5. Tidak valid -> null. */
export function uraiWaktu(teks) {
  const bagian = String(teks ?? "").trim().split(":");
  if (bagian.length < 1 || bagian.length > 3 || bagian.some((b) => !/^\d+(\.\d+)?$/.test(b.trim()))) return null;
  const angka = bagian.map((b) => Number(b));
  if (angka.length > 1 && angka.slice(1).some((n) => n >= 60)) return null;
  return angka.reduce((jumlah, n) => jumlah * 60 + n, 0);
}

// Batas atur-batas-klip: harus sama dengan backend (MIN_KLIP_DETIK / MAKS_KLIP_DETIK di backend/proyek.py).
export const MIN_KLIP_DETIK = 5;
export const MAKS_KLIP_DETIK = 300;

/** Pesan galat bila batas klip tidak boleh dipakai, "" bila boleh. durasiVideo boleh null. */
export function pesanBatasKlip(mulai, akhir, durasiVideo = null) {
  if (mulai === null || akhir === null) return "Isi waktu dengan format menit:detik, misalnya 1:15";
  if (akhir <= mulai) return "Waktu akhir harus setelah waktu mulai";
  const panjang = akhir - mulai;
  if (panjang < MIN_KLIP_DETIK) return `Klip minimal ${MIN_KLIP_DETIK} detik`;
  if (panjang > MAKS_KLIP_DETIK) return `Klip maksimal ${MAKS_KLIP_DETIK} detik`;
  if (durasiVideo != null && akhir > durasiVideo + 0.5) return `Waktu akhir melewati durasi video (${formatDurasi(durasiVideo)})`;
  return "";
}

/** 75.34 -> "1:15.3" (satu desimal, untuk editor). */
export function formatWaktuDetail(detik) {
  if (!Number.isFinite(detik) || detik < 0) return "";
  const dibulatkan = Math.round(detik * 10) / 10;
  const m = Math.floor(dibulatkan / 60);
  const d = dibulatkan - m * 60;
  return `${m}:${d.toFixed(1).padStart(4, "0")}`;
}

/** Waktu t dirapatkan ke batas kata terdekat: jenis "mulai" -> awal kata, "akhir" -> akhir kata. Tanpa kata -> t. */
export function rapatkanKeKata(kata, t, jenis) {
  let terbaik = t;
  let selisih = Infinity;
  for (const k of kata ?? []) {
    const kandidat = jenis === "mulai" ? k.s : k.e;
    const d = Math.abs(kandidat - t);
    if (d < selisih) {
      selisih = d;
      terbaik = kandidat;
    }
  }
  return terbaik;
}

/** Jeda (detik) sebelum kata ke-i bila >= minimal, selain itu 0. */
export function jedaSebelum(kata, i, minimal = 0.8) {
  if (i <= 0 || i >= kata.length) return 0;
  const jeda = kata[i].s - kata[i - 1].e;
  return jeda >= minimal ? jeda : 0;
}

/** Posisi t pada sumbu [dari, sampai] sebagai persen 0-100 (dibatasi). */
export function posisiPersen(t, dari, sampai) {
  if (!(sampai > dari)) return 0;
  return Math.min(100, Math.max(0, ((t - dari) / (sampai - dari)) * 100));
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

/** Urutan daftar klip untuk tampilan: "menit" = menurut menit video (bawaan), "skor" = skor tertinggi dulu. Tidak mengubah daftar asli. */
export function urutkanKlip(daftar, mode = "menit") {
  const salinan = [...daftar];
  if (mode === "skor") return salinan.sort((a, b) => b.score - a.score || a.start_sec - b.start_sec);
  return salinan.sort((a, b) => a.start_sec - b.start_sec || a.id - b.id);
}

/** Skor 0-100 -> tingkat untuk warna lencana saja ("tinggi" >= 70, "sedang" >= 50). Batas ini hanya tampilan, bukan rumus skor. */
export function tingkatSkor(skor) {
  if (!Number.isFinite(skor)) return "rendah";
  return skor >= 70 ? "tinggi" : skor >= 50 ? "sedang" : "rendah";
}

/** Hashtag yang belum tertulis di caption (worker biasanya sudah menaruhnya di akhir caption). */
export function hashtagTersisa(klip) {
  const caption = klip.caption ?? "";
  return (klip.hashtags ?? []).filter((h) => !caption.includes(h));
}

/** Teks isian hashtag ("seru, #lucu  baru") -> daftar rapi ["#seru", "#lucu", "#baru"]: dipisah spasi/koma, diawali #, tanpa kembar, maks 30. */
export function uraiHashtag(teks) {
  const hasil = [];
  for (const bagian of String(teks ?? "").split(/[\s,]+/)) {
    const t = bagian.replace(/#+/g, "").slice(0, 49);
    if (t && !hasil.includes("#" + t)) hasil.push("#" + t);
  }
  return hasil.slice(0, 30);
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
  ["sangat_panjang", "Sangat panjang (90 detik - 2 menit)"],
  ["ekstra_panjang", "Ekstra panjang (2 - 3 menit)"],
];

const NAMA_KEPADATAN = { jarang: "jarang", sedang: "sedang", rapat: "rapat" };
const NAMA_PANJANG = { otomatis: "otomatis", pendek: "pendek", sedang: "sedang", panjang: "panjang", sangat_panjang: "sangat panjang", ekstra_panjang: "ekstra panjang" };

/** "8 klip" bila jumlahnya dipilih pasti, selain itu "jumlah otomatis (rapat)". */
export function labelJumlah(proyek) {
  if (Number.isInteger(proyek.n_clips)) return `${proyek.n_clips} klip`;
  return `jumlah otomatis (${NAMA_KEPADATAN[proyek.clip_density] ?? "sedang"})`;
}

export function labelPanjang(proyek) {
  return `durasi ${NAMA_PANJANG[proyek.clip_length] ?? "otomatis"}`;
}

/** Perkiraan sisa waktu render dari persen dan detik yang sudah berjalan. Kasar (bobot tahap hanya tebakan);
 *  null bila datanya belum cukup (persen < 8 atau baru berjalan < 15 detik). */
export function perkiraanSisa(persen, berjalanDetik) {
  if (!Number.isFinite(persen) || !Number.isFinite(berjalanDetik) || persen < 8 || persen >= 100 || berjalanDetik < 15) return null;
  const sisa = (berjalanDetik * (100 - persen)) / persen;
  if (sisa < 60) return "kurang dari 1 menit lagi";
  return `sekitar ${Math.round(sisa / 60)} menit lagi`;
}

export const GAYA_SUBTITLE = [
  ["klasik", "Klasik"],
  ["kuning", "Kuning"],
  ["kotak", "Kotak"],
  ["sorot", "Sorot kata"],
  ["minimal", "Minimal"],
];
export const ANIMASI_SUBTITLE = [["tanpa", "Tanpa"], ["muncul", "Muncul (pop)"], ["pudar", "Memudar"]];
export const POSISI_SUBTITLE = [["atas", "Atas"], ["tengah", "Tengah"], ["bawah", "Bawah"]];
export const UKURAN_SUBTITLE = [["kecil", "Kecil"], ["sedang", "Sedang"], ["besar", "Besar"]];

/** Kata transkrip yang seluruhnya berada di dalam [mulai, akhir] (detik video asli). */
export function kataDalamRentang(kata, mulai, akhir) {
  return (kata ?? []).filter((k) => k.s >= mulai - 0.001 && k.e <= akhir + 0.001);
}

/** Daftar koreksi untuk dikirim ke API dari peta {waktuMulai: teks} dan kata asli; hanya yang berbeda dari kata asli. */
export function daftarKoreksi(peta, kata) {
  const hasil = [];
  for (const k of kata ?? []) {
    const baru = peta[String(k.s)];
    if (baru !== undefined && baru.trim() !== k.w.trim()) hasil.push({ s: k.s, w: baru.trim() });
  }
  return hasil;
}

/** Peta {waktuMulai: teks} dari daftar koreksi API ([{s, w}]). */
export function petaKoreksi(koreksi) {
  const peta = {};
  for (const k of koreksi ?? []) peta[String(k.s)] = k.w;
  return peta;
}

export const JEDA_BAWAAN = { aktif: false, ambang: 0.6 };
export const AMBANG_JEDA = { min: 0.3, maks: 3.0 };      // harus sama dengan core/jeda.py
const SISA_JEDA = 0.2;

/**
 * Selang [a, b] yang akan dibuang dari klip [mulai, akhir] bila jeda >= ambang dipotong. Sama dengan core.jeda.hitung_buang
 * (yang dipakai render sebenarnya), supaya pita merah di timeline = bagian yang benar-benar hilang (selain pembulatan ke frame).
 */
export function hitungJeda(kata, mulai, akhir, ambang = JEDA_BAWAAN.ambang) {
  const batas = Math.max(Number(ambang) || 0, SISA_JEDA + 0.05);
  const dalam = (kata ?? []).filter((k) => k.e > mulai && k.s < akhir).sort((x, y) => x.s - y.s);
  if (!dalam.length) return [];
  const bulat = (x) => Math.round(x * 1000) / 1000;
  const hasil = [];
  const lubang = (a, b, awal, ujung) => {
    if (b - a >= batas) {
      const x = a + awal;
      const y = b - ujung;
      if (y - x > 0.02) hasil.push([bulat(Math.max(x, mulai)), bulat(Math.min(y, akhir))]);
    }
  };
  lubang(mulai, dalam[0].s, 0, SISA_JEDA / 2);
  for (let i = 1; i < dalam.length; i += 1) lubang(dalam[i - 1].e, dalam[i].s, SISA_JEDA / 2, SISA_JEDA / 2);
  lubang(dalam[dalam.length - 1].e, akhir, SISA_JEDA / 2, 0);
  return hasil;
}

/** Jumlah detik yang dibuang oleh daftar selang. */
export const totalJeda = (selang) => selang.reduce((jumlah, [a, b]) => jumlah + (b - a), 0);

/** Menambah selang [a, b] ke daftar selang (urut, tanpa tumpang tindih). */
export function tambahSelang(daftar, a, b) {
  const semua = [...daftar, [a, b]].sort((x, y) => x[0] - y[0]);
  const hasil = [];
  for (const [p, q] of semua) {
    if (hasil.length && p <= hasil[hasil.length - 1][1] + 1e-9) hasil[hasil.length - 1][1] = Math.max(hasil[hasil.length - 1][1], q);
    else hasil.push([p, q]);
  }
  return hasil;
}

/** Mengurangi selang [a, b] dari daftar selang (bagian yang dipulihkan). */
export function kurangiSelang(daftar, a, b) {
  const hasil = [];
  for (const [p, q] of daftar) {
    if (q <= a || p >= b) hasil.push([p, q]);
    else {
      if (p < a) hasil.push([p, a]);
      if (q > b) hasil.push([b, q]);
    }
  }
  return hasil;
}

/** Bagian daftar selang yang jatuh di dalam [mulai, akhir]. */
export const selangDalam = (daftar, mulai, akhir) =>
  daftar.map(([a, b]) => [Math.max(a, mulai), Math.min(b, akhir)]).filter(([a, b]) => b - a > 1e-9);

/**
 * Segmen klip seperti di CapCut: klip dibagi di titik bagi dan di tepi bagian yang sudah dihapus.
 * Hasil: [{a, b, hapus}] urut; hapus = segmen itu ada di dalam potongan.
 */
export function segmenKlip(mulai, akhir, titik, potong) {
  const batas = new Set([mulai, akhir]);
  for (const t of titik ?? []) if (t > mulai + 0.01 && t < akhir - 0.01) batas.add(t);
  for (const [a, b] of potong ?? []) for (const t of [a, b]) if (t > mulai + 0.01 && t < akhir - 0.01) batas.add(t);
  const urut = [...batas].sort((x, y) => x - y);
  const hasil = [];
  for (let i = 0; i + 1 < urut.length; i += 1) {
    const a = urut[i];
    const b = urut[i + 1];
    const tengah = (a + b) / 2;
    hasil.push({ a, b, hapus: (potong ?? []).some(([p, q]) => tengah >= p && tengah < q) });
  }
  return hasil;
}

/** Segmen yang memuat waktu t (atau null). */
export const segmenDi = (segmen, t) => segmen.find((s) => t >= s.a && t < s.b) ?? (segmen.length && Math.abs(t - segmen[segmen.length - 1].b) < 1e-6 ? segmen[segmen.length - 1] : null);

/** Menyatukan dua daftar selang. */
export const gabungSelang = (x, y) => y.reduce((hasil, [a, b]) => tambahSelang(hasil, a, b), x.map(([a, b]) => [a, b]));
