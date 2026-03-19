/**
 * OVC Cloudflare Worker — Relay para citaconsular.es / app.bookitit.com
 *
 * Cloudflare Workers corren en edge de CF (IPs de CF: 104.x.x.x).
 * Las IPs de CF son más confiables para Imperva que GitHub Actions (76.x.x.x Azure).
 * Además, Workers ejecutan V8 real — pueden resolver JS challenges de Imperva.
 *
 * Deploy: https://dash.cloudflare.com → Workers → Create Worker → pegar este código
 * Free tier: 100,000 requests/día — más que suficiente para checks cada 30 min.
 *
 * URL de uso (desde GitHub Actions):
 *   GET https://ovc-relay.TU-USUARIO.workers.dev/?pk=TU_PK&sid=TU_SID
 *
 * Responde con el JSONP real de Bookitit o un JSON de error.
 */

// ── Configuración ──────────────────────────────────────────────────────────────

// PKs conocidos de citaconsular.es (La Habana) — actualizar si cambian
// Los PKs se encuentran en las URLs configuradas: /widgetdefault/{PK}/{SID}
// PKs confirmados por Inspector OVC — Mar 17/2026; LEGA verificado browser Mar 18/2026
const ALLOWED_PKS = new Set([
  "25b6cfa9f112aef4ca19457abc237f7ba",  // LEGA  (Legalización) — 33 chars, verificado
  "28330379fc95acafd31ee9e8938c278ff",  // LMD   (Legalización Matrimonio/Defunción)
  "22091b5b8d43b89fb226cabb272a844f9",  // PASAPORTE
  "28db94e270580be60f6e00285a7d8141f",  // VISADO
  "2096463e6aff35e340c87439bc59e410c",  // MATRIMONIO
  "2f21cd9c0d8aa26725bf8930e4691d645",  // NACIMIENTO + NOTARIAL (mismo PK, SID diferente)
]);

// Secret para proteger el worker (evita abuso del free tier)
// Configurar en CF Dashboard → Worker → Settings → Variables → OVC_SECRET
// Desde GitHub Actions: GET /...?secret=TU_SECRET&pk=...
const REQUIRE_SECRET = true;

