/** Isi landing page dari daftar bagian [{key, content}]. Dipakai halaman Landing dan pratinjau CMS. */
export default function IsiLanding({ bagian, hrefCta, labelCta }) {
  return (
    <div className="space-y-20">
      {bagian.map(({ key, content: c }) => {
        if (key === "hero")
          return (
            <section key={key} className="text-center max-w-3xl mx-auto pt-10 pb-4">
              <h1 className="text-4xl md:text-5xl font-bold text-white tracking-tight leading-tight">{c.title}</h1>
              {c.subtitle && <p className="text-lg text-zinc-400 mt-4">{c.subtitle}</p>}
              <a href={hrefCta} className="inline-block mt-8 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-medium px-7 py-3 transition-colors">
                {labelCta || c.cta_text}
              </a>
            </section>
          );
        if (key === "fitur")
          return (
            <section key={key} className="max-w-5xl mx-auto">
              <h2 className="text-2xl font-bold text-white text-center mb-8">Fitur</h2>
              <ul className="grid gap-4 md:grid-cols-3">
                {c.items.map((f, i) => (
                  <li key={i} className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
                    <span className="grid place-items-center w-9 h-9 rounded-lg bg-violet-500/15 text-violet-300 font-semibold mb-3">{i + 1}</span>
                    <h3 className="font-semibold text-white">{f.title}</h3>
                    <p className="text-sm text-zinc-400 mt-1">{f.text}</p>
                  </li>
                ))}
              </ul>
            </section>
          );
        if (key === "cara_kerja")
          return (
            <section key={key} className="max-w-3xl mx-auto">
              <h2 className="text-2xl font-bold text-white text-center mb-8">Cara kerja</h2>
              <ol className="space-y-3">
                {c.steps.map((s, i) => (
                  <li key={i} className="flex items-center gap-4 rounded-2xl border border-zinc-800 bg-zinc-900 px-5 py-4">
                    <span className="grid place-items-center w-8 h-8 shrink-0 rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white text-sm font-semibold">{i + 1}</span>
                    <span className="text-zinc-200">{s}</span>
                  </li>
                ))}
              </ol>
            </section>
          );
        if (key === "faq")
          return c.items.length === 0 ? null : (
            <section key={key} className="max-w-3xl mx-auto">
              <h2 className="text-2xl font-bold text-white text-center mb-8">Pertanyaan umum</h2>
              <div className="space-y-2">
                {c.items.map((f, i) => (
                  <details key={i} className="group rounded-2xl border border-zinc-800 bg-zinc-900 px-5 py-4">
                    <summary className="cursor-pointer font-medium text-white list-none flex justify-between gap-4">
                      {f.q}
                      <span className="text-zinc-500 group-open:rotate-45 transition-transform" aria-hidden="true">+</span>
                    </summary>
                    <p className="text-sm text-zinc-400 mt-3">{f.a}</p>
                  </details>
                ))}
              </div>
            </section>
          );
        if (key === "footer")
          return (
            <footer key={key} className="text-center text-sm text-zinc-500 border-t border-zinc-800 pt-8">
              {c.text}
            </footer>
          );
        return null;
      })}
    </div>
  );
}
