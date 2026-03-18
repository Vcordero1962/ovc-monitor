# 🏛️ OVC — GOVERNANCE (AGENT RULES)

> [!CRITICAL]
> **INSTRUCCIÓN SUPREMA PARA EL AGENTE:**
> Estas reglas definen tu comportamiento operativo en el proyecto OVC.
> Son mandatorias. Ignorarlas se considera falla crítica.

**Proyecto:** Orquestador de Vigilancia Consular (OVC)
**Ubicación:** `M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)\`
**Repo GitHub:** `Vcordero1962/ovc-monitor` (privado)
**Versión:** 1.0
**Fecha:** 15 Marzo 2026

---

## 0. 🃏 PROTOCOLO DE APERTURA

### 0.1 CARGA DE CONTEXTO OBLIGATORIA

> [!CRITICAL]
> **PRIMER MENSAJE DE CADA SESIÓN:** Leer siempre estos archivos antes de escribir código:
> 1. `CLAUDE.md` — arquitectura, credenciales, comandos clave
> 2. `GLOBAL_AGENT_RULES_OVC.md` (este archivo) — reglas de governance
> 3. Último `SESSION_SUMMARY_YYYYMMDD.md` — estado de la sesión anterior
> 4. `git log --oneline -5` — commits recientes

**Respuesta esperada al abrir sesión:**
```markdown
✅ Contexto OVC cargado

📌 Estado actual:
- Última sesión: [fecha] — [última tarea]
- Commit actual: [hash] — [mensaje]
- Bot GitHub Actions: [activo / inactivo]

🎯 Próxima tarea:
- [Descripción específica]

⚠️ Restricciones activas:
- [Lista de alertas/pendientes]

¿Procedo?
```

### 0.2 TARJETA DE INICIO (PRIMERA RESPUESTA DE SESIÓN NUEVA)

```markdown
# 🃏 OVC Update: [FECHA]

## ⏪ Sesión Anterior
- ✅ [Logro con commit hash]

## ⏩ Hoy
- 🎯 [Tarea específica]

## ⚠️ Estado Bot
- GitHub Actions: [OK / CAÍDO]
- Último heartbeat: [hace X horas]
- Sentinel: [corriendo / detenido]
```

---

## 1. 🔄 PROTOCOLO DE PRESERVACIÓN DEL ENTORNO

### 1.1 VERIFICACIÓN AL INICIO DE SESIÓN (OBLIGATORIO)

**PRIMERA ACCIÓN:** Verificar que el sentinel está corriendo:

```bash
# Verificar contenedor sentinel
docker ps | grep ovc-sentinel

# Si NO está corriendo — iniciarlo
cd "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)\ovc_sentinel"
docker-compose up -d

