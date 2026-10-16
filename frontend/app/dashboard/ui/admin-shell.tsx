"use client";

import Link from "next/link";
import { createContext, type FormEvent, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { button, input, secondary } from "./types";

type Identity = { email: string; csrf_token: string };
type AuthState = "loading" | "login" | "setup" | "ready" | "unavailable";
export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
type AdminContextValue = { api: <T>(path: string, options?: RequestInit) => Promise<T>; email: string };
const AdminContext = createContext<AdminContextValue | null>(null);
export function useAdmin() { const value = useContext(AdminContext); if (!value) throw new Error("AdminShell is required"); return value; }

export default function AdminShell({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>("loading");
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [message, setMessage] = useState("");
  const [logoutBusy, setLogoutBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/admin/session", { cache: "no-store", signal: controller.signal }).then(async response => {
      const data = await response.json();
      if (response.ok) { setIdentity(data); setState("ready"); }
      else if (response.status === 401) setState(data.setup_required ? "setup" : "login");
      else { setMessage(data.detail || "De beheeromgeving is niet beschikbaar."); setState("unavailable"); }
    }).catch(error => { if (error.name !== "AbortError") { setMessage("De backend is niet bereikbaar. Controleer je backendvenster."); setState("unavailable"); } });
    return () => controller.abort();
  }, []);

  const api = useCallback(async <T,>(path: string, options: RequestInit = {}): Promise<T> => {
    const headers = new Headers(options.headers);
    if (options.body) headers.set("Content-Type", "application/json");
    if (identity) headers.set("X-CSRF-Token", identity.csrf_token);
    const signal = options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000);
    const response = await fetch(`/api/admin/${path}`, { ...options, headers, signal, cache: "no-store" });
    const data = await response.json();
    if (response.status === 401) { setIdentity(null); setState("login"); }
    if (!response.ok) throw new ApiError(response.status, data.detail || "De actie kon niet worden uitgevoerd.");
    return data as T;
  }, [identity]);

  async function logout() {
    setLogoutBusy(true); setMessage("");
    try { await api("logout", { method: "POST" }); setIdentity(null); setState("login"); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Uitloggen is mislukt."); }
    finally { setLogoutBusy(false); }
  }

  if (state === "loading") return <main className="grid min-h-screen place-items-center"><p role="status" className="text-slate-600">Beheeromgeving laden…</p></main>;
  if (state === "unavailable") return <main className="mx-auto max-w-lg px-5 py-24"><h1 className="text-2xl font-bold">Beheeromgeving niet bereikbaar</h1><p role="alert" className="my-5 text-slate-600">{message}</p><button className={button} onClick={() => window.location.reload()}>Opnieuw proberen</button><Link className="ml-5 text-sm underline" href="/">Naar aanvraagformulier</Link></main>;
  if (state === "login" || state === "setup") return <Login setup={state === "setup"} onSuccess={value => { setIdentity(value); setState("ready"); setMessage(""); }} />;

  return <AdminContext.Provider value={{ api, email: identity!.email }}><div className="min-h-screen bg-slate-50 lg:grid lg:grid-cols-[220px_minmax(0,1fr)]">
    <aside className="border-b border-slate-200 bg-white px-5 py-5 lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:border-r lg:border-b-0 lg:px-6 lg:py-8">
      <Link href="/dashboard" className="flex items-center gap-3 font-extrabold"><span aria-hidden="true" className="grid h-9 w-9 place-items-center rounded-xl bg-blue-600 text-white">M</span><span>LeadFlow<span className="block font-mono text-xs font-normal tracking-widest text-slate-500">MAGNIFIZE</span></span></Link>
      <nav aria-label="Beheernavigatie" className="mt-6 flex flex-wrap gap-3 lg:flex-col"><Link href="/dashboard" className="flex min-h-11 items-center gap-3 rounded-lg bg-blue-50 px-3 py-3 text-sm font-bold text-blue-700"><svg aria-hidden="true" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>Aanvragen</Link><Link href="/" className="flex min-h-11 items-center rounded-lg px-3 py-3 text-sm text-slate-600 hover:bg-slate-50">Publiek formulier <span aria-hidden="true" className="ml-2">↗</span></Link></nav>
      <div className="mt-6 hidden rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-600 lg:mt-auto lg:block"><p className="font-semibold text-slate-800">Lokale demo</p><p className="mt-1">Fictieve aanvragen, lokaal opgeslagen. Optionele lokale n8n-verwerking; geen automatische e-mail.</p></div>
    </aside>
    <div className="min-w-0"><header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4 md:px-8"><span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 font-mono text-xs text-blue-700">CRM / lokale demo</span><div className="flex min-w-0 flex-wrap items-center gap-3"><span className="max-w-52 truncate text-sm text-slate-600">{identity?.email}</span><button className={secondary} disabled={logoutBusy} onClick={logout}>{logoutBusy ? "Uitloggen…" : "Uitloggen"}</button></div></header>{message && <p role="alert" className="mx-5 mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">{message}</p>}<main className="mx-auto max-w-7xl px-5 py-8 md:px-8 md:py-10">{children}</main></div>
  </div></AdminContext.Provider>;
}

