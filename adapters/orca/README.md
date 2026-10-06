# Adaptador Orca Build

Este primer adaptador admite ejecución local sobre un workspace accesible por Coordinator y workers. Placement remoto/WSL requiere una adaptación y verificación adicionales; no lanzar allí con este puente ni sustituirlo por ejecución local silenciosa.

Orca es el backend de coordinación; codex/claude siguen siendo los motores de los workers. DevFlow conserva contratos y evidencia de desarrollo. Orca es la autoridad de Run, Task, Dispatch, actividad, mensajes, settlement y propiedad de terminales. El puente Python no lanza procesos ni autentica mensajes.

Usar este adaptador cuando el usuario solicite Orca o la sesión proporcione contexto Orca comprobado. No activar Orca por la mera presencia de un ejecutable. No sustituirlo por subagentes Codex/Claude cuando se pide procedencia Orca. Fuera de Orca, mantener backend native.

## Cargar el contrato de la instalación

Resolver una vez el ejecutable: ORCA_CLI_COMMAND si está definido; si existe ORCA_DEV_REPO_ROOT, orca-dev; Linux fuera de terminal gestionado usa orca-ide; en los demás casos orca. Usar el valor como ejecutable/argv según la sesión, nunca evaluarlo como código shell. Conservar el mismo ejecutable durante la ejecución. Cargar `skills get orchestration` antes de actuar y las referencias que esa guía indique. Para launch, reutilización/review, placement y recuperación, cargar las referencias correspondientes. Consultar --help de esa versión para flags no descritos. Ante fallo, informar el error; no cambiar de binario ni crear workers alternativos silenciosamente.

La guía runtime es la fuente del protocolo. Este documento especifica el encaje con DevFlow, no copia ni sustituye el manual Orca. Plan-only puede leer la guía y el código; no ejecutar run-create, task-create, worker-start, link/settle/account ni crear ramas, registros o informes.

## Workspace y arranque full

Usar el workspace existente limpio por defecto. DevFlow crea una rama de tarea en ese checkout para Orca, sin crear un worktree adicional:

```text
python scripts/devflow.py --repo PROJECT _run start --executor orca --mode feature --runtime codex --request DESCRIPTION --criterion CRITERION --owner SESSION_ID
```

`--reuse-branch` permite una rama propia ya abierta y limpia. Cambios preexistentes impiden arrancar en el mismo checkout: preservarlos y resolver propiedad; si se necesita aislamiento, crear/seleccionar workspace por Orca con su contrato de placement y después iniciar DevFlow allí. No crear el mismo worktree por los dos sistemas. Registrar inmediatamente el workspace propio con `_workspace register --input REGISTRO_JSON`, usando el recibo y los campos descritos en [cleanup](../../core/commands.md). No registrar el checkout principal ni asumir propiedad por el nombre. Cleanup puede retirar los registrados mediante Orca tras confirmación, integración y comprobación real de inactividad; no usa Git como sustituto del runtime. Orca admite carpetas sin Git, pero DevFlow sigue requiriendo Git para implementar; permite análisis/plan sin Git y comunica el bloqueo concreto.

Verificar que el workspace efectivo del recibo Orca coincide con el absoluto asignado. Usar current solo si el Coordinator está realmente en ese workspace; en otro caso usar un selector exacto descubierto en Orca. No inventar repo IDs, handles, rutas remotas ni translate WSL. Preparar entorno solo si falta; no reinstalar dependencias repetidamente en un checkout existente comprobado.

## Modelo y encargo

Crear tareas DevFlow con `_run task`; `_orca spec --run ID --owner SESSION --task-id TASK [--runtime codex|claude]` devuelve un encargo autocontenido y launch_preferences desde el snapshot. El snapshot captura preferencias explícitas centrales; cuando se heredan, puede capturar el perfil de rol instalado y gestionado cuyo hash coincida. Esto conserva elecciones del usuario sin reescribir configuración. Sin selección explícita, launch_preferences está vacío y el worker hereda los defaults del agente. No elegir modelos nuevos ni aumentar effort incidentalmente.

Lanzar mediante worker-start del contrato Orca, con spec como argumento seguro; usar archivo/API de argumentos si la versión los admite, sin interpolar texto en shell. Pasar --model solo para una elección de usuario registrada; --effort requiere --model y compatibilidad real. Al reutilizar terminal no pasar model/effort; reutilizar únicamente cuando el modelo efectivo existente sea adecuado. Comparar launch.requested y launch.effective si la versión los expone; si no, declarar selección efectiva no verificada. El modelo de Coordinator sigue perteneciendo al chat principal.

