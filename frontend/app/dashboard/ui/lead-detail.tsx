"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, useAdmin } from "./admin-shell";
import StatusBadge from "./status-badge";
import AutomationBadge, { automationExplanation } from "./automation-badge";
import { button, type Detail, formatDate, input, type LeadStatus, secondary, statuses } from "./types";

export default function LeadDetail({ id }: { id: string }) {
  const { api } = useAdmin();
  const [lead, setLead] = useState<Detail | null>(null); const [selected, setSelected] = useState<LeadStatus>("new");
  const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false); const [error, setError] = useState(""); const [saved, setSaved] = useState(false);
  const [refreshing, setRefreshing] = useState(false); const [refreshError, setRefreshError] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    const result = await api<Detail>(`leads/${encodeURIComponent(id)}`, { signal });
    setLead(result); setSelected(result.status);
  }, [api, id]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(""); setLead(null);
    load(controller.signal).catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "Deze aanvraag kon niet worden geladen."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [load]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!lead || saving) return;
    setSaving(true); setError(""); setSaved(false);
    try {
      const result = await api<Detail>(`leads/${id}/status`, { method: "PATCH", body: JSON.stringify({ status: selected, expected_version: lead.version }) });
      setLead(result); setSelected(result.status); setSaved(true);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try { await load(); } catch { setError("De nieuwste versie kon niet worden geladen. Vernieuw de pagina."); return; }
      }
      setError(error instanceof Error ? error.message : "Opslaan is mislukt.");
    } finally { setSaving(false); }
  }

  async function refreshAutomation() {
    if (refreshing || saving) return;
    setRefreshing(true); setRefreshError("");
    try {
      const result = await api<Detail>(`leads/${encodeURIComponent(id)}`);
      // Do not replace the selected CRM status or its optimistic version while the user edits.
      setLead(previous => previous && previous.id === result.id ? { ...previous, automation: result.automation } : previous);
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : "De verwerking kon niet worden vernieuwd.");
    } finally { setRefreshing(false); }
  }

  if (loading) return <p role="status" className="py-10 text-slate-600">Aanvraag laden…</p>;
  if (!lead) return <div><Link href="/dashboard" className="text-sm text-blue-700 underline">Terug naar aanvragen</Link><h1 className="mt-8 text-2xl font-bold">Aanvraag niet beschikbaar</h1><p role="alert" className="mt-4 text-red-800">{error}</p><button className={`${secondary} mt-5`} onClick={() => window.location.reload()}>Opnieuw proberen</button></div>;
  return <>
    <Link href="/dashboard" className="inline-flex min-h-11 items-center text-sm font-semibold text-slate-600 hover:text-blue-700"><span aria-hidden="true" className="mr-2">←</span>Terug naar aanvragen</Link>
    <div className="mt-4 flex flex-wrap items-center justify-between gap-4"><div className="min-w-0"><p className="font-mono text-xs uppercase tracking-widest text-slate-500">Aanvraag / {lead.id.slice(0, 8)}</p><h1 className="mt-2 break-all text-3xl font-extrabold tracking-tight text-slate-900">{lead.company_name}</h1><p className="mt-3 text-sm text-slate-600">Ontvangen op {formatDate(lead.created_at)}</p></div><StatusBadge status={lead.status}/></div>
    <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(280px,.8fr)]"><div className="grid content-start gap-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 md:p-6"><h2 className="font-bold">Contactgegevens</h2><dl className="mt-5 grid gap-5 sm:grid-cols-2"><div><dt className="text-xs font-semibold text-slate-500">Contactpersoon</dt><dd className="mt-2 break-all text-sm text-slate-900">{lead.name}</dd></div><div><dt className="text-xs font-semibold text-slate-500">E-mailadres</dt><dd className="mt-2 break-all text-sm"><a className="text-blue-700 underline underline-offset-4" href={`mailto:${lead.email}`}>{lead.email}</a></dd></div><div className="sm:col-span-2"><dt className="text-xs font-semibold text-slate-500">Referentienummer</dt><dd className="mt-2 break-all font-mono text-xs text-slate-600">{lead.id}</dd></div></dl></section>
      <section className="rounded-xl border border-slate-200 bg-white p-5 md:p-6"><h2 className="font-bold">De aanvraag</h2><p className="mt-5 whitespace-pre-wrap [overflow-wrap:anywhere] text-sm leading-7 text-slate-700">{lead.description}</p></section>
      <section className="rounded-xl border border-slate-200 bg-white p-5 md:p-6" aria-label="Automatische verwerking" aria-busy={refreshing}>
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-bold">Automatische verwerking</h2><button type="button" className={secondary} disabled={refreshing || saving} onClick={refreshAutomation}>{refreshing ? "Vernieuwen…" : "Verwerking vernieuwen"}</button></div>
        <div className="mt-4" aria-live="polite" aria-atomic="true"><span className="sr-only">Automatische verwerking: </span><AutomationBadge info={lead.automation}/></div>
        <p className="mt-3 text-sm leading-6 text-slate-600">{automationExplanation(lead.automation)}</p>
        {lead.automation?.processed_at && <p className="mt-3 text-sm text-slate-600">Verwerkt op {formatDate(lead.automation.processed_at)}</p>}
        {lead.automation?.priority && <p className="mt-2 text-sm text-slate-600">Demo-prioriteit: <span className="font-semibold text-slate-800">{lead.automation.priority === "review_urgency" ? "Spoed controleren" : "Normaal"}</span>. Bepaald met vaste regels, niet met AI.</p>}
        {lead.automation?.status === "processed" && lead.automation.delivery_state !== "delivered" && <p className="mt-3 text-sm leading-6 text-amber-900">Het resultaat is opgeslagen, maar de afleverbevestiging ontbreekt nog. Er komt geen tweede verwerkingsresultaat; controleer de koppeling als dit zo blijft.</p>}
        {refreshError && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{refreshError} De eerder geladen verwerking blijft zichtbaar.</p>}
        <p className="mt-4 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">Geen automatische e-mail. Vernieuwen leest alleen de status en start geen workflow.</p>
      </section>
      <section className="rounded-xl border border-slate-200 bg-white p-5 md:p-6" aria-label="Wijzigingshistorie"><h2 className="font-bold">Wijzigingshistorie</h2>{lead.history.length ? <ol className="mt-5 grid gap-5">{lead.history.map(event => <li key={event.id} className="border-l-2 border-blue-200 pl-4"><p className="text-sm font-semibold text-slate-800">{statuses[event.previous_status]} <span aria-hidden="true">→</span> {statuses[event.new_status]}</p><p className="mt-1 break-all text-xs leading-5 text-slate-500">{formatDate(event.created_at)} · {event.actor}</p></li>)}</ol> : <p className="mt-4 text-sm text-slate-600">Er zijn nog geen statuswijzigingen.</p>}<div className="mt-5 border-l-2 border-slate-200 pl-4"><p className="text-sm font-medium text-slate-700">Aanvraag ontvangen</p><p className="mt-1 text-xs text-slate-500">{formatDate(lead.created_at)} · publiek formulier</p></div></section>
    </div><aside className="self-start rounded-xl border border-slate-200 bg-white p-5 md:p-6"><h2 className="font-bold">Volgende stap</h2><p className="mt-3 text-sm leading-6 text-slate-600">Werk de status bij zodra je de aanvraag hebt opgevolgd.</p><form onSubmit={save} className="mt-6 grid gap-4" aria-label="Status bijwerken"><div><label className="mb-2 block text-sm font-semibold" htmlFor="next-status">Status</label><select id="next-status" value={selected} onChange={event => { setSelected(event.target.value as LeadStatus); setSaved(false); }} disabled={saving} className={input}>{(Object.keys(statuses) as LeadStatus[]).map(key => <option value={key} key={key}>{statuses[key]}</option>)}</select></div>{error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm leading-6 text-red-800">{error}</p>}{saved && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">Status opgeslagen.</p>}<button className={button} disabled={saving || selected === lead.status}>{saving ? "Opslaan…" : "Status opslaan"}</button></form><p className="mt-6 border-t border-slate-100 pt-5 text-xs leading-5 text-slate-500">Laatste wijziging: {formatDate(lead.updated_at)}. Elke wijziging wordt vastgelegd met je beheeraccount.</p></aside></div>
  </>;
}
