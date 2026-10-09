# Estado persistente y continuación

## Ubicación y contenido

Guardar el estado fuera de los archivos versionados del proyecto, en el directorio de datos de DevFlow del usuario. El instalador resuelve y registra la ruta correspondiente a la plataforma.

~~~text
<devflow-data>/runs/<run-id>/
├── state.json
├── context.md
├── events.jsonl
└── results/
~~~

Cada ejecución registra:

- versión del esquema e identidad única;
- ruta real del repositorio, petición, modo y criterios;
- fase, tareas, dependencias, propietarios y decisiones;
- workers, ramas, worktrees y commits base y actuales;
- contadores de corrección;
- comprobaciones, reviews, bloqueos y siguiente acción.

No copiar secretos, credenciales ni logs sensibles completos al contexto. Conservar referencias y evidencia pertinente.

## Propiedad y escritura

Solo el Coordinator actualiza el estado común. Los workers entregan resultados y evidencias; no reescriben el contexto compartido.

Con executor orca, ese estado es evidencia de desarrollo, no autoridad de actividad. Registrar executor, orca_run_id y el mapeo por encargo a Task/Dispatch, agente estable, settlement y accounting mediante el [adaptador](../../adapters/orca/README.md). No duplicar workers Orca en la lista de actividad native. Reconciliar siempre con su runtime antes de claim, retry o cierre; el puente guarda declaraciones comprobadas por Coordinator, no autentica el proceso. Con executor native, reconciliar actividad e identidades con la API anfitriona real; gestionar el workspace mediante Orca no crea Tasks/Dispatches ni settlement de sus workers.

Guardar estado atómicamente después de asignaciones, resultados, commits, integraciones y validaciones. En V1 solo puede existir un Coordinator activo por ejecución. Un bloqueo local impide continuar simultáneamente desde dos sesiones; antes de retirar uno antiguo se comprueba si sigue activo.

## Continuación

Al solicitar el usuario continuar:

1. localizar la ejecución y verificar repositorio, ramas y worktrees;
2. comprobar workers activos y modificaciones posteriores;
3. reconciliar commits y resultados con el estado guardado;
4. invalidar evidencia que ya no corresponda a la versión actual;
5. continuar desde la fase pendiente.

Si existen varias ejecuciones posibles, preguntar cuál continuar. No duplicar workers ni repetir integraciones ya realizadas.

`--plan-only` no modifica archivos ni crea estado en disco, ramas o commits. Al continuar desde un plan, repetir el preflight y crear entonces el estado de implementación.