Incluir Target, Change, Constraints, Ownership y Observable acceptance, las rutas autorizadas, revisión, contratos y [contexto técnico](../../core/rules/technical-context.md). Los workers no necesitan el historial completo. No reutilizar un autor para aportar revisión independiente; mantener una identidad estable del agente a través de roles y Dispatches.

## Puente de evidencia full

Los IDs DevFlow identifican artefactos/criterios; los IDs Orca identifican actividad e intento autoritativo. Tras contrastar un recibo de arranque listo y placement/modelo, guardar un JSON normalizado y ejecutar:

```text
python scripts/devflow.py _orca link --run ID --owner SESSION --task-id TASK --input LINK_JSON
```

LINK_JSON contiene `orca_run_id`, `orca_task_id`, `dispatch_id`, `agent_handle` (identidad estable real del agente, obtenida del recibo/observación), `worker_id` igual a `orca:<agent_handle>`, `workspace`, `runtime` y `evidence` (referencia del recibo comprobado). No usar Dispatch como identidad del autor: reutilizar un agente no lo convierte en reviewer independiente. No adivinar campos si una versión no expone identidad verificable: inspeccionar con el contrato runtime y, si no puede acreditarse, registrar limitación y no declarar independencia.

El worker recibe los IDs autoritativos del preámbulo vivo Orca y usa su ask/check/heartbeat. Si ese preámbulo no expone el handle estable acordado, Coordinator se lo transmite por el canal del Dispatch, sin crear otro worker. Entrega resultado estructurado y envía worker_done exactamente una vez con outcome explícito, luego termina su turno. done corresponde a succeeded; partial/blocked/cancelled a failed. Un reviewer que terminó su revisión puede devolver done/changes_required: eso no significa que el producto esté aprobado. Usar report-path/files-modified solo con valores reales y permisos existentes; un reviewer de lectura devuelve JSON por mensaje y Coordinator lo guarda sin alterar la evidencia.

Coordinator procesa todas las entregas antes del ack. Contrasta worker_done con el Dispatch activo y guarda SETTLEMENT_JSON: `orca_run_id`, `orca_task_id`, `dispatch_id`, `worker_id`, `type: worker_done`, `outcome: succeeded|failed`, `evidence` y, si existe, delivery_id. Ejecutar `_orca settle ... --input SETTLEMENT_JSON`; después `_run record` con el resultado completo. El puente rechaza identidades/intentos obsoletos, falta de settlement y resultados que contradigan outcome; los controles Git/scopes/revisión se mantienen. No usar task-update completed después de worker_done: Orca ya liquida su Task.

Si no hubo worker_done, registrar `type: runtime_settled`, `outcome: failed` y `proof: failed|stopped|abandoned|start_failed` solo tras confirmar el settlement autoritativo mediante recuperación Orca; `evidence` referencia esa comprobación. Una salida de proceso aislada, timeout o estado unverifiable no sirven. No fabricar un worker_done. En runs partial/blocked/cancelled, settle/account pueden reconciliar evidencia bajo el mismo owner sin reabrir ni lanzar; link exige run activo. Un cambio de owner sigue requiriendo reconciliación real antes de claim.

Sin configuración central, el arranque Orca hereda; únicamente recupera selecciones previas de perfiles instalados gestionados cuyos hashes coinciden con el manifiesto. No trata el preset del paquete como una nueva elección de usuario.

## Olas, seguimiento y cierre

Se permiten varias tareas independientes de lectura (Architect/Explorer/Debugger/Reviewer y Tester sin write_scope) en la misma revisión limpia. Iniciar la ola completa antes de esperar. Solo añadir otra lectura si todas las pendientes son de lectura y sus dependencias están terminadas. No editar, integrar ni actualizar documentación mientras una ola lee la revisión candidata. No solapar writers ni writer con lectores en un mismo checkout. Native aplica la misma regla de olas. Implementaciones paralelas en worktrees distintos quedan fuera de este puente inicial; dividirlas en ejecuciones supervisadas propias si se acuerda, sin atribuirles un cierre integrado automático.

Esperar con check --wait siguiendo la guía, en intervalos acotados compatibles con el runtime y la comunicación al usuario. Timeout, heartbeat, UI quieta o pérdida de contacto no equivalen a fallo o muerte. No relanzar ni liberar por ausencia; seguir request-show/nextAction y referencias de recuperación de esa versión. Orca gobierna retries; una corrección conserva correction_key y presupuesto DevFlow, y respeta también el circuit breaker Orca. Cada reintento valida el último intento fallido, también en cadenas de varios retries. Un reemplazo registrado --replaces puede vincularse a un nuevo Dispatch del mismo Orca Task solo si su intento previo falló positivamente. No crear otro Run para eludir presupuestos.