# Verificar logs
docker logs ovc-sentinel --tail 20
```

**Si Docker no disponible:** Informar al usuario — el sentinel no puede monitorear.

### 1.2 BACKUP ANTES DE CADA CAMBIO IMPORTANTE

```bash
# Backup manual antes de cambio significativo
cd "M:\Gina_Documents\Orquestador de Vigilancia Consular (OVC)"
git stash  # o verificar status
git status
```

**Cambios que requieren backup previo:**
- Modificar `ovc_once.py` (lógica principal)
- Modificar `.github/workflows/*.yml` (cron del bot)
- Cambiar credenciales en `.env`
- Modificar `ovc_sentinel/sentinel.py`

### 1.3 PRESERVACIÓN VÍA GIT (MANDATORIO)

El proyecto OVC usa **git como sistema de backup principal**.

- ✅ Cada cambio funcional → commit inmediato
- ✅ Cada sesión → push a origin/main
- ✅ `.env` NUNCA en git (está en .gitignore)
- ✅ Credenciales SOLO en `.env` local + GitHub Secrets

---

## 2. 📝 PROTOCOLO DE COMMITS

### 2.1 COMMIT DESPUÉS DE CADA CAMBIO (MANDATORIO)

**Formato:**
```bash
git commit -m "$(cat <<'EOF'
<tipo>: <descripción corta>

CAMBIOS:
- [archivo] — [qué cambió]

VERIFICADO:
✅ Bot GitHub Actions ejecutando
✅ Telegram recibe alertas
✅ Sentinel monitoreando

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

**Tipos válidos:**
- `feat:` — nueva funcionalidad
- `fix:` — corrección de bug
- `docs:` — documentación
- `chore:` — mantenimiento (cron, deps)
- `sentinel:` — cambios al container sentinel

### 2.2 PUSH OBLIGATORIO AL FINAL DE SESIÓN

```bash
git push origin main
```

> [!IMPORTANT]
> GitHub Actions lee del repo. Sin push, los cambios no llegan al bot en nube.

---

## 3. 🛡️ SEGURIDAD — REGLAS ABSOLUTAS

| Regla | Acción |
|-------|--------|
| ❌ NUNCA commitear `.env` | Verificar `.gitignore` incluye `.env` |
| ❌ NUNCA escribir tokens en código | Usar `os.getenv()` siempre |
| ❌ NUNCA exponer `TELEGRAM_BOT_TOKEN` en logs | Truncar a primeros 10 chars máx |
| ❌ NUNCA commitear credenciales | `git diff` antes de commit |
| ✅ SIEMPRE usar GitHub Secrets para Actions | No hardcodear en YML |
| ✅ SIEMPRE `.env` para local | `load_dotenv()` en cada script |

**Pre-commit check obligatorio:**
```bash
git diff --staged | grep -i "token\|password\|secret\|api_key"
# Si encuentra algo → DETENER y corregir
```

---

## 4. 🤖 ARQUITECTURA DEL BOT — NO ROMPER

### 4.1 Componentes activos (NO modificar sin entender)

| Archivo | Función | Frecuencia |
|---------|---------|------------|
| `ovc_once.py` | Check principal — 2 capas: Playwright (opt) + Bookitit POST | Cada ~7 min via GH Actions |
| `ovc_burst.py` | Burst mode ventanas críticas — loop 35min × 45s | 2x/día: 11:55 y 21:55 UTC |
| `ovc_heartbeat.py` | "Estoy vivo" — edita mensaje PINNEADO | Cada 4h (UTC 3,9,15,21) |
| `bot/ovc_bot.py` | Bot gestor suscriptores — polling continuo | Permanente, timeout 350min GH Actions |
| `.github/workflows/ovc_monitor.yml` | Cron monitor | `0,7,13,19,26,32,38,44,51,57 * * * *` |
| `.github/workflows/ovc_burst.yml` | Cron burst | `55 11,21 * * *` |
| `.github/workflows/ovc_heartbeat.yml` | Cron heartbeat | `0 3,9,15,21 * * *` |
| `.github/workflows/ovc_bot.yml` | Bot gestor 24/7 | trigger push + manual, timeout 350min |
| `ovc_sentinel/sentinel.py` | Vigilancia local 24/7 | Loop cada 30 min |

> ⛔ **AVC canal ELIMINADO DEFINITIVAMENTE** — compite con el mercado objetivo de OVC.
> NO reintroducir bajo ninguna circunstancia sin autorización explícita del propietario.

### 4.2 Anti-detección — NO revertir estos fixes

| Fix | Archivo | Descripción |
|-----|---------|-------------|
| Sleep aleatorio | `ovc_once.py` L~220 | `random.randint(10, 90)` |
| UA rotativo | `ovc_once.py` L~38 | 6 user-agents reales |
| Viewport random | `ovc_once.py` L~48 | 5 resoluciones |
| Stealth script | `ovc_once.py` L~56 | Oculta `navigator.webdriver` |
| Cron irregular | `ovc_monitor.yml` | Minutos no uniformes |
| Auto-fallback wg0 | `ovc_once.py` | Si WireGuard sin handshake → desactivar |
| AllowAppointment interceptor | `playwright_check.py` | page.on("response") para getservices |
| URL directa citaconsular.es | `playwright_check.py` | NO transformar a app.bookitit.com (IP residencial bypassa) |
| _check_getservices primera capa | `bookitit.py` | AllowAppointment más fiable que bkt_init_widget |

### 4.3 API Bookitit real (descubierta Mar 18 con ovc_spy)

> ⚠️ **NO usar `/onlinebookings/main/` como endpoint primario** — devuelve `bkt_init_widget`
> vacío fabricado por Imperva (soft-block). El endpoint correcto es `getservices/`.

| Endpoint | Descripción | Flag clave |
|----------|-------------|------------|
| `GET /onlinebookings/getwidgetconfigurations/?publickey={PK}` | Config widget | - |
| `GET /onlinebookings/getservices/?publickey={PK}` | Servicios + disponibilidad | `AllowAppointment` |
| `GET /onlinebookings/getagendas/?services[]={SID}` | Agendas del servicio | `Agendas[]` |
| `GET /onlinebookings/getdates/` | Fechas disponibles | `dates[]` |

**LEGA**: PK=`25b6cfa9f112aef4ca19457abc237f7ba` (33 chars), SID=`bkt1180597`

### 4.3 Flujo de alerta (NO romper)

```
citaconsular.es → widget activo
→ ovc_once.py detecta
→ enviar_telegram(con_boton=True)
→ Telegram grupo "OVC Alertas Consulado" (-5127911137)
→ TODOS los miembros reciben simultaneamente
→ Botón ABRIR AHORA → captcha → reservar (ventana: ~2 min)
```

---

## 5. 🐳 SENTINEL CONTAINER — GESTIÓN

### 5.1 El sentinel monitorea

1. **GitHub Actions** — ¿El bot ejecutó en los últimos 60 min? (GH free tiene gaps de ~45 min)
2. **Heartbeat** — ¿Llegó heartbeat en las últimas 5 horas?
3. **Quota GH Actions** — ¿Quedan minutos disponibles?

### 5.2 Comandos del sentinel

```bash
# Iniciar
cd ovc_sentinel && docker-compose up -d

# Ver estado
docker ps | grep ovc-sentinel

# Ver logs
docker logs ovc-sentinel --tail 50 -f

# Detener
docker-compose down

# Rebuild (tras modificar sentinel.py)
docker-compose up -d --build
```

### 5.3 Cuándo hacer rebuild del sentinel

- ✅ Modificar `sentinel.py`
- ✅ Modificar `requirements.txt`
- ✅ Modificar `Dockerfile`
- ❌ No rebuild por cambiar `.env` — basta con `docker-compose restart`

---

## 6. 🔍 VERIFICACIÓN FÍSICA OBLIGATORIA

**Después de cada cambio:**

```bash
# 1. Archivo existe y tiene contenido
ls -lh [archivo modificado]

# 2. Git tracking correcto
git status

# 3. No hay secretos en staging
git diff --staged | grep -i "token\|password\|secret"

# 4. Bot sigue en Actions
gh run list --repo Vcordero1962/ovc-monitor --limit 3
```

**Después de push:**
```bash
# Verificar que GH Actions ejecutó
gh run list --repo Vcordero1962/ovc-monitor --limit 3
# Esperar ~2 min y verificar estado: completed / success
```

---

## 7. 📋 PROTOCOLO DE CIERRE DE SESIÓN

### 7.1 Checklist pre-cierre (OBLIGATORIO)

- [ ] Todos los cambios commiteados
- [ ] `git push origin main` ejecutado
- [ ] Sentinel corriendo: `docker ps | grep ovc-sentinel`
- [ ] Último run GitHub Actions: exitoso
- [ ] `SESSION_SUMMARY_YYYYMMDD.md` creado/actualizado
- [ ] `CLAUDE.md` actualizado si hubo cambios arquitectónicos
- [ ] `GLOBAL_AGENT_RULES_OVC.md` actualizado si hubo nuevas reglas

### 7.2 SESSION SUMMARY — FORMATO OBLIGATORIO

```markdown
# SESIÓN OVC: DD Mes YYYY — [HH:MM - HH:MM]

## 🎯 Objetivo
[Qué se intentaba lograr]

## ✅ Logros
- [Logro 1] — commit: `[hash]`
  - Archivo: `[ruta]`, función: `[nombre]()`
  - Antes: [descripción]
  - Después: [descripción]

## 📁 Archivos modificados
| Archivo | Sección | Cambio |
|---------|---------|--------|
| `ovc_once.py` | `verificar_avc()` | [descripción] |

## 🔨 Commits
- `[hash]` — [mensaje]

## 🤖 Estado Bot al cierre
- GitHub Actions: [OK / ERROR]
- Último run: [hace X min] — [success/failure]
- Sentinel: [corriendo / detenido]
- Último heartbeat: [hace X horas]

## ❌ Pendiente
- [Tarea] — Razón: [por qué quedó]

## 🎯 Próxima sesión — empezar por:
1. [Tarea específica con contexto]

## 🔑 Decisiones técnicas
- [Decisión] → [Razón] → [Alternativas descartadas]

## ⚠️ Alertas
- [Algo roto / pendiente / que requiere atención]
```

---

## 8. 🚫 PROHIBICIONES ABSOLUTAS

- ❌ Modificar `ovc_once.py` sin leerlo primero (Read obligatorio)
- ❌ Commitear `.env` bajo ninguna circunstancia
- ❌ Eliminar los fixes anti-detección
- ❌ Cambiar el `TELEGRAM_CHAT_ID` sin autorización explícita del usuario
- ❌ Borrar workflows de GitHub Actions sin backup
- ❌ Usar `time.sleep()` fijos en el bot (detectable por WAF)
- ❌ Documentar features no implementadas como "completadas"

## 9. ✅ SIEMPRE

- ✅ Leer archivo antes de editar
- ✅ Verificar con `ls` que el archivo existe después de escribir
- ✅ Commit con Co-Authored-By
- ✅ Push al final de sesión
- ✅ Timing aleatorio (Gaussiano / randint) en todo lo que toca el sitio
- ✅ Secretos solo en `.env` y GitHub Secrets
- ✅ Sentinel corriendo al inicio y fin de sesión

---

## 10. 🆘 EMERGENCIAS

### Bot caído (Actions no ejecuta)

```bash
# Verificar últimos runs
gh run list --repo Vcordero1962/ovc-monitor --limit 10

# Lanzar manualmente
gh workflow run ovc_monitor.yml --repo Vcordero1962/ovc-monitor

# Ver logs del run fallido
gh run view <ID> --repo Vcordero1962/ovc-monitor --log
```

### Sentinel caído

```bash
docker logs ovc-sentinel --tail 50  # ver por qué cayó
docker-compose up -d                # reiniciar
```

### Quota GitHub Actions agotada

- Plan free: 2,000 min/mes
- Uso estimado: ~50 min/día × 30 = ~1,500 min/mes (margen OK)
- Si se agota: reducir frecuencia del cron en `ovc_monitor.yml`

---

**Versión:** 2.1
**Activado:** 15 Marzo 2026
**Actualizado:** 18 Marzo 2026
**Compliance Streak:** 🟢 5 sesiones
**Próxima revisión:** Cuando haya cambio arquitectónico significativo

---

## 11. 🚫 REGLA PERMANENTE — CANAL AVC

> [!CRITICAL]
> **NUNCA reintroducir dependencia del canal AVC (t.me/AsesorVirtualC) bajo ninguna forma.**
> Este canal pertenece a un competidor directo del mercado objetivo de OVC.
> Decisión tomada el 16 Marzo 2026 por el propietario del proyecto.
> Aplica a: ovc_once.py, ovc_burst.py, ovc_monitor.py, cualquier archivo nuevo.
