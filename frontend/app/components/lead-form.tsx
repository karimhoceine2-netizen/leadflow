"use client";

import { type FormEvent, useRef, useState } from "react";

const initial = { name: "", email: "", company_name: "", description: "" };
type LeadInput = typeof initial;
type FieldName = keyof LeadInput;
type Errors = Partial<Record<FieldName, string>>;
const labels: Record<FieldName, string> = { name: "Naam", email: "E-mailadres", company_name: "Bedrijfsnaam", description: "Waar kunnen we mee helpen?" };
const limits: Record<FieldName, number> = { name: 120, email: 254, company_name: 160, description: 2000 };
const inputClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-3 font-normal text-slate-900 transition focus:border-blue-600 disabled:bg-slate-50";

function validate(input: LeadInput): Errors {
  const errors: Errors = {};
  if (input.name.length < 2) errors.name = "Vul een naam in van minimaal 2 tekens.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.email)) errors.email = "Vul een geldig e-mailadres in.";
  if (input.company_name.length < 2) errors.company_name = "Vul een bedrijfsnaam in van minimaal 2 tekens.";
  if (input.description.length < 10) errors.description = "Beschrijf je vraag in minimaal 10 tekens.";
  for (const field of Object.keys(limits) as FieldName[]) {
    if (input[field].length > limits[field]) errors[field] = `Gebruik maximaal ${limits[field]} tekens.`;
  }
  return errors;
}

export default function LeadForm() {
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState<Errors>({});
  const [state, setState] = useState<"idle" | "sending" | "success" | "error">("idle");
  const [message, setMessage] = useState("");
  const [reference, setReference] = useState("");
  const sending = useRef(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const summary = useRef<HTMLDivElement>(null);

  function showError(text: string, fields: Errors = {}) {
    setErrors(fields); setState("error"); setMessage(text);
    // Focus after React has rendered the error summary.
    requestAnimationFrame(() => summary.current?.focus());
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending.current) return;
    const input = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value.trim()])) as LeadInput;
    const invalid = validate(input);
    if (Object.keys(invalid).length) { showError("Controleer de gemarkeerde velden.", invalid); return; }
    sending.current = true;
    setErrors({}); setState("sending"); setMessage(""); setReference("");
    const body = JSON.stringify(input);
    // Keep the key on timeout/failure. Retrying unchanged input cannot create a second lead.
    if (attempt.current?.body !== body) attempt.current = { body, key: crypto.randomUUID() };
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}/api/leads`, {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": attempt.current.key }, body, signal: controller.signal,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const fields: Errors = {};
        if (response.status === 422 && Array.isArray(payload?.errors)) {
          for (const error of payload.errors) {
            if (typeof error.field === "string" && error.field in labels) fields[error.field as FieldName] = `Controleer ${labels[error.field as FieldName].toLowerCase()}.`;
          }
        }
        showError(typeof payload?.detail === "string" ? payload.detail : "Versturen is tijdelijk niet mogelijk. Probeer opnieuw.", fields);
        return;
      }
      if (typeof payload?.id !== "string") { showError("De bevestiging kon niet worden gelezen. Probeer opnieuw."); return; }
      setState("success"); setMessage("Je aanvraag is ontvangen en opgeslagen."); setReference(payload.id); setForm(initial); attempt.current = null;
    } catch {
      showError("We konden geen bevestiging ontvangen. Controleer je verbinding en probeer opnieuw; dezelfde aanvraag wordt niet dubbel opgeslagen.");
    } finally { clearTimeout(timeout); sending.current = false; }
  }

  function change(field: FieldName, value: string) {
    setForm(previous => ({ ...previous, [field]: value }));
    if (state === "success") { setState("idle"); setMessage(""); setReference(""); }
    setErrors(previous => ({ ...previous, [field]: undefined }));
  }

  return (
    <form onSubmit={submit} className="grid gap-5" noValidate aria-label="Aanvraagformulier" aria-busy={state === "sending"}>
      {state === "error" && <div ref={summary} tabIndex={-1} role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800"><p>{message}</p>{Object.keys(errors).length > 0 && <ul className="mt-2 list-inside list-disc">{(Object.keys(errors) as FieldName[]).filter(field => errors[field]).map(field => <li key={field}><a className="underline" href={`#${field}`}>{errors[field]}</a></li>)}</ul>}</div>}
      <fieldset disabled={state === "sending"} className="grid min-w-0 gap-5">
        <legend className="sr-only">Contactgegevens en aanvraag</legend>
        <div className="grid gap-5 sm:grid-cols-2">
          {(["name", "email", "company_name"] as FieldName[]).map(field => <div key={field} className={field === "company_name" ? "sm:col-span-2" : ""}><label className="mb-2 block text-sm font-semibold text-slate-700" htmlFor={field}>{labels[field]}</label><input id={field} name={field} required type={field === "email" ? "email" : "text"} maxLength={limits[field]} minLength={field === "email" ? undefined : 2} value={form[field]} onChange={event => change(field, event.target.value)} autoComplete={field === "company_name" ? "organization" : field} aria-invalid={Boolean(errors[field])} aria-describedby={errors[field] ? `${field}-error` : undefined} className={inputClass} />{errors[field] && <p id={`${field}-error`} className="mt-2 text-sm text-red-700">{errors[field]}</p>}</div>)}
        </div>
        <div><label className="mb-2 block text-sm font-semibold text-slate-700" htmlFor="description">{labels.description}</label><textarea id="description" name="description" required minLength={10} maxLength={2000} value={form.description} onChange={event => change("description", event.target.value)} aria-invalid={Boolean(errors.description)} aria-describedby={errors.description ? "description-error description-hint" : "description-hint"} className={`${inputClass} min-h-36 resize-y`} placeholder="Bijvoorbeeld: aanvragen komen via e-mail binnen. We willen ze automatisch verdelen en sneller opvolgen." /><p id="description-hint" className="mt-2 text-xs text-slate-600">10 tot 2.000 tekens. Deel geen wachtwoorden of gevoelige gegevens.</p>{errors.description && <p id="description-error" className="mt-2 text-sm text-red-700">{errors.description}</p>}</div>
      </fieldset>
      {state === "success" && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"><p className="font-semibold">{message}</p><p className="mt-1 break-all font-mono text-xs">Referentie: {reference}</p><p className="mt-2">Portfolio-demo: lokale verwerking via n8n is mogelijk zodra de koppeling actief is. Er wordt geen e-mail verstuurd.</p></div>}
      <button type="submit" disabled={state === "sending"} className="w-fit cursor-pointer rounded-lg bg-blue-600 px-5 py-3 font-bold text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60">{state === "sending" ? "Aanvraag versturen…" : "Verstuur aanvraag"}</button>
    </form>
  );
}
