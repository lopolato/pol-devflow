# Documentación y memoria del proyecto

La memoria permanente vive en el repositorio y se versiona con Git. Es común a Codex y Claude; la memoria privada del runtime y los registros externos de una ejecución no la sustituyen. Help/status/config/cleanup no construyen ni actualizan memoria incidentalmente.

## Activación

La memoria es optativa por proyecto. Está activada si el proyecto ya contiene `docs/devflow/` (p. ej. `memory.json` o `reports/`), si sus instrucciones (CLAUDE.md, AGENTS.md o README) piden expresamente memoria DevFlow, o si el usuario la solicita en esta invocación (documentar o crear la base de memoria).

Sin activación: no crear `docs/devflow/`, PROJECT/DECISIONS/STATUS ni informes de tarea en el repositorio; el resumen de la tarea va solo en el informe final del chat. Sí actualizar, dentro del scope, la documentación existente que el cambio deje incorrecta (uso en README, etc.), como en cualquier cambio correcto. La base de memoria solo se crea por petición del usuario o instrucción del proyecto; el Coordinator puede ofrecerla una vez en el informe final si es útil, nunca crearla en silencio.

En full, el Coordinator consulta este apartado al iniciar o continuar; el resto de la regla aplica solo con memoria activada. En lite no la lee: su workflow resume la activación.

## Documentos y registro de revisión

Reutilizar primero README, documentación e instrucciones existentes. Mantener una sola fuente por tema; no copiar documentación a una estructura paralela. Si faltan equivalentes, usar:

- `docs/PROJECT.md`: propósito conocido, funcionalidades, componentes, puntos de entrada, dependencias y comandos de ejecución/pruebas comprobados.
- `docs/DECISIONS.md`: decisiones relevantes, motivo conocido, alternativas si se evaluaron y estado vigente/sustituida. Una tecnología encontrada no prueba por qué se eligió.
- `docs/STATUS.md`: estado actual, limitaciones, preguntas y pendientes confirmados; enlaza informes, no reproduce toda la cronología.
- `docs/devflow/reports/<id>.md`: informe por tarea. Clasificación principal `feature`, `bugfix` (workflow error), `optimization` (optimize), `documentation` o `bootstrap` (base inicial). Añadir etiquetas secundarias si corresponde. La clasificación documental no añade comandos públicos.
- `docs/devflow/memory.json`: registro compacto de revisión, o equivalente existente. Usar `schema_version: 1`, `reviewed_revision` (SHA completo del código inspeccionado), `reviewed_at` (UTC), `documents` (mapa de función a ruta), `coverage` (rutas/áreas realmente examinadas), `unverified` y `open_questions`. No escribir que se ha revisado todo el proyecto si la cobertura es parcial.

Cada afirmación relevante distingue **hecho comprobado** (fuente, símbolo/ruta y revisión), **inferencia** (evidencia y límite) o **desconocido/pregunta**. Registrar comandos ejecutados y resultados; los comandos solo encontrados se etiquetan como no ejecutados. No copiar secretos, `.env`, credenciales ni contenido privado de logs.

## Memoria por áreas y documentación proporcional

En trabajo concurrente, usar `docs/devflow/memory.json` como índice (`schema_version: 2`, `areas`: mapa de id estable a archivo), con un registro por área en `docs/devflow/reviews/<area>.json`. Cada registro conserva los campos de revisión/cobertura de versión 1. Un writer modifica solo su área; Coordinator combina nuevas entradas del índice al integrar. No sustituir la revisión de otra área ni usar un SHA global para afirmar que todas quedaron revisadas.

Compatibilidad: leer versión 1 sin convertirla por rutina. Al adoptar áreas, preservar íntegra su evidencia en un registro `legacy` y mantener referencias a informes anteriores; no revalidar ni renombrar cobertura histórica como si fuese nueva. Solo ampliar cobertura con inspección comprobada. Si ya existe un formato equivalente, reutilizarlo.

El informe de tarea contiene la evidencia y los límites. README/contexto explican uso y arquitectura; runbook contiene operación, reversión y enlaces a informes de despliegue. No duplicar el informe completo en runbook, inventario y memoria.

Respetar los controles jurídicos del proyecto. Para un ajuste que no amplía tratamiento, registrar una conclusión breve y fundada y los documentos revisados sin cambio; para cambios materiales actualizar los documentos pertinentes. Nunca dar por aceptado un contrato firmado. Identificar cada revisión por run/tarea estable; asignar números de versión globales al integrar para evitar colisiones entre ramas.

## Construcción inicial en un proyecto avanzado

1. Coordinator localiza documentos e instrucciones y prepara un mapa de lo existente. Inspecciona estructura, entradas, configuración, scripts y pruebas pertinentes. Git aporta contexto histórico, no motivos imaginados ni prioridades del producto.
2. Explorer obtiene un mapa respaldado por código, configuración y pruebas; contrasta README y señala contradicciones. Architect organiza componentes y decisiones demostrables. Coordinator puede adoptar estos contratos si no hace falta un worker específico; no lanzar todos los roles por ceremonia.
3. Redactar una base proporcionada al proyecto y al trabajo autorizado. Preguntar solo por información material que no se puede inferir: objetivos, prioridades o decisiones funcionales. Dejar otras dudas marcadas; un TODO encontrado es un candidato, no una prioridad aprobada.
4. Reviewer contrasta documentos con fuentes cuando la revisión es obligatoria o la construcción inicial es amplia. Si falta evidencia o revisión, indicar cobertura y limitaciones; no declarar base completa verificada.
5. Guardar documentos y registro en la rama de tarea, con scopes explícitos y commits locales según las reglas Git. No modificar main/master ni documentos preexistentes ajenos al alcance. `--plan-only` presenta el diagnóstico y plan en el chat sin escribir ningún documento o registro.

