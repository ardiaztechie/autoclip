import { test } from "node:test";
import assert from "node:assert/strict";
import { formatUkuran, formatWaktu, labelStatus, masihBerjalan, pesanGalat } from "./format.js";

test("pesanGalat: teks, daftar validasi, dan cadangan", () => {
  assert.equal(pesanGalat("Email atau password salah", 401), "Email atau password salah");
  assert.equal(pesanGalat([{ loc: ["body", "n_clips"], msg: "terlalu besar" }], 422), "n_clips: terlalu besar");
  assert.equal(pesanGalat([{ loc: ["body", "a"], msg: "x" }, { msg: "y" }], 422), "a: x; y");
  assert.equal(pesanGalat(undefined, 500), "Terjadi kesalahan (kode 500)");
  assert.equal(pesanGalat("   ", 500), "Terjadi kesalahan (kode 500)");
  assert.equal(pesanGalat(null), "Terjadi kesalahan");
  assert.equal(pesanGalat([{ loc: "bukan-daftar" }]), "isian tidak valid");
});

test("labelStatus dan masihBerjalan", () => {
  assert.equal(labelStatus("queued"), "Antre");
  assert.equal(labelStatus("processing"), "Diproses");
  assert.equal(labelStatus("done"), "Selesai");
  assert.equal(labelStatus("failed"), "Gagal");
  assert.equal(labelStatus("aneh"), "aneh");
  assert.equal(masihBerjalan({ status: "queued" }), true);
  assert.equal(masihBerjalan({ status: "processing" }), true);
  assert.equal(masihBerjalan({ status: "done" }), false);
  assert.equal(masihBerjalan({ status: "failed" }), false);
});

test("formatUkuran", () => {
  assert.equal(formatUkuran(500), "1 KB");
  assert.equal(formatUkuran(2048), "2 KB");
  assert.equal(formatUkuran(5 * 1024 * 1024), "5.0 MB");
  assert.equal(formatUkuran(1.5 * 1024 * 1024 * 1024), "1.50 GB");
  assert.equal(formatUkuran(-1), "");
  assert.equal(formatUkuran(NaN), "");
});

test("formatWaktu: waktu server dianggap UTC", () => {
  const hasil = formatWaktu("2026-11-22 14:20:05");
  assert.match(hasil, /2026/);
  assert.equal(formatWaktu(null), "");
  assert.equal(formatWaktu("bukan tanggal"), "bukan tanggal");
});

import { PILIHAN_KEPADATAN, PILIHAN_PANJANG, formatDurasi, formatRentang, hashtagTersisa, labelJumlah, labelPanjang, persen, teksSalin } from "./format.js";

test("formatDurasi dan formatRentang", () => {
  assert.equal(formatDurasi(0), "0:00");
  assert.equal(formatDurasi(9.4), "0:09");
  assert.equal(formatDurasi(75.6), "1:16");
  assert.equal(formatDurasi(3600), "1:00:00");
  assert.equal(formatDurasi(3725), "1:02:05");
  assert.equal(formatDurasi(-1), "");
  assert.equal(formatDurasi(NaN), "");
  assert.equal(formatDurasi(null), "");
  assert.equal(formatRentang(10, 40), "0:10 - 0:40");
});

test("persen membatasi 0-100", () => {
  assert.equal(persen(0.456), 46);
  assert.equal(persen(1.7), 100);
  assert.equal(persen(-0.2), 0);
  assert.equal(persen(NaN), 0);
  assert.equal(persen(undefined), 0);
});

test("teksSalin: caption + hashtag tanpa dobel", () => {
  assert.equal(teksSalin({ caption: "Halo", hashtags: ["#a", "#b"] }), "Halo\n\n#a #b");
  assert.equal(teksSalin({ caption: "Halo\n\n#a #b", hashtags: ["#a", "#b"] }), "Halo\n\n#a #b");
  assert.equal(teksSalin({ caption: "Halo", hashtags: ["#a", "#b"] }).includes("#a #b"), true);
  assert.equal(teksSalin({ caption: "", hashtags: ["#a"] }), "#a");
  assert.equal(teksSalin({}), "");
});

test("hashtagTersisa: hanya yang belum ada di caption", () => {
  assert.deepEqual(hashtagTersisa({ caption: "Halo\n\n#a #b", hashtags: ["#a", "#b"] }), []);
  assert.deepEqual(hashtagTersisa({ caption: "Halo #a", hashtags: ["#a", "#b"] }), ["#b"]);
  assert.deepEqual(hashtagTersisa({ caption: "Halo", hashtags: ["#a"] }), ["#a"]);
  assert.deepEqual(hashtagTersisa({}), []);
});

test("labelJumlah dan labelPanjang", () => {
  assert.equal(labelJumlah({ n_clips: 5, clip_density: "rapat" }), "5 klip");
  assert.equal(labelJumlah({ n_clips: null, clip_density: "rapat" }), "jumlah otomatis (rapat)");
  assert.equal(labelJumlah({ n_clips: null }), "jumlah otomatis (sedang)");
  assert.equal(labelJumlah({ n_clips: null, clip_density: "aneh" }), "jumlah otomatis (sedang)");
  assert.equal(labelPanjang({ clip_length: "pendek" }), "durasi pendek");
  assert.equal(labelPanjang({}), "durasi otomatis");
});

test("pilihan jumlah/durasi sama dengan nilai yang dikenal backend", () => {
  assert.deepEqual(PILIHAN_KEPADATAN.map((x) => x[0]), ["jarang", "sedang", "rapat"]);
  assert.deepEqual(PILIHAN_PANJANG.map((x) => x[0]), ["otomatis", "pendek", "sedang", "panjang"]);
});
