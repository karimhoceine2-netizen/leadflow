"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAdmin } from "./admin-shell";
import StatusBadge from "./status-badge";
import AutomationBadge from "./automation-badge";
import { formatDate, input, type LeadPage, type LeadStatus, secondary, statuses } from "./types";

export default function LeadList() {
  const { api } = useAdmin();
  const [data, setData] = useState<LeadPage | null>(null);
  const [search, setSearch] = useState(""); const [query, setQuery] = useState("");
  const [status, setStatus] = useState<LeadStatus | "">(""); const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(""); const [revision, setRevision] = useState(0);

  useEffect(() => { const timeout = setTimeout(() => { setQuery(search.trim()); setPage(1); }, 300); return () => clearTimeout(timeout); }, [search]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    const params = new URLSearchParams({ q: query, page: String(page), page_size: "20" });
    if (status) params.set("status", status);
    api<LeadPage>(`leads?${params}`, { signal: controller.signal }).then(setData).catch(error => {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Aanvragen konden niet worden geladen.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, query, status, page, revision]);

  const total = data ? Object.values(data.counts).reduce((sum, count) => sum + count, 0) : 0;
  return <>
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="font-mono text-xs uppercase tracking-widest text-slate-500">Je leadpipeline</p><h1 className="mt-2 text-3xl font-extrabold tracking-tight text-slate-900 md:text-4xl">Aanvragen</h1><p className="mt-3 text-sm leading-6 text-slate-600">Van eerste interesse naar een gerichte volgende stap.</p></div><button onClick={() => setRevision(value => value + 1)} className={secondary} disabled={loading}>Vernieuwen <span aria-hidden="true">↻</span></button></div>

    <div className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Pipeline-overzicht">
      {(Object.keys(statuses) as LeadStatus[]).map((key, index) => <button key={key} onClick={() => { setStatus(status === key ? "" : key); setPage(1); }} aria-pressed={status === key} className={`cursor-pointer rounded-xl border bg-white p-4 text-left transition hover:border-blue-400 md:p-5 ${status === key ? "border-blue-500 ring-1 ring-blue-500" : "border-slate-200"}`}><span className="flex items-center gap-2 text-xs font-semibold text-slate-600"><span aria-hidden="true" className={`h-2 w-2 rounded-full ${["bg-blue-600", "bg-amber-500", "bg-emerald-600", "bg-slate-400"][index]}`}/>{statuses[key]}</span><span className="mt-3 block font-mono text-3xl font-medium tracking-tight text-slate-900">{data ? data.counts[key] : "—"}</span></button>)}
    </div>

    <section className="mt-7 overflow-hidden rounded-xl border border-slate-200 bg-white" aria-label="Leadlijst" aria-busy={loading}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-4"><h2 className="font-bold">Alle aanvragen <span className="ml-2 font-mono text-xs font-normal text-slate-500">{data ? `${total} totaal` : ""}</span></h2><span className="text-xs text-slate-500">Meest recent bovenaan</span></div>
      <div className="grid gap-4 border-b border-slate-100 p-5 sm:grid-cols-[minmax(0,1fr)_220px]"><div><label className="mb-2 block text-xs font-semibold text-slate-600" htmlFor="lead-search">Zoeken</label><input id="lead-search" type="search" maxLength={100} className={input} placeholder="Naam, e-mailadres of bedrijf" value={search} onChange={event => setSearch(event.target.value)}/></div><div><label className="mb-2 block text-xs font-semibold text-slate-600" htmlFor="lead-status">Status</label><select id="lead-status" className={input} value={status} onChange={event => { setStatus(event.target.value as LeadStatus | ""); setPage(1); }}><option value="">Alle statussen</option>{(Object.keys(statuses) as LeadStatus[]).map(key => <option key={key} value={key}>{statuses[key]}</option>)}</select></div></div>
      {error ? <div role="alert" className="p-5"><p className="text-sm text-red-800">{error}</p><button className={`${secondary} mt-4`} onClick={() => setRevision(value => value + 1)}>Opnieuw proberen</button></div> : loading ? <p role="status" className="p-8 text-center text-sm text-slate-600">Aanvragen laden…</p> : !data?.items.length ? <div className="px-5 py-14 text-center"><h3 className="font-bold">{query || status ? "Geen aanvragen gevonden" : "Je eerste aanvraag begint hier"}</h3><p className="mt-2 text-sm text-slate-600">{query || status ? "Pas je zoekterm of statusfilter aan." : "Verstuur een testaanvraag via het publieke formulier."}</p>{query || status ? <button className={`${secondary} mt-5`} onClick={() => { setSearch(""); setQuery(""); setStatus(""); setPage(1); }}>Filters wissen</button> : <Link className={`${secondary} mt-5`} href="/">Open aanvraagformulier</Link>}</div> : <>
        <div className="hidden xl:block"><table className="w-full table-fixed text-left text-sm"><thead className="border-b border-slate-100 bg-slate-50/80 text-xs text-slate-600"><tr><th scope="col" className="w-[24%] px-4 py-3 font-semibold">Bedrijf</th><th scope="col" className="w-[22%] px-4 py-3 font-semibold">Contactpersoon</th><th scope="col" className="w-[17%] px-4 py-3 font-semibold">Ontvangen</th><th scope="col" className="w-[15%] px-4 py-3 font-semibold">Leadstatus</th><th scope="col" className="w-[22%] px-4 py-3 font-semibold">Verwerking</th></tr></thead><tbody className="divide-y divide-slate-100">{data.items.map(lead => <tr key={lead.id} className="hover:bg-slate-50/60"><td className="px-4 py-5"><Link href={`/dashboard/leads/${lead.id}`} className="block break-all font-semibold text-slate-900 underline-offset-4 hover:text-blue-700 hover:underline">{lead.company_name}</Link><p className="mt-1 font-mono text-xs text-slate-500">{lead.id.slice(0, 8)}</p></td><td className="px-4 py-5"><p className="break-all text-slate-800">{lead.name}</p><p className="mt-1 break-all text-xs text-slate-500">{lead.email}</p></td><td className="px-4 py-5 text-xs leading-5 text-slate-600">{formatDate(lead.created_at)}</td><td className="px-4 py-5"><StatusBadge status={lead.status}/></td><td className="px-4 py-5"><AutomationBadge info={lead.automation}/></td></tr>)}</tbody></table></div>
        <ul className="divide-y divide-slate-100 xl:hidden">{data.items.map(lead => <li key={lead.id} className="p-5"><Link href={`/dashboard/leads/${lead.id}`} className="block break-all font-semibold text-slate-900 underline-offset-4 hover:text-blue-700 hover:underline">{lead.company_name}</Link><p className="mt-2 break-all text-sm text-slate-600">{lead.name} · {lead.email}</p><div className="mt-4 flex flex-wrap gap-x-6 gap-y-3"><div><p className="mb-1 text-xs font-medium text-slate-600">Leadstatus</p><StatusBadge status={lead.status}/></div><div><p className="mb-1 text-xs font-medium text-slate-600">Verwerking</p><AutomationBadge info={lead.automation}/></div></div><p className="mt-3 font-mono text-xs text-slate-500">{formatDate(lead.created_at)}</p></li>)}</ul>
      </>}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4"><p className="text-xs text-slate-600">{data ? `${data.total} ${data.total === 1 ? "resultaat" : "resultaten"} · pagina ${page} van ${Math.max(1, Math.ceil(data.total / data.page_size))}` : ""}</p><div className="flex gap-2"><button className={secondary} disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>Vorige</button><button className={secondary} disabled={loading || !data || page * data.page_size >= data.total} onClick={() => setPage(value => value + 1)}>Volgende</button></div></div>
    </section>
    <p className="mt-5 text-xs leading-5 text-slate-500">Leadstatus is jouw opvolging; verwerking is het resultaat van de lokale demo-workflow. Klik op Vernieuwen om de nieuwste verwerking te zien. Er wordt geen e-mail verstuurd.</p>
  </>;
}
