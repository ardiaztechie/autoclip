import { test } from "node:test";
import assert from "node:assert/strict";
import { formatUkuran, formatWaktu, labelStatus, masihBerjalan, pesanGalat, tingkatSkor, uraiHashtag, uraiWaktu, urutkanKlip, pesanBatasKlip, formatWaktuDetail, rapatkanKeKata, jedaSebelum, posisiPersen, perkiraanSisa, dibatalkan, labelProyek, kataDalamRentang, daftarKoreksi, petaKoreksi } from "./format.js";

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
  assert.deepEqual(PILIHAN_PANJANG.map((x) => x[0]), ["otomatis", "pendek", "sedang", "panjang", "sangat_panjang", "ekstra_panjang"]);
});

test("urutkanKlip: menurut menit atau skor, tanpa mengubah daftar asli", () => {
  const asal = [
    { id: 1, start_sec: 90, score: 60 },
    { id: 2, start_sec: 10, score: 80 },
    { id: 3, start_sec: 50, score: 80 },
  ];
  assert.deepEqual(urutkanKlip(asal).map((k) => k.id), [2, 3, 1]);
  assert.deepEqual(urutkanKlip(asal, "skor").map((k) => k.id), [2, 3, 1]);   // skor sama -> menit lebih awal dulu
  assert.deepEqual(urutkanKlip([{ id: 1, start_sec: 5, score: 10 }, { id: 2, start_sec: 9, score: 90 }], "skor").map((k) => k.id), [2, 1]);
  assert.deepEqual(asal.map((k) => k.id), [1, 2, 3]);
});

test("tingkatSkor", () => {
  assert.equal(tingkatSkor(85), "tinggi");
  assert.equal(tingkatSkor(70), "tinggi");
  assert.equal(tingkatSkor(55), "sedang");
  assert.equal(tingkatSkor(20), "rendah");
  assert.equal(tingkatSkor(NaN), "rendah");
});

test("uraiHashtag: dipisah spasi/koma, diawali #, tanpa kembar", () => {
  assert.deepEqual(uraiHashtag("seru, #lucu  baru ##seru"), ["#seru", "#lucu", "#baru"]);
  assert.deepEqual(uraiHashtag(""), []);
  assert.deepEqual(uraiHashtag(null), []);
  assert.equal(uraiHashtag(Array.from({ length: 50 }, (_, i) => `t${i}`).join(" ")).length, 30);
});

test("uraiWaktu", () => {
  assert.equal(uraiWaktu("1:15"), 75);
  assert.equal(uraiWaktu(" 0:05 "), 5);
  assert.equal(uraiWaktu("1:02:03"), 3723);
  assert.equal(uraiWaktu("75.5"), 75.5);
  assert.equal(uraiWaktu("1:75"), null);
  assert.equal(uraiWaktu("abc"), null);
  assert.equal(uraiWaktu(""), null);
  assert.equal(uraiWaktu("1:2:3:4"), null);
  assert.equal(uraiWaktu("-5"), null);
});

test("pesanBatasKlip sejalan dengan backend", () => {
  assert.equal(pesanBatasKlip(10, 40, 600), "");
  assert.match(pesanBatasKlip(null, 40), /menit:detik/);
  assert.match(pesanBatasKlip(40, 10), /setelah/);
  assert.match(pesanBatasKlip(10, 12), /minimal 5/);
  assert.match(pesanBatasKlip(0, 301), /maksimal 300/);
  assert.match(pesanBatasKlip(590, 601, 600), /melewati durasi/);
  assert.equal(pesanBatasKlip(590, 600.4, 600), "");
  assert.equal(pesanBatasKlip(10, 40, null), "");
});

test("formatWaktuDetail", () => {
  assert.equal(formatWaktuDetail(75.34), "1:15.3");
  assert.equal(formatWaktuDetail(5), "0:05.0");
  assert.equal(formatWaktuDetail(59.96), "1:00.0");
  assert.equal(formatWaktuDetail(-1), "");
  assert.equal(uraiWaktu(formatWaktuDetail(75.3)), 75.3);
});

test("rapatkanKeKata: mulai ke awal kata, akhir ke akhir kata", () => {
  const kata = [{ w: "a", s: 1, e: 1.5 }, { w: "b", s: 2, e: 2.6 }, { w: "c", s: 4, e: 4.4 }];
  assert.equal(rapatkanKeKata(kata, 1.9, "mulai"), 2);
  assert.equal(rapatkanKeKata(kata, 3.7, "mulai"), 4);
  assert.equal(rapatkanKeKata(kata, 2.5, "akhir"), 2.6);
  assert.equal(rapatkanKeKata(kata, 0, "akhir"), 1.5);
  assert.equal(rapatkanKeKata([], 3.3, "mulai"), 3.3);
});

