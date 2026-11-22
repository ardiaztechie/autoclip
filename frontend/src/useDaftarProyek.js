import { useCallback, useEffect, useState } from "react";
import { daftarProyek } from "./api.js";
import { masihBerjalan } from "./format.js";

/** Memuat daftar proyek, dan memuat ulang tiap 3 detik selama ada yang berjalan. */
export function useDaftarProyek(padaSesiHabis) {
  const [daftar, setDaftar] = useState(null);
  const [galat, setGalat] = useState("");

  const muat = useCallback(async () => {
    try {
      setDaftar(await daftarProyek());
      setGalat("");
    } catch (e) {
      if (e.status === 401) padaSesiHabis();
      else setGalat(e.message);
    }
  }, [padaSesiHabis]);

  useEffect(() => {
    muat();
  }, [muat]);

  const adaBerjalan = daftar?.some(masihBerjalan) ?? false;
  useEffect(() => {
    if (!adaBerjalan) return undefined;
    const id = setInterval(muat, 3000);
    return () => clearInterval(id);
  }, [adaBerjalan, muat]);

  return { daftar, galat, muat };
}
