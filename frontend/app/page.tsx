import LeadForm from "./components/lead-form";

const sampleLeads = [
  { name: "Demo Alpha", company: "Designbureau", status: "Nieuw", time: "Zojuist" },
  { name: "Demo Bravo", company: "Demo Studio Bravo", status: "Opvolgen", time: "18 min" },
  { name: "Demo Charlie", company: "Demo Studio Charlie", status: "Gekwalificeerd", time: "Gisteren" },
];

export default function Home() {
  return (
    <main id="top" className="min-h-screen grid-lines">
      <a href="#aanvraag" className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-white focus:p-4">Ga naar het aanvraagformulier</a>
      <header className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-6 md:px-8">
        <a className="flex items-center gap-2 text-sm font-extrabold tracking-tight sm:gap-3 sm:text-base" href="#top" aria-label="Magnifize LeadFlow — home">
          <span aria-hidden="true" className="grid h-9 w-9 place-items-center rounded-xl bg-blue-600 text-white">M</span>
          MAGNIFIZE <span className="font-medium text-slate-500">/ LeadFlow</span>
        </a>
        <div className="flex flex-wrap items-center gap-3"><a className="px-2 py-3 text-sm font-semibold text-slate-600 hover:text-blue-700" href="/dashboard">Beheerlogin</a><a className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition hover:border-blue-600 hover:text-blue-700" href="#aanvraag">Start een aanvraag</a></div>
      </header>

      <section className="mx-auto grid max-w-6xl gap-10 px-5 pb-16 pt-10 md:grid-cols-[1.05fr_.95fr] md:px-8 md:pt-20">
        <div className="rise">
          <p className="font-mono text-xs font-medium uppercase tracking-[.2em] text-blue-700">Magnifize / van aanvraag naar actie</p>
          <h1 className="mt-5 max-w-xl text-5xl font-extrabold leading-[1.05] tracking-[-.055em] text-slate-900 md:text-7xl">Een aanvraag is het begin van een <span className="text-blue-600">goed gesprek.</span></h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-slate-600">Een helder startpunt voor je volgende automatisering. Vertel wat je wilt verbeteren, zodat we gericht met je kunnen meedenken.</p>
          <div className="mt-9 flex flex-wrap items-center gap-4">
            <a href="#aanvraag" className="rounded-lg bg-orange-700 px-5 py-3 font-bold text-white transition hover:bg-orange-800">Doe een aanvraag <span aria-hidden="true">↗</span></a>
            <span className="font-mono text-xs text-slate-600">lokale intake-demo</span>
          </div>
          <div className="mt-10 flex items-center gap-3 border-t border-slate-200 pt-5 text-sm text-slate-600">
            <svg aria-hidden="true" className="h-5 w-5 shrink-0 text-blue-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z"/><path d="m8 12 3 3 5-6"/></svg>
            Gebruik fictieve gegevens. Je aanvraag blijft in de lokale demo.
          </div>
        </div>

        <aside aria-label="Voorbeeld van de toekomstige leadpipeline" className="rise self-center rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_24px_70px_-34px_rgba(37,99,235,.35)] md:p-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4">
            <div><p className="font-mono text-xs uppercase tracking-wider text-slate-500">Pipeline / voorbeeld</p><h2 className="mt-1 font-bold">Van interesse naar opvolging</h2></div>
            <span className="rounded-full bg-blue-50 px-3 py-1.5 text-xs font-bold text-blue-700">Demo</span>
          </div>
          <div className="divide-y divide-slate-100">
            {sampleLeads.map((lead, index) => (
              <div key={lead.name} className="flex items-center justify-between gap-3 py-5">
                <div className="flex items-center gap-3"><span aria-hidden="true" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-slate-100 font-mono text-sm font-medium text-slate-600">{lead.name.slice(0, 1)}</span><div><p className="font-semibold text-slate-800">{lead.name}</p><p className="mt-1 text-sm text-slate-500">{lead.company}</p></div></div>
                <div className="shrink-0 text-right"><span className={`text-xs font-semibold ${index === 2 ? "text-emerald-700" : "text-blue-700"}`}>{lead.status}</span><p className="mt-1 font-mono text-xs text-slate-500">{lead.time}</p></div>
              </div>
            ))}
          </div>
          <p className="mt-2 rounded-lg bg-slate-50 px-3 py-3 text-xs leading-5 text-slate-600">Fictieve voorbeeldgegevens. Je eigen aanvragen staan in het CRM achter de beheerlogin.</p>
        </aside>
      </section>

      <section id="aanvraag" className="scroll-mt-6 border-y border-slate-200 bg-white">
        <div className="mx-auto grid max-w-6xl gap-10 px-5 py-16 md:grid-cols-[.8fr_1.2fr] md:px-8">
          <div><p className="font-mono text-xs font-medium uppercase tracking-[.2em] text-blue-700">Aanvraag</p><h2 className="mt-4 text-3xl font-extrabold tracking-[-.04em]">Vertel waar je heen wilt.</h2><p className="mt-4 max-w-sm leading-7 text-slate-600">Welk proces kost je team onnodig tijd? Beschrijf je vraag, je huidige werkwijze en wat je wilt bereiken.</p><p className="mt-6 text-sm text-slate-500">Alle velden zijn verplicht.</p></div>
          <LeadForm />
        </div>
      </section>
      <footer className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-8 text-sm text-slate-600 md:flex-row md:justify-between md:px-8"><span>© 2026 Magnifize — LeadFlow portfolio-project</span><span className="font-mono text-xs">Intake-demo · gebruik fictieve gegevens</span></footer>
    </main>
  );
}