function Login({ setup, onSuccess }: { setup: boolean; onSuccess: (identity: Identity) => void }) {
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (setup && password !== confirm) { setError("De wachtwoorden zijn niet gelijk."); return; }
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/admin/${setup ? "setup" : "login"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.trim(), password }), signal: AbortSignal.timeout(15000) });
      const data = await response.json();
      if (!response.ok) { setError(data.detail || "Inloggen is mislukt."); return; }
      setPassword(""); setConfirm(""); onSuccess(data);
    } catch { setError("De backend is niet bereikbaar. Probeer opnieuw."); }
    finally { setBusy(false); }
  }
  return <main className="grid min-h-screen place-items-center grid-lines px-5 py-12"><section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8"><Link href="/" className="mb-8 flex items-center gap-3 font-extrabold"><span aria-hidden="true" className="grid h-10 w-10 place-items-center rounded-xl bg-blue-600 text-white">M</span>Magnifize / LeadFlow</Link><p className="font-mono text-xs uppercase tracking-widest text-blue-700">Beheeromgeving</p><h1 className="mt-3 text-3xl font-extrabold tracking-tight">{setup ? "Maak je beheeraccount." : "Welkom terug."}</h1><p className="mt-3 text-sm leading-6 text-slate-600">{setup ? "Kies je eigen login voor het lokale CRM. Je wachtwoord wordt gehasht opgeslagen in de projectconfiguratie." : "Log in om aanvragen te bekijken en op te volgen."}</p>
    <form onSubmit={submit} className="mt-7 grid gap-5" aria-label={setup ? "Beheeraccount instellen" : "Beheerlogin"}>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      <div><label htmlFor="admin-email" className="mb-2 block text-sm font-semibold">E-mailadres</label><input id="admin-email" className={input} type="email" autoComplete="username" required maxLength={254} value={email} onChange={event => setEmail(event.target.value)} disabled={busy}/></div>
      <div><label htmlFor="admin-password" className="mb-2 block text-sm font-semibold">Wachtwoord</label><input id="admin-password" className={input} type="password" autoComplete={setup ? "new-password" : "current-password"} minLength={setup ? 15 : 1} maxLength={128} required value={password} onChange={event => setPassword(event.target.value)} disabled={busy}/>{setup && <p className="mt-2 text-xs text-slate-600">Minimaal 15 tekens. Een lange wachtwoordzin werkt ook.</p>}</div>
      {setup && <div><label htmlFor="admin-confirm" className="mb-2 block text-sm font-semibold">Herhaal wachtwoord</label><input id="admin-confirm" className={input} type="password" autoComplete="new-password" required value={confirm} onChange={event => setConfirm(event.target.value)} disabled={busy}/></div>}
      <button className={`${button} w-full`} disabled={busy}>{busy ? "Even wachten…" : setup ? "Beheeraccount maken" : "Inloggen"}</button>
    </form><p className="mt-6 border-t border-slate-100 pt-5 text-xs leading-5 text-slate-500">Deze beheerlogin is voor de lokale demo. Je sessie verloopt na één uur of een backend-herstart.</p></section></main>;
}
