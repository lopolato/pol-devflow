# Comprobación de Pol DevFlow (historial 1.0.5–1.0.25)

## 1.0.25

La primera matriz CI detectó una llamada directa a `run_command` sin el nuevo atributo opcional `compact`. El test previo de validación de reviewer reprodujo el error localmente; se conserva la compatibilidad tratando su ausencia como `False`, sin modificar el test ni omitir controles.

Mejoras derivadas de una ejecución real: respuesta compacta optativa para mutaciones de estado, contadores explícitos de encargos/identidades y tokens sin datos, petición literal desde el inicio, contexto de delegación acotado, riesgos del análisis trasladados a comprobaciones y verificación temprana de UI compartida. Se conservan la autorización de correcciones posteriores, los guards de Git/identidad/scopes, la revisión independiente y la refutación.

Las regresiones de `tests/test_compact_output.py` usan repositorios temporales y el CLI real: comprueban petición literal multilínea, contexto/identidad del arranque, menor respuesta con resultados completos en disco, warnings conservados, reutilización de identidad, cero reportado frente a datos ausentes y rechazo sin mutación de propietario incorrecto o de compactar un encargo. Las instrucciones de UI se contrastan con un caso de evaluación independiente; no se ejecutan sesiones Claude de pago como parte de la suite.

Pruebas dirigidas locales: 12 casos de CLI/status/salida compacta y 23 de presupuestos, petición literal y coherencia de comandos aprobados; 8 casos adicionales de protocolo de resultados y ciclo de vida aprobados. `scripts/validate.py` devuelve healthy y `quick_validate.py` de skill-creator acepta la skill. Se mantiene la política del repositorio: suite completa en la matriz CI de Windows/Linux y Python 3.11/3.12.

Evaluación independiente de lectura sobre seis artefactos sintéticos: identificó redefinición global, orden de carga de scripts, estado/navegación compartidos y contrato de importación todavía desconocido. Propuso trasladarlos a comprobaciones, una entrega vertical y navegador antes de la primera review, con roles acotados y `fork_turns="none"`; no escribió producto ni creó un run. Esa evaluación valida decisiones del plan, no demuestra ejecución de una feature ni mide tokens. El cambio reduce el volumen de respuestas de estado por construcción; no cuantifica ahorro de tokens de modelos ni promete una duración para tareas futuras.

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

## 1.0.17 · Publicación controlada, uso real, presupuesto y conocimiento del proyecto · 09/10/2026

- Publicación: `scripts/release.py VERSION [--push] [--install] [--evals --yes] [--dry-run]` solo trabaja en `main` limpio y al día, exige que la versión ya esté subida en la rama de trabajo (sin commits en `main`), nota en VERIFICATION, cabecera del README, tests, CI de GitHub en verde (si `gh` está disponible) y etiqueta nueva; después etiqueta, publica e instala. `main` está protegida en GitHub: requiere las 4 comprobaciones de la CI, también para administradores, sin force-push ni borrado.
- Uso real: cada run y registro lite guarda `features` (automáticas y declaradas con `_metrics feature`); `stats --features` cuenta su uso y lista `never_used`. Solo `cleanup --apply` deja un registro global sin rutas; las consultas no escriben nada.
- Presupuesto opcional por run: `--max-workers` (bloquea nuevos encargos al llegar al límite) y `--max-tokens` (solo aviso); subirlos exige `_run update budget` con `approved_by`.
- Autoevaluación: `_retro add` al final de cada tarea (qué fue bien, problemas por categoría, sugerencias) y `retro` para el resumen; filtro de datos personales (email, teléfono, IBAN, DNI/NIE/CIF).
- Reglas del proyecto: `_rules add|confirm|remove|for|import-tests` y `rules` (consulta). Guardadas fuera del repo por defecto (o `.devflow/rules.json` con `--repo-file`), con aviso de obsoletas si cambian sus archivos. Un bug corregido propone una regla `must_not` enlazada a su test; el reviewer comprueba las reglas de los archivos tocados.
- README con guía rápida al principio e historial de una línea por versión.
- Pruebas nuevas: test_release.py (19), test_usage_budget.py (8), test_retro.py y test_rules.py (20). Las de uso, retro y reglas fallan contra la 1.0.16.

