import { useCallback, useEffect, useState } from "react";
import { saya } from "./api.js";
import Kerangka from "./Kerangka.jsx";
import { alamat, uraiRute } from "./rute.js";
import { useDaftarProyek } from "./useDaftarProyek.js";
import Cms from "./halaman/Cms.jsx";
import Landing from "./halaman/Landing.jsx";
import Beranda from "./halaman/Beranda.jsx";
import Editor from "./halaman/Editor.jsx";
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
  const ruteAsli = useRute();
  const rute = ruteAsli.nama === "masuk" ? { nama: "beranda" } : ruteAsli;       // sudah masuk: #/masuk sama dengan beranda
  const { daftar, galat, muat } = useDaftarProyek(padaKeluar);

  if (rute.nama === "landing") return <Landing pengguna={pengguna} />;
  if (rute.nama === "editor") return <Editor key={`${rute.id}-${rute.klip}`} id={rute.id} idKlip={rute.klip} padaKeluar={padaKeluar} />;

  let isi;
  if (rute.nama === "beranda") isi = <Beranda pengguna={pengguna} daftar={daftar} galat={galat} muat={muat} padaKeluar={padaKeluar} />;
  else if (rute.nama === "cms") isi = <Cms pengguna={pengguna} padaKeluar={padaKeluar} />;
  else if (rute.nama === "proyek") isi = <Proyek daftar={daftar} galat={galat} muat={muat} />;
  else if (rute.nama === "detail") isi = <Hasil key={rute.id} id={rute.id} padaKeluar={padaKeluar} padaHapus={() => { muat(); window.location.hash = alamat.proyek(); }} />;
  else isi = <TidakAda />;

  return (
    <Kerangka pengguna={pengguna} rute={rute} padaKeluar={padaKeluar}>
      {isi}
    </Kerangka>
  );
}

/** Pengunjung yang belum masuk: landing page di #/ dan #/landing, formulir masuk di #/masuk; alamat lain diarahkan ke #/masuk. */
function TamuApp({ galat, padaMasuk }) {
  const rute = useRute();
  if (rute.nama === "beranda" || rute.nama === "landing") return <Landing pengguna={null} />;
  return <Login galatAwal={galat} padaMasuk={padaMasuk} />;
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

  if (pengguna === undefined) return <p className="p-8 text-zinc-500">Memuat...</p>;
  if (pengguna === null) return <TamuApp galat={galat} padaMasuk={(u) => { window.location.hash = alamat.beranda(); setPengguna(u); }} />;
  return <Aplikasi pengguna={pengguna} padaKeluar={keluarSesi} />;
}
