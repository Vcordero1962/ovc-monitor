# SESIÓN OVC: 18 Marzo 2026 — Sesión 6 [18:00 - 20:30 Miami]

## 🎯 Objetivo
Inteligencia competitiva sobre AVC (Asesor Virtual Cubano) + fix definitivo
del gate Imperva "Continue/Continuar" confirmado con browser real + modo
continuo en ovc_spy.

---

## ✅ Logros

### 1. Imperva gate confirmado y resuelto — commit `7e3ff23`
- **Diagnóstico definitivo**: El browser desde IP residencial (casa) TAMBIÉN
  ve el "Continue / Continuar" de Imperva — es universal, no un bloqueo por IP.
- **Evidencia**: Screenshots del navegador Edge muestran el flujo completo:
  1. Continue/Continuar → 2. SE HA PRODUCIDO UN ERROR (transitorio) → 3. Widget real
- **Resultado final del widget LEGA**: "No hay horas disponibles" — **OVC estaba correcto**
- **Fix `playwright_check.py`**: Detección por texto visible (`inner_text`) en lugar de
  `input[name="token"]` — ahora detecta el gate con certeza y hace clic automático
  con 3 niveles de fallback (locator → JS click → Enter)
- **Fix `ovc_spy.py`**: Paso 2b añadido — igual lógica de detección/clic del gate

### 2. ovc_spy.py — modo continuo — commit `7e3ff23`
- `--continuo --intervalo 300 --alerta` → loop infinito con jitter anti-detección
- Log a `logs/ovc_spy_continuo_TIMESTAMP.log`
- Envía Telegram cuando `AllowAppointment=True`
- `ovc_spy.bat` ampliado: opciones 1-5 (single) + 6-8 (continuo) + 9-A (AVC intel)

### 3. ovc_avc_intel.py — inteligencia AVC — commit `7e3ff23`
- Scraper del canal público Telegram `t.me/s/AsesorVirtualC`
- Análisis: frecuencia de posts, horario, keywords técnicos, hipótesis de método
- Fix keyword detection: word-boundary para palabras cortas (≤3 chars) — evita
  falso positivo "ip" en "equipo"
- **Resultado del primer run**: 20 posts capturados, 13 sobre citas, 1 timestamp parseado
- Modo `--continuo` disponible (cada 10 min por defecto)

### 4. Análisis AVC — conclusiones
- **AVC NO tiene tecnología especial** — es un servicio de consultoría pagado (~15€)
- **Operadores humanos** verifican manualmente ("Verificado por nuestro equipo")
- **IP de casa** de algún operador en España o Cuba
- **No detecta con AllowAppointment** — reporta FECHAS ESPECÍFICAS del calendario
  (navegan el flujo completo de booking hasta ver las fechas disponibles)
- Canal Telegram: `t.me/AsesorVirtualC` | 4,746 suscriptores | WhatsApp también

---

## 📁 Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `core/playwright_check.py` | Gate bypass por texto + fallbacks JS/Enter + re-nav si URL cambió |
| `ovc_spy.py` | Paso 2b gate bypass + modo --continuo (loop+jitter+telegram) |
| `ovc_spy.bat` | Opciones 6-A (continuo LEGA/PASAPORTE + AVC intel) |
| `ovc_avc_intel.py` | NUEVO — scraper AVC + análisis patrón + modo continuo |

---

## 🔨 Commit esta sesión

| Hash | Descripción |
|------|-------------|
| `7e3ff23` | Fix Imperva gate bypass + AVC intel + ovc_spy modo continuo |

---

## 🤖 Estado al cierre

- **OVC Monitor**: ✅ 14/14 checks exitosos hoy
- **LEGA**: ✅ Sin citas — confirmado en browser (real, no falso)
- **ovc_spy --continuo**: 🟢 CORRIENDO en background (LEGA, 5 min, con alerta)
- **ovc_avc_intel --continuo**: 🟢 CORRIENDO en background (AVC, 10 min)
- **playwright_check.py**: ✅ Gate fix activo — próximo GitHub Actions run lo usará

---

## ❌ Pendiente

- **Verificación `AllowAppointment: true` en producción**: Cuando haya citas reales,
  confirmar alerta llega correctamente.
- **PASAPORTE URL**: AVC reportó fechas para Primer Pasaporte (Habana) — el PK de
  pasaporte en OVC puede necesitar verificación
- **Frecuencia AVC**: Con ovc_avc_intel corriendo continuo, próxima sesión podrá
  mostrar patrón de posting (¿cada cuánto publica AVC?)

---

## 🎯 Próxima sesión — empezar por

1. **Ver logs ovc_spy continuo**: `logs/ovc_spy_continuo_*.log` — ¿detecta correctamente?
2. **Ver logs AVC intel**: `logs/avc_intel_continuo_*.log` — ¿cuántos posts nuevos?
3. **Verificar PASAPORTE URL**: ¿Es el mismo PK que tiene OVC o diferente?

---

## ⚠️ Notas importantes

- **AVC es competencia manual, no técnica** — su ventaja es operadores humanos
  con IPs residenciales que navegan el widget completo
- **OVC ventanas críticas** (02:55 AM + 05:55 PM Miami) siguen siendo la detección
  más fiable desde IP residencial local
- **ovc_spy.bat opción 5** (visible) permite ver en tiempo real lo que ve el bot
