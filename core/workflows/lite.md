# lite

Objetivo: resolver una tarea pequeña y clara (error o feature) con un modelo ligero y sin el procedimiento completo, manteniendo la seguridad Git y las pruebas reales. El Coordinator solo elige nivel, crea la rama, delega y verifica.

## Elegir el nivel

`--lite` o `--full` fuerzan el nivel; `--review` pide revisión independiente (`--lite --review` = lite+review, `--full --review` = full con review, solo `--review` = nivel automático con review). Sin flag de nivel, el Coordinator decide por riesgo y comprensión (el número de archivos es solo una pista) y justifica el nivel en una línea; si ninguna pregunta lleva a otro nivel, lite:

1. ¿Riesgo alto? Permisos/accesos/seguridad; dinero (importes, IVA, facturas, cobros, pagos); comunicaciones a clientes (correos, recordatorios, notificaciones); datos (migraciones, borrados, cambios de estructura); concurrencia o tareas automáticas/programadas. Nunca lite sin review: lite+review si por lo demás es pequeño y se entiende; full con migraciones, cambios de datos, concurrencia o trabajo amplio.
2. ¿Se entiende sin investigación amplia? Si no, full (o explorer primero). Muchos archivos obligan a revisar esta pregunta, nunca deciden por sí solos.
3. ¿Hay dos o más partes independientes que pueden escribir workers distintos? Si sí, full.

Lite exige además modo error o feature (optimize siempre es full y no admite `--review`) y checkout limpio salvo archivos sin seguimiento ajenos a la tarea (con versionados modificados, usar full o preguntar). Si el usuario/proyecto pide review, lite+review. Si el usuario fuerza `--lite` y no cabe, explicar por qué y proponer lite+review o full; no seguir en lite. Plan-only se detiene antes de crear la rama.

## Pasos del Coordinator

1. Preflight breve: instrucciones del proyecto, `git status`, criterios y archivos previstos. Preguntar solo decisiones relevantes de producto. En lite+review, anotar las lentes de riesgo que toca (requirements, security, money, communications, data, concurrency, tests). No leer [memoria del proyecto](../rules/project-memory.md); solo comprobar si está activada: existe `docs/devflow/`, las instrucciones del proyecto la piden o el usuario la solicita ahora.
2. Crear la rama en la carpeta actual, sin worktree:
   `python scripts/devflow.py --repo PROJECT _lite start --mode error|feature --request DESCRIPTION [--request-file FILE] [--review] --executor EXECUTOR`
   El helper exige checkout limpio salvo untracked, nunca escribe en main/master y registra la rama para `cleanup`. `--request` es el título; `--request-file` guarda el mensaje literal del usuario (sin él se guarda `--request`). Devuelve `request_ref`, `untracked_preserved` (muestra de hasta 20 rutas) con `untracked_preserved_count`, `session_model_hint` e `identity`; si esta trae `warning`, resolver el autor según [Git](../rules/git-worktrees.md).
