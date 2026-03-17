# db/ — Capa de acceso a datos OVC (Neon PostgreSQL)
from .connection    import get_conn, test_connection
from .usuarios      import (
    registrar_usuario, obtener_usuario, actualizar_servicios,
    listar_suscriptores_para_tramite, desactivar_usuario,
)
from .suscripciones import (
    activar_suscripcion, listar_activas, listar_por_expirar,
    contar_por_plan, ingresos_estimados, expirar_vencidas,
)

__all__ = [
    "get_conn", "test_connection",
    "registrar_usuario", "obtener_usuario", "actualizar_servicios",
    "listar_suscriptores_para_tramite", "desactivar_usuario",
    "activar_suscripcion", "listar_activas", "listar_por_expirar",
    "contar_por_plan", "ingresos_estimados", "expirar_vencidas",
]
