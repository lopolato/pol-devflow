# Comprobación de Pol DevFlow (historial 1.0.5–1.0.10)

Actualización del 5 de octubre de 2026: adaptador local Orca Build, Context7 selectivo y lite proporcional. Engram queda fuera.

## Cambios y comprobaciones

- Orca conserva autoridad sobre Run/Task/Dispatch y actividad. El helper genera encargos autocontenidos y registra evidencia contrastada de vínculo, settlement y accounting; no lanza procesos ni autentica recibos.
- Lecturas independientes en olas sobre la misma revisión; escritores secuenciales. Git, scopes, criterios y revisión independiente siguen vigentes.
- Identidad estable del agente, validación del último intento en retries sucesivos, recuperación positiva sin fabricar worker_done, reutilización posterior al settlement y prohibición de inyectar finalización desde LINK_JSON.
- Reconciliación de settlement/accounting de runs parciales sin reabrirlos. Cleanup protege evidencia Orca pendiente también en lite, incluso con purga explícita.
- Orca hereda sin configuración central ni perfiles gestionados previos. Captura preferencias instaladas únicamente con hash verificado; nunca configura el modelo de Coordinator.
- Context7 por necesidad, dependencia instalada y documentación compatible. Compartir extractos relevantes; fallback oficial/local si no está disponible. No instalar MCPs incidentalmente.
- Lite admite hasta tres archivos de producto, un informe y dos documentos/memoria afectados con scope explícito. Usa registro mínimo Orca con link/settle/account y registra liberación, retención solicitada o retención `user_takeover` acreditada por Orca antes de escalar.

## Evidencia

- Suite general: 95 casos, 94 aprobados y 1 omitido por permisos de enlaces simbólicos en Windows (184,126 s).
- Después de la última corrección de claves reservadas y protección de tareas aún sin enlace: 21 pruebas Orca aprobadas (47,232 s), incluido el nuevo caso de inyección. Este caso es adicional a los 95 de la pasada general.
- Cobertura Orca: olas/native secuencial, identidad/revisión/outcomes, specs de lectura, preferencias gestionadas y herencia, arranque limpio sin worktree extra, Context7 compartido, retries sucesivos, recuperación positiva, accounting, cierre parcial, protección lite y rechazo de claves reservadas.
- Una pasada intermedia falló por un WinError 5 al reemplazar un archivo temporal; las pasadas finales anteriores completaron sin ese fallo.

El validador propio del paquete dio healthy, nueve perfiles y ocho workers por runtime, con referencias internas comprobadas. La evaluación independiente de lectura detectó y motivó correcciones de retries, recuperación, reutilización y claves reservadas del enlace. Los tres casos de recuperación fallaron antes de corregirlos. No se ejecutaron workers reales en la evaluación.

El validador quick_validate de skill-creator sigue sin ejecutarse en este intérprete por falta de PyYAML; no se instaló una dependencia para suplirlo.

## Actualización local y límites

La actualización conserva configuración central y modelos/esfuerzos/frontmatter de los dieciséis perfiles instalados, reemplaza únicamente instrucciones gestionadas y valida hashes/metadatos. Ambos runtimes reciben backup transaccional.

No se ha probado todavía un workflow completo con workers Orca reales en un proyecto real. El puente inicial admite ejecución local; remoto/WSL y escritores paralelos en worktrees separados quedan pendientes. Sus JSON son declaraciones contrastadas por Coordinator, no autenticación automática. La veracidad semántica de memoria/documentación continúa bajo Coordinator/Reviewer. Context7 requiere acceso efectivo a sus herramientas; la skill no configura ese MCP.

Si un arranque lite Orca queda sin recibo, conserva su registro protegido: ausencia de enlace no prueba ausencia de recursos. Reconciliar con la guía Orca; el helper no abandona ni limpia recursos inciertos automáticamente.

## Repetir

### Ajuste local de retención de Orca — 05/10/2026

Se distingue la petición explícita de conservar una sesión de la retención que decide Orca. El helper acepta `action: retained`, `retention_source: orca` y un `orca_release_result` del mismo Dispatch con `state: retained`, `reason: user_takeover` y `processAction: none`, siempre después de settlement y con evidencia. No inventa una petición del usuario, no cierra procesos y no cambia el resultado del producto. Los recibos pendientes, inciertos o de otra sesión siguen rechazados; otros motivos de retención quedan fuera de esta excepción.

