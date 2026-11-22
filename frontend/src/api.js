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
export const daftarKlip = (id) => panggil(`/projects/${id}/clips`);
/** Alamat video klip untuk <video src> (cookie sesi ikut terkirim karena satu asal) dan untuk unduhan. */
export const alamatVideo = (idProyek, idKlip, unduh = false) =>
  `${DASAR}/projects/${idProyek}/clips/${idKlip}/video${unduh ? "?unduh=true" : ""}`;
