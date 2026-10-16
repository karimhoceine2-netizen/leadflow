import "./globals.css";
import type { Metadata } from "next";
export const metadata: Metadata = { title: "Magnifize LeadFlow", description: "Lead intake that is ready for follow-up." };
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) { return <html lang="nl"><body><div role="note" className="border-b border-blue-200 bg-blue-50 px-5 py-2 text-center text-xs leading-5 text-blue-900">Portfolio-demo · uitsluitend fictieve gegevens · workflowprioriteit via vaste regels</div>{children}</body></html>; }
