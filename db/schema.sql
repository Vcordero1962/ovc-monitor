-- ============================================================
-- OVC — Esquema PostgreSQL (Neon.tech)
-- Ejecutar una sola vez al crear el proyecto
-- ============================================================

-- ── Extensiones ──────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- ── Tabla: usuarios ──────────────────────────────────────────
-- Un registro por persona que habla con el bot gestor
CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT  UNIQUE NOT NULL,          -- chat_id del usuario en Telegram
    telegram_user   VARCHAR(100),                      -- @username (puede ser NULL)
    nombre          VARCHAR(150),                      -- nombre que dio al registrarse
    whatsapp_phone  VARCHAR(20),                       -- para futuro push WhatsApp
    plan            VARCHAR(20)  NOT NULL DEFAULT 'free',  -- free | directo | premium
    servicios       TEXT[]       NOT NULL DEFAULT '{}',    -- ['LEGA','LMD','PASAPORTE',...]
    activo          BOOLEAN      NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Tabla: suscripciones ─────────────────────────────────────
-- Historial de pagos y activaciones manuales por el admin
CREATE TABLE IF NOT EXISTS suscripciones (
    id              SERIAL PRIMARY KEY,
    usuario_id      INTEGER      NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    plan            VARCHAR(20)  NOT NULL,             -- directo | premium
    precio_usd      NUMERIC(6,2),                      -- lo que pagó (puede ser 0 en pruebas)
    metodo_pago     VARCHAR(30),                       -- zelle | paypal | efectivo | cortesia
    referencia      VARCHAR(100),                      -- confirmación de pago opcional
    activado_por    BIGINT,                            -- telegram_id del admin que activó
    dias            INTEGER      NOT NULL DEFAULT 90,  -- duración en días
    fecha_inicio    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    fecha_expira    TIMESTAMPTZ  NOT NULL DEFAULT NOW() + INTERVAL '90 days',
    activa          BOOLEAN      NOT NULL DEFAULT true,
    notas           TEXT                               -- notas internas del admin
);

-- ── Tabla: alertas_log ───────────────────────────────────────
-- Registro de cada alerta detectada y enviada (evita duplicados)
CREATE TABLE IF NOT EXISTS alertas_log (
    id              SERIAL PRIMARY KEY,
    tramite         VARCHAR(20)  NOT NULL,
    fuente          VARCHAR(20)  NOT NULL,             -- sitio | bookitit | avc
    detectado_en    TIMESTAMPTZ  NOT NULL,
    canal_publico   BOOLEAN      NOT NULL DEFAULT false,
    usuarios_dm     INTEGER      NOT NULL DEFAULT 0,   -- cuántos DMs se enviaron
    hash_contenido  VARCHAR(64),                       -- hash del texto detectado (dedup)
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Tabla: admin_audit ───────────────────────────────────────
-- Log inmutable de cada acción del administrador
CREATE TABLE IF NOT EXISTS admin_audit (
    id              SERIAL PRIMARY KEY,
    admin_tg_id     BIGINT       NOT NULL,
    comando         VARCHAR(50)  NOT NULL,             -- /admin_activar, /admin_broadcast ...
    target_tg_id    BIGINT,                            -- usuario afectado (si aplica)
    detalle         TEXT,                              -- parámetros del comando
    ejecutado_en    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Tabla: watermarks ────────────────────────────────────────
-- Asocia cada alerta enviada a su suscriptor (trazabilidad de filtraciones)
CREATE TABLE IF NOT EXISTS watermarks (
    id              SERIAL PRIMARY KEY,
    alerta_id       INTEGER      NOT NULL REFERENCES alertas_log(id),
    usuario_id      INTEGER      NOT NULL REFERENCES usuarios(id),
    wm_code         VARCHAR(32)  NOT NULL,             -- código único por envío
    enviado_en      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Índices ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_usuarios_telegram_id  ON usuarios(telegram_id);
CREATE INDEX IF NOT EXISTS idx_suscripciones_activa  ON suscripciones(activa, fecha_expira);
CREATE INDEX IF NOT EXISTS idx_alertas_tramite        ON alertas_log(tramite, detectado_en);
CREATE INDEX IF NOT EXISTS idx_watermarks_wm_code     ON watermarks(wm_code);

-- ── Vista: suscriptores_activos ───────────────────────────────
-- Suscriptores con plan vigente en este momento
CREATE OR REPLACE VIEW suscriptores_activos AS
SELECT
    u.id,
    u.telegram_id,
    u.telegram_user,
    u.nombre,
    u.plan,
    u.servicios,
    u.whatsapp_phone,
    s.fecha_expira,
    s.plan AS plan_suscripcion
FROM usuarios u
JOIN suscripciones s ON s.usuario_id = u.id
WHERE s.activa = true
  AND s.fecha_expira > NOW()
  AND u.activo = true;

-- ── Función: expirar suscripciones vencidas ─────────────────
-- Se puede llamar desde el bot periódicamente
CREATE OR REPLACE FUNCTION expirar_suscripciones_vencidas()
RETURNS INTEGER AS $$
DECLARE
    filas INTEGER;
BEGIN
    UPDATE suscripciones
       SET activa = false
     WHERE activa = true
       AND fecha_expira <= NOW();
    GET DIAGNOSTICS filas = ROW_COUNT;

    -- Degradar usuario a free si no tiene otra suscripción activa
    UPDATE usuarios u
       SET plan = 'free', updated_at = NOW()
     WHERE plan <> 'free'
       AND NOT EXISTS (
           SELECT 1 FROM suscripciones s
            WHERE s.usuario_id = u.id
              AND s.activa = true
              AND s.fecha_expira > NOW()
       );

    RETURN filas;
END;
$$ LANGUAGE plpgsql;
