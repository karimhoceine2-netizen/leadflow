import type { NextRequest } from "next/server";

export const runtime = "nodejs";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  // Next may normalize request.nextUrl to localhost in development. Compare
  // the browser Origin against the actual HTTP Host, not that internal URL.
  const host = request.headers.get("host") || "";
  let hostname = "";
  try { hostname = new URL(`http://${host}`).hostname; } catch { /* reject below */ }
  if (!["127.0.0.1", "localhost", "[::1]"].includes(hostname)) {
    return Response.json({ detail: "De beheerlogin is alleen lokaal beschikbaar." }, { status: 403 });
  }
  const { path } = await context.params;
  const target = path.join("/");
  if (!/^(session|setup|login|logout|leads|leads\/[0-9a-f-]{36}(\/status)?)$/.test(target)) {
    return Response.json({ detail: "Deze route bestaat niet." }, { status: 404 });
  }
  const headers = new Headers();
  for (const name of ["content-type", "cookie", "origin", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let body: ArrayBuffer | undefined;
  if (request.method !== "GET") {
    if (request.headers.get("origin") !== `${request.nextUrl.protocol}//${host}`) {
      return Response.json({ detail: "De herkomst van dit verzoek is niet toegestaan." }, { status: 403 });
    }
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 16384) {
          await reader.cancel();
          return Response.json({ detail: "Het verzoek is te groot." }, { status: 413 });
        }
        chunks.push(value);
      }
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    body = bytes.buffer;
  }
  try {
    const base = (process.env.LEADFLOW_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    const upstream = await fetch(`${base}/api/admin/${target}${request.nextUrl.search}`, {
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(12000),
    });
    const responseHeaders = new Headers({ "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("Set-Cookie", cookie);
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter) responseHeaders.set("Retry-After", retryAfter);
    return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: "De backend is niet bereikbaar. Controleer of je backendvenster nog draait." }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
