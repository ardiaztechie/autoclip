import { useState } from "react";
import { masuk } from "../api.js";

export default function Login({ galatAwal = "", padaMasuk }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [galat, setGalat] = useState(galatAwal);
  const [sibuk, setSibuk] = useState(false);

  async function kirim(e) {
    e.preventDefault();
    setGalat("");
    setSibuk(true);
    try {
      padaMasuk(await masuk(email, password));
    } catch (err) {
      setGalat(err.message);
      setSibuk(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={kirim} className="w-full max-w-sm bg-white rounded-2xl shadow p-8 space-y-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">AutoClip</h1>
          <p className="text-sm text-slate-500 mt-1">Ubah video panjang menjadi klip pendek.</p>
        </div>

        <label className="block">
          <span className="text-sm font-medium">Email</span>
          <input
            type="email"
            required
            autoFocus
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium">Password</span>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </label>

        {galat && (
          <p role="alert" className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {galat}
          </p>
        )}

        <button
          type="submit"
          disabled={sibuk}
          className="w-full rounded-lg bg-indigo-600 text-white font-medium py-2.5 hover:bg-indigo-700 disabled:opacity-60"
        >
          {sibuk ? "Memeriksa..." : "Masuk"}
        </button>
      </form>
    </main>
  );
}