Las dos pruebas nuevas de aceptación fallaron antes del cambio con `Retention requires an explicit user request`. Después pasaron seis pruebas de retención y las 22 pruebas del adaptador Orca, incluida la persistencia real del accounting lite mediante el CLI en un repositorio temporal (28 pruebas en total). El validador del paquete devuelve healthy y `quick_validate.py` de skill-creator devuelve `Skill is valid!`. La validación cubre los helpers y las instrucciones, sin lanzar nuevos workers ni modificar Orca. El ajuste está sincronizado en las copias locales de Codex y Claude: ambas pasan 28 pruebas del adaptador y retención, y el validador propio devuelve healthy. Se conservan modelos y metadatos de cada runtime. quick_validate valida la copia Codex y el contenido portable de Claude en una carpeta temporal; su ejecución directa sobre Claude rechaza las claves nativas argument-hint y disable-model-invocation, que se mantienen en la instalación.

```text
python -m unittest discover -s tests -v
python scripts/validate.py
```

## 1.0.6 · Cierre y limpieza · 05/10/2026

Regresiones reproducidas con Git temporal: workspace Orca omitido del inventario, rama principal abierta dentro del workspace, borrado remoto no solicitado y pérdida de respuesta tras retirada del worktree. Se añadieron diez pruebas: registro de propiedad/inactividad, reconciliación de transporte, preservación de rama protegida, rechazo del checkout principal, borrado remoto optativo y retención de evidencia, revisión remota sin integrar, cambios locales, identidad Orca ausente, remoto desconocido y rama ya eliminada por Orca. Las pruebas iniciales fallaron por ausencia del registro de propiedad; las diez pasan tras implementar los helpers. Git y el remoto bare son reales en carpetas temporales; el límite Orca se simula. No se retiraron worktrees ni ramas de clientes durante estas pruebas.

Se verifican documentos y referencias con el validador portable y se preservan los metadatos específicos de Codex/Claude. La instalación comprueba snapshots previos, mantiene los dieciséis perfiles generados sin cambios y guarda backup transaccional. Los manifiestos registran hashes comprobados para permitir futuras actualizaciones gestionadas.

La nueva memoria por áreas es una instrucción compatible con registros antiguos, no una migración automática de proyectos existentes. Los estados de runs anteriores no se reescriben. La mejora de comportamiento documental aún requiere observar próximas sesiones reales; no se afirma que las pruebas deterministas acrediten obediencia de un LLM o autentiquen la declaración de inactividad del Coordinator.
## 1.0.7 · Memoria optativa, lite ligero y cleanup por repositorio · 06/10/2026

- Cleanup solo considera registros del repositorio actual. Identidad estable: `git rev-parse --git-common-dir`, compartida por el checkout principal y sus worktrees. Se guarda en worktrees nuevos, registros lite, registros Orca y ejecuciones nuevas; los registros antiguos sin identidad solo coinciden mediante `git worktree list`. Reproducción manual: una tarea creada en el repositorio B ya no aparece en el cleanup del repositorio A.
- Las entradas cuyo único motivo para conservarse es el historial ya no se listan por defecto: se resumen en `history_retained` (recuento y hasta 20 ramas) y se muestran con `--purge-history`. Las entradas con bloqueos reales y las ramas remotas pendientes siguen listadas.
- Seis pruebas nuevas en test_cleanup_scoping.py; las seis fallaron contra la 1.0.6 antes de la corrección.
- Memoria del proyecto optativa por proyecto (`docs/devflow/` existente, instrucción del proyecto o petición del usuario). Sin activación no se escriben informes ni memoria en el repositorio; el resumen va al chat.
- Lite: el Coordinator no lee la regla de memoria y solo lee el adaptador Orca si Orca se usa en esa invocación. Con memoria activada, el informe lo escribe `pol-lite`.
- Referencias al informe en contratos de rol, definition-of-done, handoff, plantilla final y adaptador Orca condicionadas a la activación.
- Suite: 121 casos, 120 aprobados y 1 omitido (enlace simbólico en Windows). Validador: healthy.
- Pendiente: el reemplazo atómico de `state.json` falló de forma intermitente con WinError 5 en dos pasadas intermedias (bloqueo de Windows). No reproducido en la pasada final; corregido con un reintento (ver abajo).
- Corregido después: `atomic_write` reintenta hasta 6 veces (unos 1,5 s en total) cuando Windows bloquea el destino de forma transitoria (PermissionError, WinError 5/32). Si el bloqueo persiste, falla sin dejar escritura parcial ni temporales. Dos pruebas nuevas en test_storage_retry.py, que fallan contra la versión anterior.
- El resumen final (full y lite) indica el modelo configurado y el efectivo de cada rol, y qué fases hizo el Coordinator con el modelo de la sesión.