test("jedaSebelum dan posisiPersen", () => {
  const kata = [{ s: 0, e: 1 }, { s: 1.2, e: 2 }, { s: 3.5, e: 4 }];
  assert.equal(jedaSebelum(kata, 0), 0);
  assert.equal(jedaSebelum(kata, 1), 0);
  assert.equal(jedaSebelum(kata, 2), 1.5);
  assert.equal(jedaSebelum(kata, 9), 0);
  assert.equal(posisiPersen(15, 10, 20), 50);
  assert.equal(posisiPersen(5, 10, 20), 0);
  assert.equal(posisiPersen(99, 10, 20), 100);
  assert.equal(posisiPersen(1, 5, 5), 0);
});

test("perkiraanSisa: butuh data cukup, lalu menghitung kasar", () => {
  assert.equal(perkiraanSisa(5, 100), null);
  assert.equal(perkiraanSisa(50, 10), null);
  assert.equal(perkiraanSisa(NaN, 100), null);
  assert.equal(perkiraanSisa(100, 100), null);
  assert.equal(perkiraanSisa(50, 120), "sekitar 2 menit lagi");
  assert.equal(perkiraanSisa(90, 100), "kurang dari 1 menit lagi");
});

test("dibatalkan dan labelProyek", () => {
  assert.equal(dibatalkan({ status: "failed", stage: "Dibatalkan" }), true);
  assert.equal(dibatalkan({ status: "failed", stage: "Gagal" }), false);
  assert.equal(dibatalkan({ status: "processing", stage: "Dibatalkan" }), false);
  assert.equal(labelProyek({ status: "failed", stage: "Dibatalkan" }), "Dibatalkan");
  assert.equal(labelProyek({ status: "failed", stage: "Gagal" }), "Gagal");
  assert.equal(labelProyek({ status: "done", stage: "Selesai" }), "Selesai");
});

test("kataDalamRentang, daftarKoreksi, petaKoreksi", () => {
  const kata = [{ w: "a", s: 1, e: 1.4 }, { w: "b", s: 2, e: 2.4 }, { w: "c", s: 3, e: 3.4 }];
  assert.deepEqual(kataDalamRentang(kata, 1.5, 3.4).map((k) => k.w), ["b", "c"]);
  assert.deepEqual(kataDalamRentang(null, 0, 9), []);
  assert.deepEqual(daftarKoreksi({ "2": "Bee", "3": " c ", "9": "x" }, kata), [{ s: 2, w: "Bee" }]);   // "c" sama -> tidak dikirim
  assert.deepEqual(daftarKoreksi({ "1": "" }, kata), [{ s: 1, w: "" }]);                                // kosong = dibuang
  assert.deepEqual(petaKoreksi([{ s: 2.5, w: "x" }]), { "2.5": "x" });
  assert.deepEqual(petaKoreksi(undefined), {});
});

test("hitungJeda sama dengan core.jeda.hitung_buang untuk kasus yang sama", async () => {
  const { hitungJeda, totalJeda } = await import("./format.js");
  const kata = [{ w: "a", s: 1.0, e: 1.5 }, { w: "b", s: 3.0, e: 3.4 }, { w: "c", s: 3.5, e: 4.0 }];
  assert.deepEqual(hitungJeda(kata, 0, 6, 0.6), [[0, 0.9], [1.6, 2.9], [4.1, 6]]);       // nilai ini sama dengan tests/test_jeda.py
  assert.deepEqual(hitungJeda(kata, 0, 6, 2.5), []);
  assert.deepEqual(hitungJeda([], 0, 6), []);
  assert.deepEqual(hitungJeda([{ w: "x", s: 1, e: 1.1 }, { w: "y", s: 1.15, e: 1.3 }], 1, 1.3, 0), []);
  assert.ok(Math.abs(totalJeda([[0, 0.9], [1.6, 2.9]]) - 2.2) < 1e-9);
});

test("potongan manual: tambah, kurangi, segmen seperti CapCut", async () => {
  const { tambahSelang, kurangiSelang, segmenKlip, segmenDi, selangDalam } = await import("./format.js");
  assert.deepEqual(tambahSelang([[1, 2], [5, 6]], 1.5, 5), [[1, 6]]);
  assert.deepEqual(kurangiSelang([[1, 6]], 2, 3), [[1, 2], [3, 6]]);
  assert.deepEqual(kurangiSelang([[1, 2]], 5, 6), [[1, 2]]);
  assert.deepEqual(selangDalam([[0, 3], [8, 9]], 2, 5), [[2, 3]]);
  const s = segmenKlip(10, 20, [14, 30], [[16, 18]]);
  assert.deepEqual(s.map((x) => [x.a, x.b, x.hapus]), [[10, 14, false], [14, 16, false], [16, 18, true], [18, 20, false]]);
  assert.equal(segmenDi(s, 17).hapus, true);
  assert.equal(segmenDi(s, 20).a, 18);
  assert.equal(segmenDi(s, 25), null);
});
