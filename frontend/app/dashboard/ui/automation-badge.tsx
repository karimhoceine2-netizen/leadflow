import { type AutomationInfo } from "./types";

const states: Record<AutomationInfo["status"], { label: string; color: string; explanation: string }> = {
  processed: { label: "Automatisch verwerkt", color: "bg-emerald-50 text-emerald-800 ring-emerald-200", explanation: "De lokale demo-workflow heeft een eenmalig verwerkingsresultaat opgeslagen. Je leadstatus blijft zoals jij die hebt gekozen." },
  pending: { label: "Wacht op verwerking", color: "bg-amber-50 text-amber-900 ring-amber-200", explanation: "De aanvraag is veilig opgeslagen. Controleer of de backend en n8n draaien en de koppeling is ingeschakeld. Bij een storing wordt automatisch opnieuw geprobeerd." },
  failed: { label: "Opnieuw proberen nodig", color: "bg-red-50 text-red-800 ring-red-200", explanation: "De automatische pogingen zijn gestopt; je aanvraag is behouden. Controleer n8n en plan daarna een handmatige retry in volgens de lokale handleiding." },
  not_scheduled: { label: "Niet ingepland", color: "bg-slate-100 text-slate-700 ring-slate-200", explanation: "Deze oudere aanvraag heeft geen workflowevent. Bestaande aanvragen worden niet achteraf automatisch verwerkt." },
  unavailable: { label: "Niet beschikbaar", color: "bg-slate-100 text-slate-700 ring-slate-200", explanation: "Voor deze opslagomgeving is nog geen lokale verwerkingsinformatie beschikbaar." },
};

export function automationExplanation(info?: AutomationInfo) {
  return states[info?.status ?? "unavailable"].explanation;
}

export default function AutomationBadge({ info }: { info?: AutomationInfo }) {
  const state = states[info?.status ?? "unavailable"];
  return <span className={`inline-flex max-w-full items-center rounded-lg px-2.5 py-1 text-xs font-semibold leading-5 ring-1 ring-inset ${state.color}`}>{state.label}</span>;
}
