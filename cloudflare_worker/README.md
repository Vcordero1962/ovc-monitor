# OVC Cloudflare Worker — Relay (Backup Plan)

## Cuándo usar esto

Solo si `app.bookitit.com/onlinebookings/main/` también está protegido por Imperva
y devuelve datos vacíos desde IPs de GitHub Actions.

## Deploy (5 minutos, gratis)

1. Ir a https://dash.cloudflare.com
2. Workers & Pages → Create → Create Worker
3. Borrar el código de ejemplo, pegar `worker.js`
4. Configurar secret: Settings → Variables → `OVC_SECRET` = cualquier string
5. Deploy → copiar la URL: `https://ovc-relay.TU-USUARIO.workers.dev`

## Integrar en bookitit.py

Añadir en `core/config.py`:
```
CLOUDFLARE_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "")
OVC_SECRET            = os.getenv("OVC_WORKER_SECRET", "")
```

Y en `core/bookitit.py`, dentro de `_check_directo()`, añadir Variante D:
```python
# Variante D — via Cloudflare Worker relay
if CLOUDFLARE_WORKER_URL:
    worker_url = f"{CLOUDFLARE_WORKER_URL}?pk={pk}&sid={sid}&secret={OVC_SECRET}"
    r = requests.get(worker_url, timeout=20)
    # misma lógica de parseo bkt_init_widget
```

Añadir en el workflow:
```yaml
CLOUDFLARE_WORKER_URL: ${{ secrets.CLOUDFLARE_WORKER_URL }}
OVC_WORKER_SECRET:     ${{ secrets.OVC_WORKER_SECRET }}
```

## Por qué funciona

Cloudflare Workers corren en los edge nodes de CF (IPs 104.x.x.x).
Imperva y Cloudflare son competidores directos — CF no está en la lista negra
de datacenter IPs de Imperva. Además, Workers ejecutan V8 real (mismo motor
que Chrome) por lo que pueden resolver JS challenges de Imperva si aparecen.

Free tier: 100,000 requests/día. A 48 checks/día = 0.05% del límite.