Después de settlement aceptado, decidir según Orca: reutilizar para una tarea inmediata, retener por petición del usuario o solicitar la liberación. ACCOUNT_JSON contiene `dispatch_id`, `action: released|reused|retained`, `evidence`; la retención solicitada exige `user_requested: true`. Una retención impuesta por Orca se registra como se indica a continuación. reused exige `next_dispatch_id` posterior, ya vinculado al mismo agente después de settlement; no admite referencias hacia atrás ni ciclos. Registrar con `_orca account ... --input ACCOUNT_JSON`. No confundir esta operación de evidencia con worker-release: primero ejecutar/comprobar la acción real Orca. Completar DevFlow exige settlement y accounting de todos sus encargos, además de sus controles de producto.

Si `worker-release` devuelve `state: retained`, `reason: user_takeover` y `processAction: none` para el Dispatch liquidado, respetar esa decisión. Contrastar el recibo con el Dispatch y registrar `action: retained`, `retention_source: orca` y `orca_release_result` con los campos literales `dispatchId`, `state`, `reason` y `processAction`; añadir la referencia comprobada en `evidence`. No marcar `user_requested: true` salvo petición real, ni `released` si la sesión sigue retenida. Esta marca no acredita qué interacción la originó. No forzar un cierre con `terminal close` ni cambiar propiedad para eludir la protección.

La retención comprobada completa el accounting de esa sesión; no convierte por sí sola un resultado de producto en partial. Un recibo `release_pending`, `release_unknown`, de otro Dispatch o con otro motivo no acredita esta excepción: seguir la recuperación de la guía Orca y mantener pendiente lo que no esté comprobado. En la entrega, describir primero el resultado del código y sus validaciones. Mencionar la sesión conservada únicamente si afecta al siguiente paso o el usuario pregunta, como decisión de Orca y no como una tarea administrativa que deba resolver el usuario.

Antes del cierre, consultar worker-list del Run y comprobar que no quedan terminales reclamables ni Dispatches pendientes de resultado/decisión. Los workers Orca no se reflejan manualmente en la lista workers nativa DevFlow como segunda autoridad. Las entradas del puente son declaraciones contrastadas por Coordinator, no autenticación automática ni consultas al proceso. En continuación/claim reconciliar primero el Run/Dispatch real; nunca afirmar workers detenidos solo por estado local.

## Lite y limpieza

Lite mantiene su registro mínimo de rama, sin duplicar las Tasks/Dispatches de Orca en otro planificador. En lite+review, el reviewer es otro Dispatch con identidad distinta del autor y su veredicto se registra igualmente con `_lite review`. Coordinator crea la rama con `_lite start --executor orca --owner SESSION`, crea/bindea un Run Orca conforme a la guía, encarga el contrato lite y el contexto pertinente, y conserva IDs/resultado en el resumen final (y en el informe versionado solo con memoria activada). Usa el modelo lite elegido por el usuario (perfil comprobado/configuración), o herencia si no hay selección; verifica modelo efectivo. Sigue el mismo lifecycle de preguntas, settlement, accounting y no duplicación. Verifica rama, archivos, revisión y comprobaciones reales antes de aceptar la entrega. Una escalada conserva rama/trabajo, liquida el intento y continúa en full con --executor orca --reuse-branch.

El registro lite usa `_lite link|settle|account --lite ID --owner SESSION --input JSON`, con los mismos esquemas de evidencia que full. En este puente mínimo lite termina liberado, retenido si el usuario lo pide o con retención `user_takeover` impuesta por Orca y acreditada según el apartado anterior; no registra reutilización entre runs sin prueba de continuidad. Antes de escalar, liquidar el worker lite y resolver su liberación o retención acreditada antes de abrir el encargo full. Una rama lite Orca recién creada sin recibo también se protege: reconciliar el arranque por la guía Orca antes de limpiar; ausencia de enlace no acredita ausencia de recursos.

worker-release limpia recursos de ejecución, no autoriza borrar Git. cleanup conserva historial y solo considera elementos DevFlow propios; no detiene terminales, reinicia Orca ni elimina worktrees Orca. Registros lite Orca sin settlement/accounting y ejecuciones full Orca con Dispatches vinculados sin settlement/accounting mantienen bloqueada su limpieza, incluso si se registró partial/blocked. La purga de historial sigue requiriendo confirmación específica. Para limpiar recursos Orca pendientes, usar su guía, no el helper Git de DevFlow.
