# Comandos públicos

Usar `python <skill>/scripts/devflow.py <argumentos>`. `--data-dir <ruta>` fija otra ubicación de datos; `--repo <ruta>` identifica el proyecto. Ambas opciones globales admiten posición antes o después del comando.

## help

`help [error|feature|optimize|lite|status|stats|config|cleanup|profile|orca|help]` muestra ayuda sin inspeccionar el repositorio, lanzar workers ni escribir estado.

## status

`status [--run ID]` consulta estado y contrasta Git. Usar el run del chat si se conoce; en otro caso buscar por proyecto. Una ejecución se selecciona, varias se enumeran y ninguna indica ausencia de estado.

Resumir modo, fase, estado, workspace, rama, revisión, tareas (y `overdue_tasks`), workers, validaciones, review, fecha registrada, bloqueos y siguiente acción. Actividad registrada no prueba actividad nativa actual. HEAD cambiado o workspace dirty impiden afirmar vigencia de evidencia anterior. En Orca resumir también IDs de Run/Task/Dispatch, settlement y accounting registrados; comprobar actividad real con el runtime solo cuando corresponda, sin fingirla a partir del JSON. Status no reanuda ni reescribe estado; corrupción se informa como error.

## stats

`stats [--all] [--since DAYS]` agrega tokens, tiempo y modelos registrados por rol y tipo de tarea del repositorio actual (`--all`: todos). Es de lectura; lo no registrado figura como desconocido, nunca estimado. Los datos proceden de `usage` en resultados y de `_metrics add`; los comandos verificados del proyecto, del helper interno `_profile` ([procedimiento](coordinator.md)).

## cleanup

`cleanup [--into REF] [--remote REMOTO] [--purge-history]` enumera ramas registradas (lite y full), worktrees propios y ejecuciones cerradas. Es de lectura. La referencia de integración predeterminada es main o master; `--into` selecciona otra.

Solo considera ramas registradas por DevFlow. Conserva main/master, referencia destino, ejecuciones activas, worktrees con cambios pendientes y ramas abiertas en checkout ajeno o sin integrar. Las acciones son remove, forget (solo con purga cuando la rama ya no existe) o keep con motivo. El historial retenido de una rama ya eliminada aparece como keep; no es trabajo pendiente.

Mostrar una vista previa del conjunto de ramas/worktrees y del remoto elegido y obtener una confirmación específica. Solo entonces ejecutar `cleanup --apply` con las mismas opciones. La confirmación cubre todos los pasos enumerados; no repetirla por rama. Recalcular y retirar solo elementos integrados y limpios sin force; aplicar [cierre y limpieza](rules/delivery.md). **Conserva por defecto registros lite, carpetas de runs, resultados, decisiones y evidencia.** No ejecuta ninguna limpieza dentro de la documentación del repositorio.

`cleanup --purge-history` previsualiza también el borrado de registros externos elegibles. `cleanup --apply --purge-history` los elimina, incluidas carpetas completas de runs cerrados. Mostrar ids y pérdida de informes/evidencia, y obtener confirmación expresa de esa purga; un sí a la limpieza normal no la autoriza. También permite purgar posteriormente el historial retenido de ramas ya eliminadas. No purgar ejecuciones activas ni elementos bloqueados por las protecciones Git.

Una rama sin integrar (incluido squash merge) solo se elimina con `cleanup --apply --discard RAMA`, tras confirmar la rama concreta y advertir de commits/documentos exclusivos. No implica purgar historial. No usar --discard automáticamente para resolver una comprobación de integración fallida. Si el contenido ya está integrado con otro SHA (p. ej. autor reescrito), figura `equivalent: true` con motivo "content identical ... different SHA"; borrarlo sigue exigiendo confirmación y `--discard`. Fallos por elemento se informan en errors; una retirada fallida conserva `residual` con su ruta en limpiezas posteriores, nunca forzar.

En Orca, registrar desde el recibo comprobado el workspace propio mediante `_workspace register --input REGISTRO_JSON`, desde un checkout del mismo repositorio. Campos: `workspace`, `branch`, `backend: orca`, `worktree_id`, `orca_command` (ejecutable resuelto sin argumentos shell) y `evidence`. Rechaza el checkout principal, ramas protegidas y conflictos de propiedad. No registrar carpetas ajenas por su mera presencia. Consultar actividad real y añadir `--orca-idle-confirmed` a apply solo después de verificar ausencia de workers activos y que las terminales restantes son shells inactivos de la tarea. El helper elimina mediante Orca y contrasta Git, Orca y ruta física. No detiene workers ni fuerza borrados.

`--remote REMOTO` es optativo y debe figurar en vista previa y apply. Consulta solo ramas registradas; no hace fetch incidental. Exige revisión remota integrada comprobable localmente y conserva revisiones desconocidas o sin integrar. La eliminación utiliza el SHA esperado para impedir borrar una rama que avanzó. Confirmar expresamente el borrado remoto; la limpieza local no borra GitHub. Se preservan main/master y ramas ajenas.

Cleanup lo ejecuta el Coordinator directamente, sin workers. Mantiene bloqueada la limpieza de runs Orca con Dispatches vinculados pendientes de settlement/accounting, incluso en estado partial/blocked; no detiene ni libera workers Orca.

## config

`config [show|validate]` muestra selección y ubicación o valida configuración y generación. Disponibilidad de modelos se informa como not_verified; no realiza llamadas de pago.

`config set --runtime codex|claude --role <worker> --model <id> [--effort <level>]`

`config set --runtime codex|claude --role <worker> --inherit`

Effort se admite solo en Codex y debe ser compatible con el modelo real. Coordinator usa la sesión principal. Inherit borra model y effort y no puede combinarse con sus flags.

Set modifica la entrada elegida y regenera perfiles del runtime instalado. Comprueba hashes de todos sus perfiles antes de escribir; cambios manuales o archivos ausentes detienen la operación. Backup y rollback conservan el estado previo ante fallos. Las ejecuciones abiertas conservan su config_snapshot.

Sin instalación, set solo escribe la configuración central; no instala agentes. JSON predeterminado es YAML válido sin dependencias; YAML de bloques requiere PyYAML opcional.
