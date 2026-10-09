# Comprobación de Pol DevFlow (historial 1.0.5–1.0.16)

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

## 1.0.11 · codegraph y skills de proceso ajenas · 06/10/2026

- codegraph optativo: `_profile show` devuelve `codegraph` (`project_path`, `ignored_by_git`) cuando el checkout principal o un directorio superior tiene `.codegraph/codegraph.db`. También desde un worktree de tarea, que no contiene el índice. Solo cuenta una carpeta con base de datos: `~/.codegraph` (configuración y telemetría global) no es un índice; lo detectó la primera prueba en esta máquina.
- Los roles que leen código consultan `codegraph_explore` antes de buscar y leer archivo por archivo. DevFlow nunca ejecuta `codegraph init` ni `upgrade`.
- Durante DevFlow no se activan skills de proceso de otros plugins (superpowers está activo en Claude y Codex); sí las de conocimiento.
- Pruebas: 2 nuevas en test_codegraph_profile.py. Comprobación real de solo lectura: el proyecto de facturación tiene índice y Git lo ignora.

## 1.0.12 · Menos coste en tareas medianas · 06/10/2026

- Nivel lite+review (`--lite --review`): cambios pequeños que necesitan revisión independiente (permisos, seguridad, reglas de negocio relevantes) ya no pasan a full. Flujo: `_lite review-diff` (diff con hash y autor), un `pol-reviewer` distinto del autor y del Coordinator, `_lite review` con el veredicto y `_lite status` con `review_current`. Una revisión queda obsoleta si cambia la rama; el tercer `changes_required` pasa a full. Migraciones, datos, concurrencia y trabajo amplio siguen yendo a full.
- `code_map` en los resultados (archivo, función, líneas, motivo; máximo 50) y `_run task --context-from TAREA`, que lo pasa al siguiente worker para que no vuelva a explorar el mismo código.
- `_lite start` devuelve `session_model_hint`: el Coordinator puede sugerir, una vez y sin bloquear, abrir las sesiones de tareas pequeñas con un modelo ligero.
- Pruebas: 11 nuevas en test_lite_review.py, que fallan todas contra la 1.0.11. Suite completa: 177 casos con la configuración por defecto y con `core.autocrlf=false`, 1 omitido.

## 1.0.13 · Fiabilidad de entregas y coordinación · 07/10/2026

- Prevalidación de resultados de lectura antes de settlement, con errores de campo y plantillas completas `partial`; no convierte claims ni elimina blockers. Registro posterior conserva los controles de Git, identidad y settlement.
- Rutas Git literales `[action]`, preservación de staging ajeno y rechazo de directorios eliminados. Cleanup confirma Orca, Git y ruta física durante un plazo acotado, sin repetir borrados; conserva residuos y devuelve salida no cero si falla.
- Salida UTF-8 bajo Windows cp1252. Tiempos observados con cierre estable, incluso tras accounting posterior; históricos sin evidencia permanecen desconocidos. No son coste ni tiempo de ejecución del agente.
- Primera entrega con prueba del recorrido principal; revisión y pruebas dirigidas antes de build/Docker finales. Arranque incierto de Orca se reconcilia sin duplicar prompts; no se modifica el runtime.
- Revisión independiente con fixtures de prevalidación/settlement, Git literal, staging ajeno y borrado asíncrono. Encontró y verificó la corrección de un contador que seguía creciendo después del cierre.
- Suite completa de 196 casos ejecutada en Windows/Python 3.11. Inicialmente 192 pasaron, 1 fue omitido por permisos de symlink y 3 pruebas antiguas fallaron por cambios de contrato. Se actualizaron únicamente esas pruebas (plantilla completa/partial, éxito explícito y firma del mock); los tres casos fueron reejecutados y aprobados independientemente. Resultado combinado: 195 casos aprobados y 1 omitido; no se presenta como una segunda ejecución completa.
- Validadores portable y skill-creator aprobados; instalación Codex 1.0.13 y perfiles administrados verificados, preservando modelos y configuración. Pendiente observar el ahorro de tiempo en una nueva ejecución real y diagnosticar la causa interna del arranque Orca.

## 1.0.14 · Delegación nativa en Codex y Claude · 07/10/2026

- Executor native preferido si el runtime anfitrión ofrece una API real de delegación. Codex usa sus subagentes; Claude Code usa Agent. Una petición explícita de executor Orca se mantiene y una ejecución activa nunca cambia de autoridad en silencio.
- Propiedad de workspace independiente del executor; Orca sigue gestionando sus worktrees y terminales, mientras native mantiene su propia evidencia de workers sin Tasks/Dispatches ficticios ni settlement duplicado.
- Prueba real de Codex: un único spawn_agent recibió 350 filas numeradas, devolvió NATIVE_DELIVERY_OK y confirmó extremos 000/349.
- Prueba real de compatibilidad Claude Code 2.1.291: una ejecución print aislada invocó Agent exactamente una vez; el subagente nativo devolvió CLAUDE_NATIVE_DELIVERY_OK con 350 filas y extremos 000/349. Sin denegaciones ni cambios de archivos. Esta prueba de compatibilidad no introduce un launcher oculto: la delegación de desarrollo se realiza con Agent desde la propia sesión Claude.
- Se preservan perfiles y preferencias de modelos de cada proveedor, scopes, revisión independiente y autorizaciones. La disponibilidad efectiva de otros modelos no se infiere de estas pruebas.
- Este cambio evita depender del pegado de terminal para la ejecución normal de Pol DevFlow. Los parches experimentales del runtime Orca no se han instalado ni acreditan resolución de su incidencia upstream.

## 1.0.15 · Subdelegación nativa controlada · 09/10/2026

- Subdelegación optativa en full/native: un padre architect, reviewer o tester con `--can-delegate`, evidencia de preflight (`--native-nesting-evidence`) y límite de 2–4 workers puede usar hasta dos hijos de solo lectura (explorer, debugger, tester) dentro de su `read_scope`. Sin tercer nivel; lite y Orca siguen planos.
- En Claude, los perfiles architect, reviewer y tester pueden usar Agent; el resto mantiene `disallowedTools: Agent`.
- Pruebas: test_nesting.py (topología, capacidad compartida, cierre de hijos y padres). CI en verde en Windows y Ubuntu.

## 1.0.16 · Subdelegación comprobada en Claude Code · 09/10/2026

- Pruebas en vivo con Claude Code 2.1.291 en una carpeta temporal: un agente padre lanza a un hijo y recibe su respuesta; un agente con `disallowedTools: Agent` no puede delegar; el `pol-reviewer` instalado, con grant, delega en `pol-explorer` la lectura de un archivo y devuelve el dato correcto; sin grant, no delega aunque el encargo se lo sugiera y lee él mismo.
- Hallazgo: en una repetición, el padre lanzó al hijo en segundo plano y terminó antes de recibir su respuesta. Ahora el contrato del worker y el adaptador de Claude exigen lanzar cada hijo esperando su resultado (`run_in_background: false`) y no terminar antes que los hijos.
- Flujo aclarado para Claude: el Coordinator registra los hijos antes de lanzar al padre, el padre recibe directamente la respuesta de sus hijos y la devuelve con su resultado, y el Coordinator registra cada hijo.
- `evals/check_claude_nesting.py`: repite las cuatro pruebas (unos 0,90 $). Conviene ejecutarlo tras actualizar Claude Code. Comprueba que el hijo no se lance en segundo plano.
