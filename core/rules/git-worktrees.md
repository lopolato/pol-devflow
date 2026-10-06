# Contrato Git, commits e integración

## Base y ramas

Inspeccionar repositorio, rama, HEAD, worktrees y cambios locales antes de modificar código.

- Usar la base explícita del usuario o del proyecto.
- Al continuar, reutilizar la rama registrada después de verificarla.
- En una tarea nueva sin base explícita, partir del HEAD actual y registrar su commit.
- Si la rama actual pertenece a esa misma tarea, reutilizarla.
- Si es `main`/`master` o corresponde a otra tarea, crear una rama propia.
- Ante una colisión de nombre ajena a la ejecución, añadir un sufijo único; no reemplazar la rama existente.

Informar de la base elegida. No hacer pull, rebase ni cambiar la base implícitamente.

Si no existe Git, se permite analizar y planificar; la implementación queda bloqueada hasta disponer del aislamiento requerido o de una instrucción explícita que cambie esta política.

## Cambios preexistentes

Preservar cambios locales. No ejecutar stash, reset o limpieza automáticamente.

Si esos cambios no son necesarios, usar un worktree propio desde el commit base. Si la tarea depende de cambios sin commit, preguntar cómo incorporarlos antes de modificar código dependiente. No ignorarlos ni incluirlos automáticamente en commits.

## Commits locales automáticos

DevFlow puede crear commits locales de su trabajo sin pedir aprobación en cada paso, respetando las instrucciones del usuario y del proyecto.

- Usar staging de rutas explícitas; evitar `git add .`.
- Inspeccionar el diff staged antes de confirmar.
- No incluir modificaciones preexistentes ni ajenas.
- Respetar hooks; no omitirlos para forzar un commit.
- Registrar si el checkpoint está validado o incompleto.

Crear checkpoints de unidades coherentes y antes de integrarlas. Un commit no acredita que los tests hayan pasado.

DevFlow no hace push, crea PRs, despliega ni mergea a `main` por el mero hecho de haber completado la tarea; esas acciones necesitan una solicitud que las incluya.

## Integración

Las ramas hijas parten de un commit identificado de la raíz. El Coordinator las integra mediante merges locales secuenciales según sus dependencias.

Resolver conflictos técnicos cuando exista una solución consistente con el contrato acordado. Preguntar si el conflicto exige elegir un comportamiento funcional. No seleccionar automáticamente `ours` o `theirs`.

Validar el resultado integrado y revisarlo cuando corresponda. La aprobación aislada de cada rama hija no acredita la raíz integrada.

## Conservación y limpieza

Aplicar [cierre y entrega](delivery.md). La propiedad del worktree se conserva por identidad/ruta aunque cambie la rama; no trasladar main/master a un workspace de tarea como cierre habitual. Si un workspace Orca propio fue creado fuera del helper Git, registrarlo mediante `_workspace register` antes de asignar workers.

Si la ejecución queda parcial, bloqueada o cancelada, conservar ramas, worktrees, cambios y estado. Informar de ubicación y trabajo pendiente.

Al completar, conservar la rama raíz y su workspace para revisión humana. Se pueden retirar worktrees hijos integrados únicamente si están limpios, no hay workers activos y sus commits son alcanzables desde la raíz. Conservar sus ramas en V1.

Conservar los experimentos descartados, identificándolos como tales. Eliminarlos requiere una solicitud posterior de limpieza. No usar borrado forzado para cerrar una ejecución.

La limpieza posterior se hace con `cleanup`, siempre listando primero y con confirmación del usuario (ver [comandos](../commands.md)). En modo lite no hay worktree: la rama se crea en el checkout actual y es lo único que queda por retirar.

## Preparar el entorno del worktree

Un worktree nuevo contiene lo versionado en Git. Antes de implementar o probar, Coordinator:

1. Lee instrucciones del proyecto, manifiestos, lockfiles y scripts de bootstrap. Comprueba herramientas/versiones, dependencias, servicios necesarios y permisos de acceso a la carpeta devuelta.
2. Reproduce el entorno con el procedimiento del proyecto: instalación reproducible desde lockfile, entorno virtual local y compilación previa cuando corresponda. Registra comandos, versiones y resultado. Usa cachés documentadas si existen; no copia ni enlaza automáticamente node_modules o .venv del checkout original.
3. Obtiene configuración de desarrollo del mecanismo aprobado del proyecto. No copia .env, credenciales ni otros secretos por defecto; no los incluye en estado, diff o commits. Si no existe una vía autorizada, identifica las variables o servicios faltantes sin revelar valores y detiene trabajo dependiente.
4. Comprueba acceso del runtime al worktree y a los artefactos de review. En Claude usa el mecanismo nativo disponible para el directorio concreto; no concede acceso global ni desactiva controles.
5. Ejecuta una comprobación inicial pertinente antes de editar producto. Distingue fallo de bootstrap/entorno de fallo funcional y registra baseline en decisiones y validaciones. Si falta un requisito, registrar not_run con motivo y devolver partial/blocked.

Generados y dependencias deben usar rutas ignoradas previstas por el proyecto o externas al checkout. Si dejan archivos no ignorados, reconciliarlos explícitamente antes de asignar otro worker; no esconderlos con cambios automáticos al Git del usuario. Toda asignación CLI exige un checkpoint limpio.

La carpeta propia usa wt- seguido de un id corto, independiente del nombre descriptivo de la rama. Si aun así la ruta completa del proyecto supera lo soportado por una herramienta Windows, usar --data-dir con una raíz externa corta acordada para esa ejecución. No modificar ajustes globales de rutas largas.
