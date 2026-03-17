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
const ALLOWED_PKS = new Set([
  // Añadir aquí los PKs de cada servicio cuando los conozcas
  // Ejemplo: "28db94e270580be60f6e00285a7d8141f"
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

    const ts = Date.now();

    // Construir URL objetivo
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

    // ── Fetch desde el edge de Cloudflare ──────────────────────────────────────
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
        // Workers tienen 30s timeout por defecto
      });

      const text = await resp.text();
      const chars = text.length;
      const hasBkt = text.includes("bkt_init_widget");

      console.log(`OVC Worker: HTTP ${resp.status} — ${chars} chars — bkt=${hasBkt}`);

      // Retornar la respuesta JSONP directamente
      return new Response(text, {
        status: resp.status,
        headers: {
          "Content-Type":                "application/javascript",
          "Access-Control-Allow-Origin": "*",
          "X-OVC-Target":                target,
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