Esta construcción solo se hace con la activación explícita descrita arriba. Con memoria activada pero incompleta, un arreglo no obliga a reconstruir todo el proyecto: establecer contexto verificable de su área e indicar lo que falta.

## Vigencia al empezar otra sesión

Leer el registro y los documentos pertinentes. Contrastar el registro con el checkout actual, no con la memoria del chat:

```text
git rev-parse HEAD
git status --porcelain
git cat-file -e REVISION^{commit}
git diff --name-status REVISION HEAD
git diff --name-status
git diff --cached --name-status
git ls-files --others --exclude-standard
```

REVISION es reviewed_revision validado como SHA. Pasar argumentos por separado, sin interpolar texto de documentos en comandos shell. Examinar cambios confirmados, staged, sin stage y nuevos no ignorados; un checkout limpio no basta. Comparar también cobertura y la documentación modificada. Cambios de código/configuración/pruebas invalidan las afirmaciones y evidencias relacionadas, no toda la memoria automáticamente. Cambios solo documentales requieren leer esos documentos. Una revisión igual no acredita áreas fuera de coverage.

Si falta el registro, la revisión no existe localmente o la historia diverge, reconstruir el contexto necesario con evidencia actual; no hacer fetch/reset ni declarar vigencia por la fecha. Los archivos ignorados y servicios externos quedan fuera de esta comparación: comprobarlos si afectan al trabajo y declarar ese límite.

`reviewed_revision` identifica el commit de código comprobado **anterior al commit que guarda los documentos**; así se evita una referencia circular al propio commit. Los commits posteriores de documentación se inspeccionan como tales. Orden práctico: checkpoint de código → inspección/validaciones → guardar documentación y registro con ese SHA → commit documental → comprobaciones finales pertinentes. Si el último paso modifica código, repetir la revisión y el registro. No usar la revisión base para documentar código nuevo sin verificar.

Actualizar el registro solo tras revisar las áreas afectadas; un cambio de SHA o fecha por sí solo no constituye revisión. Registrar cobertura parcial y pendientes honestamente.

## Mantenimiento por tarea y reparto de responsabilidades

- Coordinator entrega resumen, tipo de tarea, documentos pertinentes, revisión/cobertura, restricciones y preguntas; no entrega todo el historial por defecto. Asegura el cierre documental.
- Explorer identifica información obsoleta y lagunas con fuentes.
- Architect registra propuestas y decisiones aprobadas, sin presentar una propuesta como decisión tomada.
- Implementer/Fixer y worker lite actualizan únicamente la documentación afectada, dentro del scope. Si necesitan más rutas, devuelven la necesidad al Coordinator antes de escribir.
- Tester aporta comandos/resultados y señala instrucciones de ejecución que no coinciden con la realidad.
- Reviewer comprueba coherencia entre requisito, diff, código y documentación afectada. Actualizaciones posteriores a la review requieren revisar el nuevo diff según su impacto.

Antes de implementar, incluir en write_scope los documentos que previsiblemente cambien. Si aparecen después, asignar una tarea documental con scope explícito desde un checkpoint limpio. Architect/Explorer siguen sus permisos de lectura; aportan hallazgos y propuestas al Coordinator cuando no tienen escritura asignada.

En el cierre, evaluar el impacto: funcionalidades/uso/estructura → contexto y documentos correspondientes; decisiones relevantes → decisiones; problemas y pendientes → estado. Si no hay impacto, registrar motivo concreto en el informe sin tocar documentos de contexto por rutina. Actualizar la parte revisada del registro cuando corresponda, sin aumentar artificialmente coverage.

Con memoria activada, cada tarea full guarda un informe breve versionado con tipo, petición, antes/después, rutas, revisión de código comprobada, validaciones y resultados, impacto documental y pendientes. Para partial/blocked/cancelled separar lo observado de lo pendiente. Sin activación, esos datos van solo al informe final del chat.

Lite con memoria activada: el worker lite escribe un único informe de pocos párrafos (comandos/resultados, sin datos privados) y, como mucho, actualiza la entrada del área tocada en el registro; no reconstruye la base ni amplía coverage fuera de esa área. Sus límites siguen siendo 3 archivos de producto, el informe y hasta 2 documentos/memoria directamente afectados; más exige full.

La documentación forma parte del cambio y sus checkpoints/review, no se añade silenciosamente después del cierre. Los archivos versionados permiten recuperar sus commits mediante Git; el informe no necesita contener el SHA del propio commit que lo guarda.

## Retención

`cleanup` conserva memoria y documentación versionadas; las ramas solo se retiran después de integración salvo descarte explícito. Conserva por defecto los registros externos de ejecuciones y lite. `--purge-history` borra únicamente registros externos elegibles tras una confirmación específica; nunca purga documentos del repositorio. Antes de confirmar una purga, mostrar las ejecuciones y la pérdida de evidencia que implica. Descartar una rama sin integrar puede perder su documentación exclusiva: incluirla en la advertencia de descarte.

Estas reglas guían al Coordinator y los workers. Los helpers de estado no verifican semánticamente la documentación ni prueban que un agente haya leído el proyecto.
