import { test } from "node:test";
import assert from "node:assert/strict";
import { pilihTema } from "./tema.js";

test("pilihTema: pilihan tersimpan menang, selain itu mengikuti sistem", () => {
  assert.equal(pilihTema("terang", false), "terang");
  assert.equal(pilihTema("gelap", true), "gelap");
  assert.equal(pilihTema(null, true), "terang");
  assert.equal(pilihTema(undefined, false), "gelap");
  assert.equal(pilihTema("ngawur", true), "terang");
});
