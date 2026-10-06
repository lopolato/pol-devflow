# lite

Objetivo: resolver una tarea pequeña y clara (error o feature) con un modelo ligero y sin el procedimiento completo, manteniendo la seguridad Git y las pruebas reales. El Coordinator solo elige nivel, crea la rama, delega y verifica.

## Elegir el nivel

`--lite` o `--full` fuerzan el nivel. Sin flag, el Coordinator propone uno y lo justifica en una línea. Lite solo si se cumple todo:

- el cambio está claro y se sabe qué tocar sin investigación amplia;
- afecta a 3 archivos de producto (incluidos tests) como máximo;
- no toca permisos, seguridad, reglas de negocio relevantes, migraciones, datos ni concurrencia;
- el modo es error o feature (optimize siempre es full);
- el checkout está limpio, salvo archivos sin seguimiento ajenos a la tarea. Con modificaciones de archivos versionados, usar full o preguntar.

Si el usuario fuerza `--lite` y no se cumple una condición, explicar cuál y proponer full; no seguir en lite. Plan-only se detiene antes de crear la rama.

## Pasos del Coordinator

1. Preflight breve: instrucciones del proyecto, `git status`, criterios y archivos previstos. Preguntar solo decisiones relevantes de producto. Ejecutar `_profile show`: si existe y no está `stale`, usar sus comandos; si falta o está obsoleto, pol-lite los descubre. No leer [memoria del proyecto](../rules/project-memory.md); solo comprobar si está activada: existe `docs/devflow/`, las instrucciones del proyecto la piden o el usuario la solicita ahora.
2. Crear la rama en la carpeta actual, sin worktree:
   `python scripts/devflow.py --repo PROJECT _lite start --mode error|feature --request DESCRIPTION`
   El helper exige checkout limpio salvo untracked, nunca escribe en main/master y registra la rama para `cleanup`. Devuelve `untracked_preserved` e `identity`; si esta trae `warning`, resolver el autor según [Git](../rules/git-worktrees.md).
3. Delegar en `pol-lite`: petición, criterios, carpeta, rama, revisión base, scope de producto, `untracked_preserved` como "no tocar ni confirmar", autor si se resolvió, comprobaciones (comandos del perfil si existen) y ruta de esta skill. Solo con memoria activada, añadir la ruta del informe y hasta 2 documentos/memoria afectados; sin activación no hay informe ni memoria en el repositorio. El Coordinator no implementa salvo en native si el runtime no tiene workers; entonces avisar de que se usa el modelo de la sesión.
4. Verificar con Git: rama, commit, archivos cambiados dentro de los límites y checkout limpio. No aceptar `done` sin comprobaciones ejecutadas en el commit final. Guardar en el perfil los comandos que pol-lite ejecutó (`_profile set`) y registrar su uso real con `_metrics add --lite ID --role lite [--owner SESSION]`.

## Orca

Solo si se solicita Orca o la sesión Orca está comprobada en esta invocación, leer el apartado lite del [adaptador Orca](../../adapters/orca/README.md); sustituye al launcher native. En resumen: `_lite start` con `--executor orca --owner SESSION`; lanzar el contrato lite por worker-start con el modelo lite elegido o herencia, verificando el modelo efectivo; registrar `_lite link|settle|account` y resolver liberación o retención acreditada antes de cerrar o escalar. Sin ese accounting `cleanup` no retira la rama. Si Orca no permite lanzar el worker, bloquear y explicar el error.

## Pasar a full

Si el worker devuelve `escalate`, o se detecta una condición de full, confirmar el trabajo útil con el helper de commit (marcado como incompleto), explicar el motivo al usuario y continuar en full sobre la misma rama:

`python scripts/devflow.py --repo PROJECT _run start --mode MODE --request DESCRIPTION --criterion CRITERION --runtime RUNTIME --owner SESSION_ID --reuse-branch RAMA_LITE`

En Orca añadir `--executor orca` y liquidar antes el intento lite; nunca relanzar por timeout.

## Resumen final

```text
DEVFLOW LITE RESULT
Estado: done | partial | escalated | blocked
Rama / commit:
Cambios y comprobaciones (comando y resultado):
Modelos: pol-lite (configurado / efectivo o no verificado) y Coordinator (modelo de la sesión, solo preflight y verificación):
Informe en repositorio (solo con memoria activada) / Orca IDs y accounting (si aplica):
Siguiente paso: revisar y mezclar la rama; después, `cleanup` la retira.
```

Context7 solo ante una duda real de API/versión, según [contexto técnico](../rules/technical-context.md). Lite no hace push, merge ni PR, y no sustituye a una revisión independiente: si se exige, usar full.