## 1.0.8 · Eficiencia: métricas, perfil, menos llamadas, CI y evaluaciones · 06/10/2026

- Métricas: `usage` opcional en cada resultado (se registra en `_run record`), `_metrics add` para full y lite, y comando público `stats` por rol y tipo de tarea, filtrado por repositorio (`--all`, `--since`). Nunca se estiman valores no registrados.
- Perfil del proyecto: `_profile show|set` guarda comandos verificados fuera del repositorio (compartidos por sus worktrees) o en `.devflow/project.json` solo con `--repo-file`. Marca `stale` cuando cambian package.json, lockfiles u otros archivos de dependencias o herramientas.
- Tandas paralelas de tareas de solo lectura también en modo nativo; los writers siguen siendo secuenciales. Tests afectados durante las correcciones y comprobaciones completas una vez sobre la versión final.
- Menos llamadas: `_run checkpoint` (commit de rutas explícitas + refresh) y resultados sin listas vacías obligatorias; `files_changed` se sigue contrastando con Git.
- CI en GitHub Actions: Ubuntu y Windows con Python 3.11 y 3.12.
- Evaluaciones de comportamiento manuales en `evals/` (6 escenarios, sin ejecución automática de LLM).
- Pruebas nuevas: 8 en test_efficiency.py y 19 en test_evals.py. Comprobación por mutación: sin el filtro por repositorio, `stats` falla su prueba.
- Pendiente: primera ejecución real de la CI en Linux y de las evaluaciones con un LLM.

## 1.0.9 · Commits con finales de línea CRLF · 06/10/2026

- Detectado por la primera ejecución de la CI en Windows: con `core.autocrlf=false`, `git diff --cached --check` trataba el CR de los finales CRLF como espacio sobrante y el helper de commit rechazaba cualquier archivo CRLF, con un mensaje de error vacío.
- El commit acepta CRLF (`core.whitespace=cr-at-eol`) y sigue rechazando espacios sobrantes reales y marcadores de conflicto. Los errores de Git muestran stdout cuando stderr está vacío.
- Prueba nueva en test_gitops.py, que falla contra la 1.0.8. Suite completa con `core.autocrlf=false`: 149 casos, 148 aprobados y 1 omitido.

## 1.0.10 · Correcciones del primer piloto real · 06/10/2026

Origen: piloto en un proyecto de facturación. La corrección técnica pasó 815 pruebas y revisión independiente, pero la ejecución mostró seis carencias de la skill.

- Incidencia frente a defecto: en modo error, `incident` (symptom, status, evidence, accepted_by) separa el síntoma reportado del defecto corregido. `completed` exige `resolved`, o `accepted_unverified` con quién lo aceptó.
- Workers sin avances: `--budget-minutes` por encargo y `overdue_tasks` en status. Si el worker no aporta evidencia nueva, el Coordinator reconcilia y continúa.
- Identidad Git: `_git identity` y el aviso en `_run start`/`_lite start` antes del primer commit (remoto GitHub con email no privado o identidad ausente). Autor por comando con `--author-name/--author-email`, sin tocar la configuración.
- Contratos: `_run template`, `_run record --dry-run` (todas las validaciones antes de cualquier cambio) y `_run check-close` (lista completa de bloqueos). `close` muestra todos los bloqueos a la vez.
- Cleanup: detecta contenido equivalente con otro SHA (`git cherry`) sin borrarlo automáticamente, y conserva identificadas las carpetas residuales tras un borrado fallido.
- Lite: se permite con archivos sin seguimiento ajenos a la tarea (`untracked_preserved`); los cambios en archivos con seguimiento siguen exigiendo full.
- Pruebas: 15 nuevas en test_pilot_fixes.py; 14 fallan contra la 1.0.9 (la otra protege un comportamiento que ya existía). Suite completa: 164 casos con la configuración por defecto y con `core.autocrlf=false`, 1 omitido.
- Pendiente: comprobar en el siguiente uso real que el Coordinator registra la incidencia y respeta el presupuesto de los workers.
