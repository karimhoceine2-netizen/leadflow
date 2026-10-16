export type LeadStatus = "new" | "contacted" | "qualified" | "closed";
export const statuses: Record<LeadStatus, string> = { new: "Nieuw", contacted: "Gecontacteerd", qualified: "Gekwalificeerd", closed: "Gesloten" };
export type AutomationInfo = { status: "not_scheduled" | "pending" | "processed" | "failed" | "unavailable"; delivery_state: "pending" | "delivered" | "dead" | null; attempts: number; processed_at: string | null; priority: "normal" | "review_urgency" | null };
export type Lead = { id: string; name: string; email: string; company_name: string; description: string; status: LeadStatus; version: number; created_at: string; updated_at: string; automation?: AutomationInfo };
export type StatusEvent = { id: string; previous_status: LeadStatus; new_status: LeadStatus; actor: string; created_at: string };
export type Detail = Lead & { history: StatusEvent[] };
export type LeadPage = { items: Lead[]; total: number; page: number; page_size: number; counts: Record<LeadStatus, number> };
export const button = "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50";
export const secondary = "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
export const input = "min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base text-slate-900";
export function formatDate(date: string) { return new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium", timeStyle: "short" }).format(new Date(date)); }
