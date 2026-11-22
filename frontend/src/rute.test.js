import { test } from "node:test";
import assert from "node:assert/strict";
import { alamat, uraiRute } from "./rute.js";

test("uraiRute: halaman dikenal", () => {
  assert.deepEqual(uraiRute(""), { nama: "beranda" });
  assert.deepEqual(uraiRute("#/"), { nama: "beranda" });
  assert.deepEqual(uraiRute("#"), { nama: "beranda" });
  assert.deepEqual(uraiRute(undefined), { nama: "beranda" });
  assert.deepEqual(uraiRute("#/proyek"), { nama: "proyek" });
  assert.deepEqual(uraiRute("#/proyek/"), { nama: "proyek" });
  assert.deepEqual(uraiRute("#/proyek/12"), { nama: "detail", id: 12 });
  assert.deepEqual(uraiRute("#/proyek?x=1"), { nama: "proyek" });
});

test("uraiRute: alamat aneh -> tidakada", () => {
  for (const h of ["#/abc", "#/proyek/abc", "#/proyek/12/edit", "#/proyek/-1", "#/proyek/1234567890", "#//proyek"]) {
    assert.deepEqual(uraiRute(h), { nama: "tidakada" }, h);
  }
});

test("alamat dan uraiRute konsisten", () => {
  assert.deepEqual(uraiRute(alamat.beranda()), { nama: "beranda" });
  assert.deepEqual(uraiRute(alamat.proyek()), { nama: "proyek" });
  assert.deepEqual(uraiRute(alamat.detail(7)), { nama: "detail", id: 7 });
});