// ── Handler principal ──────────────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const pk      = url.searchParams.get("pk")      || "";
    const sid     = url.searchParams.get("sid")     || "";
    const lang    = url.searchParams.get("lang")    || "es";
    const secret  = url.searchParams.get("secret")  || "";
    const target  = url.searchParams.get("target")  || "bookitit";  // "bookitit" | "citaconsular"
    const mode    = url.searchParams.get("mode")    || "jsonp";     // "jsonp" (simple) | "full" (GET→POST→JSONP)

    // Validación de secret
    if (REQUIRE_SECRET && env.OVC_SECRET && secret !== env.OVC_SECRET) {
      return new Response(JSON.stringify({error: "Unauthorized"}), {
        status: 401,
        headers: {"Content-Type": "application/json"},
      });
    }

    // Validar PK (alfanumérico, 10-64 chars)
    if (!pk || !/^[a-zA-Z0-9]{10,64}$/.test(pk)) {
      return new Response(JSON.stringify({error: "pk requerido (10-64 chars alfanuméricos)"}), {
        status: 400,
        headers: {"Content-Type": "application/json"},
      });
    }

    // Whitelist de PKs conocidos (evita usar el Worker como proxy genérico)
    if (ALLOWED_PKS.size > 0 && !ALLOWED_PKS.has(pk)) {
      return new Response(JSON.stringify({error: "PK no autorizado"}), {
        status: 403,
        headers: {"Content-Type": "application/json"},
      });
    }

    const ts = Date.now();

    // ── Modo getservices: endpoint AllowAppointment directo ──────────────────────
    // Más confiable que bkt_init_widget — retorna AllowAppointment=true/false directamente.
    if (mode === "getservices") {
      const referer = `https://www.citaconsular.es/es/hosteds/widgetdefault/${pk}/`;
      const params  = new URLSearchParams({
        callback:  `ovc_gs_${ts}`,
        publickey: pk,
        lang:      lang,
        version:   "4",
        type:      "default",
        src:       referer,
        srvsrc:    "https://www.citaconsular.es",
        _:         ts,
      });

      // Intentar en los dos dominios, igual que bookitit.py
      for (const domain of ["app.bookitit.com", "www.citaconsular.es"]) {
        try {
          const gsUrl = `https://${domain}/onlinebookings/getservices/?${params}`;
          const r = await fetch(gsUrl, {
            method: "GET",
            headers: {
              "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
              "Accept":           "text/javascript, application/javascript, */*; q=0.01",
              "Accept-Language":  "es-ES,es;q=0.9",
              "Referer":          referer,
              "X-Requested-With": "XMLHttpRequest",
            },
          });
          const text = await r.text();
          console.log(`CF Worker getservices [${domain}]: ${r.status} — ${text.length} chars`);

          // Extraer JSON del JSONP
          const i0 = text.indexOf("{");
          const i1 = text.lastIndexOf("}");
          if (i0 !== -1 && i1 > i0) {
            try {
              const data = JSON.parse(text.slice(i0, i1 + 1));
              const allow = data.AllowAppointment;
              if (allow !== null && allow !== undefined) {
                return new Response(JSON.stringify({
                  ok:               true,
                  domain:           domain,
                  AllowAppointment: allow,
                  services_count:   (data.Services || []).length,
                  agendas_count:    (data.Agendas  || []).length,
                  sid:              (data.Services || [{}])[0]?.id || "",
                }), {
                  status: 200,
                  headers: { "Content-Type": "application/json", "Cache-Control": "no-cache, no-store", "Access-Control-Allow-Origin": "*" },
                });
              }
            } catch (_) {}
          }
        } catch (err) {
          console.error(`CF Worker getservices [${domain}] error: ${err.message}`);
        }
      }
      return new Response(JSON.stringify({ ok: false, error: "getservices no respondió con JSON válido en ningún dominio" }),
        { status: 200, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" } });
    }

    // Construir URL objetivo para modos jsonp/full
    let targetUrl;
    if (target === "citaconsular") {
      // Intentar via citaconsular.es (con Imperva — Workers pueden pasar el JS challenge)
      const params = new URLSearchParams({
        callback:  "bkt_init_widget",
        type:      "default",
        publickey: pk,
        lang:      lang,
        version:   "5",
        src:       "https://www.citaconsular.es/",
        _:         ts,
      });
      if (sid) params.set("services[]", sid);
      targetUrl = `https://www.citaconsular.es/onlinebookings/main/?${params}`;
    } else {
      // Directo a app.bookitit.com (sin Imperva del cliente)
      const params = new URLSearchParams({
        callback: "bkt_init_widget",
        pk:       pk,
        lang:     lang,
        _:        ts,
      });
      if (sid) params.set("services[]", sid);
      targetUrl = `https://app.bookitit.com/onlinebookings/main/?${params}`;
    }

    console.log(`OVC Worker: target=${target} pk=${pk.slice(0,12)}... url=${targetUrl.slice(0,80)}`);

    // ── Modo full: GET→POST→JSONP (con cookie de sesión Imperva) ──────────────
    if (mode === "full") {
      try {
        const widgetUrl = target === "citaconsular"
          ? `https://www.citaconsular.es/es/hosteds/widgetdefault/${pk}/${sid}`
          : `https://app.bookitit.com/es/hosteds/widgetdefault/${pk}/${sid}`;

        const baseHdrs = {
          "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
          "Accept":          "text/html,application/xhtml+xml,*/*;q=0.9",
          "Accept-Language": "es-ES,es;q=0.9",
          "Accept-Encoding": "gzip, deflate, br",
          "Connection":      "keep-alive",
          "Upgrade-Insecure-Requests": "1",
        };

        // Paso 1: GET widget → capturar cookies + token
        const r1 = await fetch(widgetUrl, { method: "GET", headers: baseHdrs, redirect: "follow" });
        const html1 = await r1.text();
        const cookies1 = r1.headers.get("set-cookie") || "";
        console.log(`CF Worker GET: ${r1.status} — ${html1.length} chars — cookies: ${cookies1.slice(0,60)}`);

        const tokenMatch = html1.match(/name=["']token["'][^>]*value=["']([^"']+)["']/)
                        || html1.match(/value=["']([^"']+)["'][^>]*name=["']token["']/);
        if (!tokenMatch) {
          return new Response(JSON.stringify({error: "sin token Imperva en GET", chars: html1.length, preview: html1.slice(0,200)}),
            { status: 200, headers: {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"} });
        }

        // Paso 2: POST token → establecer sesión Imperva
        const cookieHdr = cookies1 ? cookies1.split(",").map(c => c.split(";")[0]).join("; ") : "";
        const r2 = await fetch(widgetUrl, {
          method: "POST",
          headers: { ...baseHdrs,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": widgetUrl,
            "Cookie": cookieHdr,
          },
          body: `token=${encodeURIComponent(tokenMatch[1])}`,
          redirect: "follow",
        });
        const html2 = await r2.text();
        const cookies2 = r2.headers.get("set-cookie") || "";
        const allCookies = [cookieHdr, cookies2.split(",").map(c => c.split(";")[0]).join("; ")]
          .filter(Boolean).join("; ");
        console.log(`CF Worker POST: ${r2.status} — ${html2.length} chars — cookies: ${allCookies.slice(0,80)}`);

        // Paso 3: GET JSONP con cookie de sesión
        const jsonpParams = new URLSearchParams({
          callback: "bkt_init_widget", publickey: pk,
          lang, type: "default", version: "5", _: Date.now(),
        });
        if (sid) jsonpParams.set("services[]", sid);

        const jsonpBase = target === "citaconsular"
          ? "https://www.citaconsular.es/onlinebookings/main/"
          : "https://app.bookitit.com/onlinebookings/main/";

        const r3 = await fetch(`${jsonpBase}?${jsonpParams}`, {
          method: "GET",
          headers: { ...baseHdrs,
            "Accept": "*/*",
            "Referer": widgetUrl,
            "Cookie": allCookies,
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin",
          },
        });
        const text3 = await r3.text();
        const hasBkt = text3.includes("bkt_init_widget");
        console.log(`CF Worker JSONP: ${r3.status} — ${text3.length} chars — bkt=${hasBkt}`);

        return new Response(text3, {
          status: r3.status,
          headers: {
            "Content-Type": "application/javascript",
            "Access-Control-Allow-Origin": "*",
            "X-OVC-Mode": "full",
            "X-OVC-Chars": text3.length,
            "X-OVC-Has-Bkt": hasBkt ? "1" : "0",
            "Cache-Control": "no-cache, no-store",
          },
        });
      } catch (err) {
        console.error(`CF Worker full mode error: ${err.message}`);
        return new Response(JSON.stringify({ error: err.message, mode: "full" }),
          { status: 502, headers: {"Content-Type": "application/json"} });
      }
    }

    // ── Modo simple: GET JSONP directo desde CF edge ────────────────────────────
    try {
      const resp = await fetch(targetUrl, {
        method: "GET",
        headers: {
          "User-Agent":      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
          "Accept":          "*/*",
          "Accept-Language": "es-ES,es;q=0.9",
          "Referer":         target === "citaconsular"
                               ? "https://www.citaconsular.es/cita-previa/"
                               : "https://app.bookitit.com/",
          "Origin":          target === "citaconsular"
                               ? "https://www.citaconsular.es"
                               : "https://app.bookitit.com",
          "Sec-Fetch-Dest":  "script",
          "Sec-Fetch-Mode":  "no-cors",
          "Sec-Fetch-Site":  "same-origin",
        },
      });

      const text = await resp.text();
      const chars = text.length;
      const hasBkt = text.includes("bkt_init_widget");

      console.log(`OVC Worker: HTTP ${resp.status} — ${chars} chars — bkt=${hasBkt}`);

      return new Response(text, {
        status: resp.status,
        headers: {
          "Content-Type":                "application/javascript",
          "Access-Control-Allow-Origin": "*",
          "X-OVC-Target":                target,
          "X-OVC-Mode":                  "jsonp",
          "X-OVC-Chars":                 chars,
          "X-OVC-Has-Bkt":               hasBkt ? "1" : "0",
          "Cache-Control":               "no-cache, no-store",
        },
      });

    } catch (err) {
      console.error(`OVC Worker error: ${err.message}`);
      return new Response(JSON.stringify({
        error:   err.message,
        target:  target,
        pk:      pk.slice(0, 12) + "...",
      }), {
        status: 502,
        headers: {"Content-Type": "application/json"},
      });
    }
  },
};
