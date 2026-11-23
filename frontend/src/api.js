// Semua komunikasi dengan backend lewat sini. Alamat dasar /api diteruskan oleh Vite ke FastAPI (lihat vite.config.js).
import { pesanGalat } from "./format.js";

const DASAR = "/api";
const PESAN_TERPUTUS = "Tidak bisa menghubungi server. Pastikan backend (uvicorn) dan MySQL di XAMPP menyala.";

export class GalatApi extends Error {
  constructor(pesan, status) {
    super(pesan);
    this.status = status; // 0 = server tidak terjangkau
  }
}

async function bacaJson(respons) {
  try {
    return await respons.json();
  } catch {
    return null;
  }
}

async function panggil(jalur, opsi = {}) {
  let respons;
  try {
    respons = await fetch(DASAR + jalur, { credentials: "same-origin", ...opsi });
  } catch {
    throw new GalatApi(PESAN_TERPUTUS, 0);
  }
  const isi = await bacaJson(respons);
  if (!respons.ok) throw new GalatApi(pesanGalat(isi?.detail, respons.status), respons.status);
  return isi;
}

export const masuk = (email, password) =>
  panggil("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

export const keluar = () => panggil("/auth/logout", { method: "POST" });
export const saya = () => panggil("/auth/me");
export const daftarProyek = () => panggil("/projects");

/** Mengunggah video. Memakai XMLHttpRequest karena fetch tidak punya kemajuan unggahan.
 *  padaKemajuan(persen) dipanggil selama pengiriman. */
export function unggahProyek(berkas, opsi, padaKemajuan) {
  return new Promise((selesai, gagal) => {
    const data = new FormData();
    data.append("file", berkas);
    for (const [kunci, nilai] of Object.entries(opsi)) data.append(kunci, String(nilai));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", DASAR + "/projects");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) padaKemajuan(Math.round((e.loaded * 100) / e.total));
    };
    xhr.onload = () => {
      let isi = null;
      try {
        isi = JSON.parse(xhr.responseText);
      } catch {
        /* balasan bukan JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) selesai(isi);
      else gagal(new GalatApi(pesanGalat(isi?.detail, xhr.status), xhr.status));
    };
    xhr.onerror = () => gagal(new GalatApi(PESAN_TERPUTUS, 0));
    xhr.send(data);
  });
}

/** Membuat proyek dari tautan YouTube (tanpa unggahan; video diunduh oleh worker). */
export function buatProyekDariTautan(url, opsi) {
  const data = new FormData();
  data.append("url", url.trim());
  for (const [kunci, nilai] of Object.entries(opsi)) data.append(kunci, String(nilai));
  return panggil("/projects", { method: "POST", body: data });
}

export const detailProyek = (id) => panggil(`/projects/${id}`);
/** Membatalkan pemrosesan proyek yang antre/berjalan. Mengembalikan proyek yang sudah diperbarui. */
export const batalProyek = (id) => panggil(`/projects/${id}/batal`, { method: "POST" });
/** Kata transkrip proyek pada rentang waktu video asli [dari, sampai] (maks 900 detik per permintaan). */
export const kataRentang = (idProyek, dari, sampai) =>
  panggil(`/projects/${idProyek}/kata?dari=${encodeURIComponent(dari)}&sampai=${encodeURIComponent(sampai)}`);
export const daftarKlip = (id) => panggil(`/projects/${id}/clips`);
/** Mengubah judul, caption, dan hashtag satu klip (tanpa render ulang). Mengembalikan klip yang sudah diperbarui. */
export const ubahKlip = (idProyek, idKlip, isi) =>
  panggil(`/projects/${idProyek}/clips/${idKlip}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(isi),
  });
/** Kata transkrip di sekitar klip: { dari, sampai, kata: [{ w, s, e }] }. Dipakai editor. */
export const kataKlip = (idProyek, idKlip, margin = 30) => panggil(`/projects/${idProyek}/clips/${idKlip}/kata?margin=${margin}`);
/** Alamat video klip untuk <video src> (cookie sesi ikut terkirim karena satu asal) dan untuk unduhan. */
export const alamatVideo = (idProyek, idKlip, unduh = false, versi = null) => {
  const query = [unduh ? "unduh=true" : "", versi != null ? `v=${versi}` : ""].filter(Boolean).join("&");   // v = ukuran berkas: ganti saat dirender ulang
  return `${DASAR}/projects/${idProyek}/clips/${idKlip}/video${query ? "?" + query : ""}`;
};

/** Video asli proyek (untuk pratinjau batas klip di editor). */
export const alamatSumber = (idProyek) => `${DASAR}/projects/${idProyek}/source`;

/** Mengatur batas awal/akhir klip (detik video sumber) lalu merender ulang klip itu. Mengembalikan klip (status "rendering"). */
export const batalRenderKlip = (idProyek, idKlip) =>
  panggil(`/projects/${idProyek}/clips/${idKlip}/batal-render`, { method: "POST" });

export const renderUlangKlip = (idProyek, idKlip, mulai, akhir) =>
  panggil(`/projects/${idProyek}/clips/${idKlip}/render-ulang`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_sec: mulai, end_sec: akhir }),
  });

/** Menyimpan gaya subtitle (gaya, posisi, ukuran, aktif) dan koreksi kata satu klip. Tidak merender ulang. */
export const simpanSubtitle = (idProyek, idKlip, isi) =>
  panggil(`/projects/${idProyek}/clips/${idKlip}/subtitle`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(isi),
  });

/** Menyamakan gaya subtitle semua klip proyek dan merender ulang semuanya. Mengembalikan {diantre}. */
export const subtitleSemua = (idProyek, isi) =>
  panggil(`/projects/${idProyek}/clips/subtitle-semua`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(isi),
  });

/** Menyimpan pilihan potong jeda satu klip ({aktif, ambang} detik). Tidak merender ulang. */
export const simpanJeda = (idProyek, idKlip, isi) =>
  panggil(`/projects/${idProyek}/clips/${idKlip}/jeda`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(isi),
  });

/** Menyimpan potongan manual satu klip: daftar [awal, akhir] detik video asli yang dibuang. Tidak merender ulang. */
export const simpanPotong = (idProyek, idKlip, selang) =>
  panggil(`/projects/${idProyek}/clips/${idKlip}/potong`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selang }),
  });

/** Menghapus proyek beserta semua klip dan berkas videonya (tidak bisa dibatalkan). */
export const hapusProyek = (idProyek) => panggil(`/projects/${idProyek}`, { method: "DELETE" });
/** Menghapus satu klip beserta berkas videonya (tidak bisa dibatalkan). */
export const hapusKlip = (idProyek, idKlip) => panggil(`/projects/${idProyek}/clips/${idKlip}`, { method: "DELETE" });

/** Isi landing page untuk pengunjung (tanpa login): [{key, content}] hanya bagian yang ditampilkan. */
export const ambilLanding = () => panggil("/landing");
/** Admin: semua bagian landing beserta urutan, status tampil, dan isi bawaan. */
export const ambilLandingAdmin = () => panggil("/admin/landing");
/** Admin: menyimpan satu bagian landing ({content, is_visible, sort_order}). */
export const simpanLanding = (kunci, isi) =>
  panggil(`/admin/landing/${kunci}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(isi),
  });
