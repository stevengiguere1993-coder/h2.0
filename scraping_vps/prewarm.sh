#!/bin/sh
# Pré-chauffage de Kratos (Render Free) avant les routines Claude du matin.
#
# Phil 2026-10-13 : sa routine claude.ai lit Kratos chaque matin par le
# connecteur MCP et répondait depuis un mois « le connecteur n'était pas
# activé dans la tâche ». Cause : Render Free met l'API et le site en
# veille après 15 min sans trafic, réveil ~1 min — trop long pour
# l'initialisation du connecteur au démarrage de la routine. La nuit,
# personne ne visite Kratos → il dort au moment de la routine.
#
# Ce script tourne en boucle dans un conteneur minuscule sur le VPS
# Hetzner (toujours allumé, voir docker-compose.yml, service `prewarm`) :
# toutes les PREWARM_INTERVAL secondes, si l'heure UTC est dans la fenêtre
# [PREWARM_FROM_UTC, PREWARM_TO_UTC), il pingue
#   • immohorizon.com/api/v1/ping  (Cloudflare → Next.js → API : réveille
#     le site ET l'API — le connecteur peut passer par l'un ou l'autre) ;
#   • h2-0.onrender.com/health     (API directe).
# Fenêtre par défaut 09:00–13:59 UTC = 05–09 h à Montréal (heure avancée)
# ou 04–08 h (heure normale). Pas de ping le reste de la journée : les
# 750 h gratuites mensuelles de Render sont PARTAGÉES par tous les
# services free du compte ; garder 2 services éveillés 24 h/24 les
# suspendrait avant la fin du mois. Pour supprimer la veille pour de bon :
# plan Render Starter.
#
# Journal : `docker logs horizon-prewarm` sur le VPS.

# 2026-10-15 : cause racine confirmée (48,7 s de réveil mesurés sur le
# frontend de staging) et la fenêtre commençait À L'HEURE de la routine
# (09:00 UTC) → elle commence maintenant 1 h avant (08:00 UTC = 04 h
# Montréal à l'heure avancée, 03 h à l'heure normale) et dure jusqu'à
# 14:59 UTC, toutes les 4 min. On pingue aussi le chemin MCP exact que le
# connecteur appelle (401 attendu : la clé n'est pas ici) pour réveiller
# toute la chaîne. Un réveil à froid (> 5 s) est signalé dans le journal.
FROM_UTC="${PREWARM_FROM_UTC:-8}"
TO_UTC="${PREWARM_TO_UTC:-15}"
INTERVAL="${PREWARM_INTERVAL:-240}"

echo "$(date -u +%FT%TZ) prewarm démarré — fenêtre ${FROM_UTC}h–${TO_UTC}h UTC, toutes les ${INTERVAL}s"
while true; do
  h=$(date -u +%H)
  h=${h#0}
  if [ "$h" -ge "$FROM_UTC" ] && [ "$h" -lt "$TO_UTC" ]; then
    a=$(curl -sS -o /dev/null -w '%{http_code} %{time_total}s' --max-time 90 https://immohorizon.com/api/v1/ping 2>&1 || true)
    b=$(curl -sS -o /dev/null -w '%{http_code} %{time_total}s' --max-time 90 https://h2-0.onrender.com/health 2>&1 || true)
    c=$(curl -sS -o /dev/null -w '%{http_code} %{time_total}s' --max-time 90 https://h2-0.onrender.com/api/v1/mcp/prewarm 2>&1 || true)
    d=$(curl -sS -o /dev/null -w '%{http_code} %{time_total}s' --max-time 90 https://immohorizon.com/api/v1/mcp/prewarm 2>&1 || true)
    marque=""
    for x in "$a" "$b" "$c" "$d"; do
      t=${x#* }; t=${t%s}; t=${t%%.*}
      case "$t" in ''|*[!0-9]*) ;; *) [ "$t" -ge 5 ] && marque="  ⚠ RÉVEIL À FROID" ;; esac
    done
    echo "$(date -u +%FT%TZ) site+api=$a  api=$b  mcp-api=$c  mcp-site=$d$marque"
  fi
  sleep "$INTERVAL"
done
