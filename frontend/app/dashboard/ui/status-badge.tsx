import { type LeadStatus, statuses } from "./types";

const colors: Record<LeadStatus, string> = { new: "bg-blue-50 text-blue-800 ring-blue-200", contacted: "bg-amber-50 text-amber-900 ring-amber-200", qualified: "bg-emerald-50 text-emerald-800 ring-emerald-200", closed: "bg-slate-100 text-slate-700 ring-slate-200" };
export default function StatusBadge({ status }: { status: LeadStatus }) {
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${colors[status]}`}>{statuses[status]}</span>;
}
