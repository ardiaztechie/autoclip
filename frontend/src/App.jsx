import { useCallback, useEffect, useState } from "react";
import { saya } from "./api.js";
import Kerangka from "./Kerangka.jsx";
import { uraiRute } from "./rute.js";
import { useDaftarProyek } from "./useDaftarProyek.js";
import Beranda from "./halaman/Beranda.jsx";
import Hasil from "./halaman/Hasil.jsx";
import Login from "./halaman/Login.jsx";
import Proyek from "./halaman/Proyek.jsx";
import TidakAda from "./halaman/TidakAda.jsx";

function useRute() {
  const [rute, setRute] = useState(() => uraiRute(window.location.hash));
  useEffect(() => {
    const ubah = () => setRute(uraiRute(window.location.hash));
    window.addEventListener("hashchange", ubah);
    return () => window.removeEventListener("hashchange", ubah);
  }, []);
  return rute;
}

function Aplikasi({ pengguna, padaKeluar }) {
  const rute = useRute();
  const { daftar, galat, muat } = useDaftarProyek(padaKeluar);

  let isi;
  if (rute.nama === "beranda") isi = <Beranda pengguna={pengguna} daftar={daftar} galat={galat} muat={muat} padaKeluar={padaKeluar} />;
  else if (rute.nama === "proyek") isi = <Proyek daftar={daftar} galat={galat} />;
  else if (rute.nama === "detail") isi = <Hasil key={rute.id} id={rute.id} padaKeluar={padaKeluar} />;
  else isi = <TidakAda />;

  return (
    <Kerangka pengguna={pengguna} rute={rute} padaKeluar={padaKeluar}>
      {isi}
    </Kerangka>
  );
}

export default function App() {
  const [pengguna, setPengguna] = useState(undefined); // undefined = memuat, null = belum masuk
  const [galat, setGalat] = useState("");
  const keluarSesi = useCallback(() => setPengguna(null), []);

  useEffect(() => {
    saya()
      .then(setPengguna)
      .catch((e) => {
        if (e.status !== 401) setGalat(e.message);
        setPengguna(null);
      });
  }, []);

  if (pengguna === undefined) return <p className="p-8 text-slate-500">Memuat...</p>;
  if (pengguna === null) return <Login galatAwal={galat} padaMasuk={setPengguna} />;
  return <Aplikasi pengguna={pengguna} padaKeluar={keluarSesi} />;
}
