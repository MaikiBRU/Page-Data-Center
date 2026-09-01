#!/usr/bin/env bash
#
# Despliega el backend en la instancia EC2.
#
# Se ejecuta EN el servidor, desde el directorio de la aplicacion. Desde tu
# maquina:
#
#   ssh -i <clave>.pem ubuntu@<host>
#   cd ~/data-center
#   ./scripts/deploy-backend.sh
#
# Que hace, en orden:
#   1. comprueba el directorio, docker-compose.prod.yml y .env.prod;
#   2. respalda la base de datos ANTES de tocar nada;
#   3. trae el commit nuevo;
#   4. reconstruye la imagen de la API;
#   5. levanta el contenedor (el entrypoint corre `alembic upgrade head`);
#   6. espera a que /health responda y verifica el endurecimiento.
#
# Si cualquier paso falla el script se detiene. El respaldo del paso 2 queda en
# ~/backups y es lo que te permite volver atras.
#
# NO borra datos, no recrea la base y no hace DROP en ningun momento. Las
# migraciones 0002 y 0003 son puramente aditivas: crean tablas y agregan
# columnas anulables, todas comprobando antes el catalogo, asi que se pueden
# reejecutar sin efecto.

set -euo pipefail

RAMA="${RAMA:-codex/public-clean}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
SERVICIO_API="${SERVICIO_API:-api}"
SERVICIO_DB="${SERVICIO_DB:-db}"
DIR_BACKUPS="${DIR_BACKUPS:-$HOME/backups}"

# Todo pasa por el compose de produccion y su env file. El
# docker-compose.yml de la raiz solo define la base para desarrollo local.
dc() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

rojo() { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
paso() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# --- 1. comprobaciones previas ---------------------------------------------
paso "Comprobaciones previas"

if [ ! -f "$COMPOSE_FILE" ]; then
  rojo "No se encuentra $COMPOSE_FILE. Ejecutalo desde ~/data-center."
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  rojo "Falta $ENV_FILE. El backend no arranca sin SECRET_KEY."
  exit 1
fi

if ! grep -q '^SECRET_KEY=.\+' "$ENV_FILE"; then
  rojo "SECRET_KEY esta vacia o ausente en $ENV_FILE."
  exit 1
fi

if ! grep -q '^ENVIRONMENT=production' "$ENV_FILE"; then
  rojo "ENVIRONMENT no es 'production' en $ENV_FILE."
  rojo "Fuera de produccion se sirven /docs y /openapi.json publicamente."
  exit 1
fi

verde "Directorio, $ENV_FILE, SECRET_KEY y ENVIRONMENT correctos."

# --- 2. respaldo ------------------------------------------------------------
paso "Respaldo de la base de datos"

mkdir -p "$DIR_BACKUPS"
SELLO="$(date +%Y%m%d-%H%M%S)"
ARCHIVO="$DIR_BACKUPS/data_quality-$SELLO.sql.gz"

# El usuario y la base salen del propio contenedor, no de valores adivinados.
USUARIO_DB="$(dc exec -T "$SERVICIO_DB" printenv POSTGRES_USER | tr -d '\r')"
NOMBRE_DB="$(dc exec -T "$SERVICIO_DB" printenv POSTGRES_DB | tr -d '\r')"

dc exec -T "$SERVICIO_DB" pg_dump -U "$USUARIO_DB" "$NOMBRE_DB" | gzip > "$ARCHIVO"

TAM="$(du -h "$ARCHIVO" | cut -f1)"
if [ ! -s "$ARCHIVO" ]; then
  rojo "El respaldo salio vacio. Se aborta antes de tocar nada."
  exit 1
fi
verde "Respaldo: $ARCHIVO ($TAM)"

# Deja solo los 10 respaldos mas recientes.
ls -1t "$DIR_BACKUPS"/data_quality-*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm --

# --- 3. traer el codigo -----------------------------------------------------
paso "Trayendo $RAMA"

ANTES="$(git rev-parse --short HEAD)"
git fetch --quiet origin "$RAMA"
git checkout --quiet "$RAMA"
git reset --hard --quiet "origin/$RAMA"
DESPUES="$(git rev-parse --short HEAD)"

verde "$ANTES -> $DESPUES"
git log --oneline -1

# --- 4. construir -----------------------------------------------------------
paso "Construyendo la imagen de la API"
dc build "$SERVICIO_API"

# --- 5. levantar ------------------------------------------------------------
# El entrypoint corre `alembic upgrade head` antes de uvicorn. Si una migracion
# falla, el contenedor no arranca y la version anterior sigue en pie.
paso "Levantando la API (aplica migraciones al arrancar)"
dc up -d "$SERVICIO_API"

# --- 6. verificar -----------------------------------------------------------
paso "Verificando"

echo "Esperando a /health ..."
OK=""
for intento in $(seq 1 30); do
  CODIGO="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health || echo 000)"
  if [ "$CODIGO" = "200" ]; then OK="si"; break; fi
  sleep 2
done

if [ -z "$OK" ]; then
  rojo "/health no respondio 200. Ultimos registros:"
  dc logs --tail 40 "$SERVICIO_API"
  rojo ""
  rojo "La version anterior quedo detenida. Para volver atras:"
  rojo "  git reset --hard $ANTES && ./scripts/deploy-backend.sh"
  rojo "Y si hiciera falta restaurar datos:"
  rojo "  gunzip -c $ARCHIVO | docker compose -f $COMPOSE_FILE --env-file $ENV_FILE exec -T $SERVICIO_DB psql -U $USUARIO_DB $NOMBRE_DB"
  exit 1
fi
verde "/health responde 200."

echo ""
echo "Revision de Alembic aplicada:"
dc exec -T "$SERVICIO_API" alembic current 2>/dev/null | tail -2 || true

echo ""
echo "Endurecimiento (en produccion la documentacion no debe servirse):"
FALLOS=0
for ruta in /docs /redoc /openapi.json; do
  CODIGO="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8000$ruta" || echo 000)"
  if [ "$CODIGO" = "404" ]; then
    printf '  %-16s %s cerrado\n' "$ruta" "$CODIGO"
  else
    printf '  %-16s %s ' "$ruta" "$CODIGO"; rojo "EXPUESTO"
    FALLOS=$((FALLOS + 1))
  fi
done

CODIGO="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/auth/register || echo 000)"
if [ "$CODIGO" = "404" ]; then
  printf '  %-16s %s eliminado\n' "/auth/register" "$CODIGO"
else
  printf '  %-16s %s ' "/auth/register" "$CODIGO"; rojo "SIGUE ABIERTO"
  FALLOS=$((FALLOS + 1))
fi

echo ""
if [ "$FALLOS" -gt 0 ]; then
  rojo "El despliegue arranco pero $FALLOS comprobacion(es) de seguridad fallaron."
  rojo "Revisa ENVIRONMENT=production en $ENV_FILE y reinicia: ./scripts/deploy-backend.sh"
  exit 1
fi

verde "Despliegue correcto en $DESPUES. Respaldo previo: $ARCHIVO"