## 1.0.18 · Entregas breves y revisiones incrementales · 09/10/2026

- Entrega breve: `_run record --brief` acepta un resultado corto con identidad explícita (run, task, worker, rol, estado, resumen, revisiones observada y resultante) y lo expande con los mismos controles que un resultado completo. Rechaza identidades que no coinciden con el encargo y `usage` con campos no reportados; el reviewer debe declarar veredicto y `coverage` no vacía.
- Revisión incremental: `_run task --role reviewer --review-from TASK` genera, además del diff completo, un diff delta desde la revisión anterior (con hash). Solo se admite si la revisión previa fue independiente, completa (no `incomplete`), con cobertura explícita y registrada antes de autores posteriores; `record` comprueba el hash del delta.
- Métricas por actividad: `usage.activity` (implementation, tests, review, reporting, coordination, waiting) y su resumen en `stats`, separado del tiempo de reloj; los registros antiguos sin actividad siguen como desconocidos.
- Pautas: pruebas y revisión de lectura en paralelo sobre el candidato limpio, regresión exacta antes del fix y suite completa una sola vez al final.
- Pruebas: 4 nuevas en test_efficiency.py (expansión de entregas breves e identidades, reviewer breve con usage, revisión incremental con cobertura independiente y diff completo conservado, estadísticas por actividad); ajustes menores en test_lifecycle, test_pilot_fixes y test_report_regressions. CI en verde en Windows y Ubuntu (PR #2).
- Nota redactada al publicar, a partir del diff y los tests de la versión.

## 1.0.19 · Mejor criterio, menos pérdidas · 13/10/2026

Ideas tomadas de gentle-ai v4.1.0 (delegar por un motivo y no por tamaño; especificación literal por referencia; limpieza al retirar; control de deriva de la documentación), adaptadas a DevFlow.

- Nivel por riesgo y comprensión, no por número de archivos. Riesgo alto: permisos/accesos/seguridad; dinero (importes, IVA, facturas, cobros, pagos); comunicaciones a clientes; datos (migraciones, borrados, estructura); concurrencia y tareas automáticas. Riesgo alto nunca va a lite simple (lite+review si es pequeño y se entiende; full en el resto). Sin comprensión suficiente o con partes independientes, full. Desaparece el límite de 3 archivos: pol-lite escribe solo en su write scope asignado y escala si necesita salir de él. Las instrucciones que lee el modelo bajan una línea.
- Petición literal por referencia: `_run start` y `_lite start` aceptan `--request-file` (UTF-8, no vacía, hasta 64 KiB) o guardan `--request` como `inline`, en `request.md` con `request_ref` (ruta, sha256, origen, bytes). Va en cada encargo, plantilla y salida de lite; `record` y `_lite review` rechazan el trabajo si el archivo cambió. Los workers la leen primero y el Coordinator no la sustituye por un resumen.
- Mantenimiento: el instalador borra los archivos propios que una versión deja de incluir si siguen intactos (`removed_obsolete`) y conserva y avisa de los modificados (`preserved_modified`). tests/test_docs_consistency.py comprueba que cada comando, acción y flag citado en la documentación existe en el CLI (sin discrepancias al publicar).
- `release.py --wait-ci [--ci-timeout MIN]`: espera a que la CI termine, también cuando las comprobaciones aún no existen justo después de un push; falla si alguna falla o se agota el tiempo.
- Evaluación `auth-chooses-full` actualizada: una tarea pequeña de permisos debe elegir lite+review o full.
- Pruebas: test_request_ref.py (8), test_install_obsolete.py (4), test_docs_consistency.py (7) y 6 nuevas de `--wait-ci` en test_release.py; 15 de las nuevas fallan contra la 1.0.18. Suite completa: 282 casos con la configuración por defecto y con `core.autocrlf=false`, 1 omitido.

## 1.0.20 · Acertar a la primera · 14/10/2026

Motivada por datos reales de 14 ejecuciones: 13 en full con revisión obligatoria, ~2 reviewers y ~1,3 fixers por ejecución, y funciones opcionales (perfil, reglas, codegraph, retro, métricas) nunca usadas porque dependían de que el Coordinator se acordara.

- Plan de revisión por lentes: `_run update` con `review_plan` {lenses, reason} (requirements, security, money, communications, data, concurrency, tests). Va en los encargos de implementer, fixer, tester y reviewer; la `coverage` del reviewer debe nombrar cada lente del plan.
- Autorrevisión: implementer y fixer devuelven `self_review` por lente (ok, risk, not_applicable); si falta con un plan activo, `record` avisa.
- Segunda vuelta controlada: con dos o más revisiones `changes_required`, un nuevo fixer exige `--blockers-confirmed` con lo que se comprobó.
- Contexto automático: `_run start` y `_lite start` devuelven `context` (perfil, codegraph, número de reglas); cada encargo con alcance trae sus `rules`; `record` devuelve `warnings` (uso no registrado, autorrevisión ausente); `check-close` propone un `retro_draft` con hechos de la ejecución. Las instrucciones dejan de pedir esas consultas a mano.
- Higiene: `status` lista `stale_runs` (activas sin actividad más de 24 h) y `_run abandon --run ID --reason TEXT --confirm-stale` las cierra como canceladas sin tocar ramas ni worktrees.
- Pruebas: test_first_pass.py (9) y test_auto_context.py (11); 18 de 20 fallan contra la 1.0.19 (las otras 2 protegen comportamiento existente). Suite completa: 303 casos con la configuración por defecto y con `core.autocrlf=false`, 1 omitido. Las instrucciones que lee el modelo crecen 2 líneas.

## 1.0.21 · Revisión precisa y contexto acotado · 14/10/2026

Ideas adaptadas de gentle-ai (MIT); análisis completo en docs/analisis-gentle-ai.md. Objetivo: reducir las ~2 revisiones y ~1,3 fixers por ejecución observados.

- Refutación antes de corregir: `_run task --role reviewer --refute-from REVIEW_TASK` asigna a un reviewer independiente (ni autor, ni Coordinator, ni el reviewer original) que devuelve `corroborated`, `refuted` o `inconclusive` para cada bloqueo, sin hallazgos nuevos. Un bloqueo refutado cuenta como resuelto. El fixer solo se asigna con algún bloqueo corroborado; sin refutación o con solo dudosos, decide el usuario (`--user-approved TEXT`).
- Re-revisión acotada: con `--review-from`, el reviewer recibe `scope: "validation"` y `frozen_findings`; un bloqueo nuevo fuera de los archivos corregidos se rechaza y debe informarse como seguimiento no bloqueante.
- Una sola corrección por candidato: si la re-revisión acotada vuelve a pedir cambios, otra corrección exige `--user-approved TEXT`, que basta por sí sola (no se pide además `--blockers-confirmed`).
- Filtro de precisión del reviewer: solo defectos reales con evidencia; el estilo no bloquea; una pasada por lente.
- Contexto: `status --brief [--run ID]` y `_run show --brief` dan un resumen compacto (40 líneas como máximo) para recuperar el estado tras una compactación sin cargar toda la ejecución; reglas de contexto con números (≤3 llamadas o ~10.000 tokens en línea; explorador con ≤ ~2.000 tokens y `archivo:línea`; salidas acotadas; aviso hacia ~150.000 tokens). Formateadores antes de revisar.
- Pruebas: test_refutation.py (10), test_scoped_review.py (5) y test_status_brief.py (4); las 19 fallan contra la 1.0.20. Suite completa: 322 casos, 1 omitido. Las instrucciones que lee el modelo crecen 6 líneas.
- Política de pruebas: la suite completa en este equipo tarda ~20–25 minutos (Python de la Microsoft Store), frente a ~1 minuto en la CI de Ubuntu. Desde esta versión, en local solo se ejecutan los tests afectados; la suite completa la ejecuta la CI en Windows y Linux, y `release.py` se usa con `--skip-tests` sobre un commit ya validado por la CI.

## 1.0.22 · Python del proyecto y publicación robusta · 15/10/2026

- `_profile show` y el `context` de start incluyen `python`: el entorno virtual del proyecto (`.venv`, `venv` o `env` en la raíz o un nivel por debajo, p. ej. `backend/.venv`), buscado en el checkout principal porque los worktrees de tarea no lo contienen. Avisa si el entorno se creó con el Python de la Microsoft Store. Coordinator, pol-lite y workers ejecutan Python con ese intérprete y nunca instalan en el Python global.
- `release.py`: la autenticación de `gh` se comprueba en local (`gh auth token`). Antes, `gh auth status` consultaba GitHub y un corte de red hacía saltarse la comprobación de la CI con solo un aviso. Los cortes de conexión se reintentan 3 veces (20 s) al comprobar y durante `--wait-ci`; si persisten, la publicación se detiene sin etiquetar.
- Origen: migración del equipo del usuario del Python de la Microsoft Store al de python.org, y dos cortes de conexión con GitHub durante la publicación de la 1.0.21.
- Pruebas: test_python_env.py (3) y 3 nuevas en test_release.py; ajuste del contexto esperado en test_auto_context.py.

## 1.0.23 · Cierre de lite y métricas observadas · 15/10/2026

- `_lite finish --lite ID [--status completed|partial|cancelled] [--reason TEXTO] [--revision SHA]`: cierra el registro lite con `closed_at`, revisión final y número de commits. `completed` exige commits desde la base y, en lite+review, revisión vigente; `partial`/`cancelled` exigen motivo; `--revision` acepta el commit final cuando la rama ya se mezcló y borró (debe descender de la base). Orca lite exige `_lite account` antes. Antes ningún registro lite salía de `pending`, así que `stats` no tenía su resultado ni su duración.
- Ramas: los acentos se transliteran (`página` → `pagina`) y el nombre se corta en un límite de palabra a 40 caracteres.
- `untracked_preserved` guarda como mucho 20 rutas más `untracked_preserved_count`; un proyecto real guardaba 1.351 rutas (98 KB) en cada registro y en el encargo de pol-lite.
- `stats`: por rol, `task_elapsed_s` y `avg_task_elapsed_s` con el intervalo observado entre asignación y resultado registrado, disponible aunque el anfitrión no informe tokens ni duración.
- Error y feature: una incidencia o criterio visual se comprueba en un navegador si la sesión tiene uno; si no, se pide al usuario una comprobación concreta antes de cerrar.
- Origen: análisis de dos ejecuciones reales del 15/10/2026 (una lite y una full con refutación corroborada y re-revisión acotada).
- Pruebas: test_lite_finish.py (8) y una nueva en test_timing.py.

## 1.0.24 · Salidas acotadas, cambio mínimo y aclaración guiada · 15/10/2026

- `_check run --workspace W --name NOMBRE [--run ID|--lite ID] [--timeout SECONDS] -- COMANDO ARGS`: ejecuta sin shell (en Windows resuelve lanzadores `.cmd` por PATH), guarda la salida completa con cabecera y hash en `runs/ID/checks/`, `lite/ID.checks/` o `checks/` y devuelve estado (`passed`, `failed`, `timeout`), código, duración, hasta 20 líneas de fallo y las 30 últimas (3 si pasa). El comando tras `--` se separa antes de analizar los argumentos de DevFlow; `--` en cualquier otro comando se rechaza.
- Contrato de worker: tests, lint, typecheck y build con `_check run`, buscando en el log en lugar de repetir; los roles que escriben código siguen una escalera de cambio mínimo (¿hace falta?, ¿ya existe?, librería estándar, función nativa, dependencia instalada, una línea, lo mínimo) sin recortar validación en fronteras de confianza, pérdida de datos, seguridad ni accesibilidad, y declaran en `risks` los atajos con límite conocido.
- Lente `simplicity` en `review_plan`: el reviewer devuelve qué sobra solo como `suggestion`, nunca como blocker, para no alargar el ciclo de corrección.
- Aclaración: con decisiones de producto abiertas, una pregunta cada vez, con respuesta recomendada y motivo, hasta cerrar las que cambian criterios o comportamiento visible.
- Origen: ideas de Ponytail (escalera y atajos anotados), Context Mode (salidas fuera del contexto) y `grill-me` de Matt Pocock; ver docs/analisis-ideas-externas.md. Se toman ideas, no texto ni código.
- Pruebas: test_checks.py (6); `_check` añadido a los comandos de test_docs_consistency.