3. Delegar en `pol-lite`: `request_ref` (la petición literal; nunca sustituirla por una paráfrasis), `context.python` si existe (intérprete del proyecto para tests y scripts), criterios, carpeta, rama, revisión base, write scope asignado (rutas de producto y tests), `untracked_preserved` como "no tocar ni confirmar" (si `untracked_preserved_count` es mayor, indicar que ningún archivo sin seguimiento se confirma), autor si se resolvió, comprobaciones y ruta de esta skill. Usar el `context` de `_lite start`: comandos de `context.profile` si no está `stale` (si faltan, pol-lite los descubre), su `codegraph.project_path` y, si `rules_count` > 0, las reglas de `_rules for --path P` para los archivos previstos como límites; en lite+review, también las lentes. Solo con memoria activada, añadir la ruta del informe y hasta 2 documentos/memoria afectados; sin activación no hay informe ni memoria en el repositorio. Usar la API nativa comprobada del anfitrión (Codex o Claude), salvo petición explícita Orca o falta de API nativa; en ese caso comprobar Orca en vivo. No simular workers con subprocessos o pegado TUI. Si no hay backend disponible, informar bloqueo.
4. Verificar con Git: rama, commit, archivos cambiados dentro del scope asignado y checkout limpio. No aceptar `done` sin comprobaciones ejecutadas en el commit final. Guardar en el perfil los comandos que pol-lite ejecutó (`_profile set`) y registrar su uso real con `_metrics add --lite ID --role lite [--owner SESSION]` y las funciones que el CLI no ve con `_metrics feature --lite ID --name NAME [--owner SESSION]`. En un error corregido con test de regresión, proponer la regla `must_not` como en [error](error.md).
5. Solo lite+review: `_lite review-diff --lite ID --author-id LITE_WORKER_ID` genera el diff con hash. Lanzar `pol-reviewer` (distinto del autor y del Coordinator) con la ruta del diff, los criterios y las lentes, pidiendo revisar solo esas (más blockers evidentes) y nombrarlas en su cobertura; guardar su JSON {worker_id, verdict passed|changes_required|incomplete, revision, findings} con `_lite review --lite ID --input FILE`. Con changes_required, enviar los blockers aceptados a pol-lite para una corrección con commit y repetir review-diff y review. Si `_lite review` devuelve `escalate` (tercer changes_required), pasar a full. No hay `done` sin `review_current: true` en `_lite status --lite ID`.
6. Cerrar siempre el registro antes del resumen: `_lite finish --lite ID [--owner SESSION]` (completed; exige commits y, en lite+review, revisión vigente) o `--status partial|cancelled --reason TEXTO`. Si la rama ya se mezcló y borró, `--revision SHA` con el commit final. Sin cierre, `stats` lo cuenta como pendiente y sin duración.

## Orca

Elegir `EXECUTOR` antes de iniciar: native por defecto con API anfitriona comprobada, también en una sesión Orca. Una petición explícita de workers Orca o ausencia de API nativa exige preflight vivo y el apartado lite del [adaptador Orca](../../adapters/orca/README.md); entonces sustituye al launcher native. No cambiar executor en silencio durante un run. En resumen: `_lite start` con `--executor orca --owner SESSION`; lanzar el contrato lite por worker-start con el modelo lite elegido o herencia, verificando el modelo efectivo; registrar `_lite link|settle|account` y resolver liberación o retención acreditada antes de cerrar o escalar. Sin ese accounting `cleanup` no retira la rama. Si Orca no permite lanzar el worker, bloquear y explicar el error. Los workspaces Orca siguen gestionados por Orca aunque EXECUTOR sea native; no crear Tasks/Dispatches ni settlement Orca para workers nativos.

## Pasar a full

Si el worker devuelve `escalate`, o se detecta una condición de full, confirmar el trabajo útil con el helper de commit (marcado como incompleto), explicar el motivo al usuario y continuar en full sobre la misma rama:

`python scripts/devflow.py --repo PROJECT _run start --mode MODE --request DESCRIPTION --request-file FILE --criterion CRITERION --runtime RUNTIME --owner SESSION_ID --reuse-branch RAMA_LITE`

Conservar el executor del registro lite al pasar a full y pasar como `--request-file` la ruta de `request_ref`. Con executor orca añadir `--executor orca` y liquidar antes el intento lite; nunca relanzar por timeout. `--runtime` identifica el anfitrión codex/claude, no el executor.

## Resumen final

```text
DEVFLOW LITE RESULT
Estado: done | partial | escalated | blocked
Rama / commit:
Cambios y comprobaciones (comando y resultado):
Review (lite+review): veredicto, reviewer y revisión revisada:
Modelos: pol-lite (configurado / efectivo o no verificado) y Coordinator (modelo de la sesión, solo preflight y verificación):
Informe en repositorio (solo con memoria activada) / Orca IDs y accounting (si aplica):
Siguiente paso: revisar y mezclar la rama; después, `cleanup` la retira.
```

Al cerrar, retro optativa de ≤3 líneas: `_retro add --lite ID [--owner SESSION] --input FILE` (ver [procedimiento](../coordinator.md)); nunca bloquea.

Context7 solo ante una duda real de API/versión, según [contexto técnico](../rules/technical-context.md). Lite no hace push, merge ni PR. Sin `--review` no acredita revisión independiente: si se exige, usar lite+review o full. Si `session_model_hint` indica un modelo pesado en la sesión, sugerir una vez en el resumen un modelo ligero para la próxima vez; nunca bloquea ni se repite.
