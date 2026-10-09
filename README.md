# Pol DevFlow 1.0.15

La 1.0.15 permite delegación nativa optativa de un nivel adicional en full, tanto Codex como Claude Code, con grants explícitos, scopes de lectura contenidos, dos plazas por padre y un máximo de cuatro workers activos. Los hijos son solo lectura; el Coordinator registra cada hijo antes del lanzamiento y recoge su resultado para el padre.

La 1.0.14 prefiere la delegación nativa verificada del entorno actual: subagentes de Codex en Codex y Agent en Claude Code, también cuando la sesión está abierta en Orca. Una petición explícita de workers Orca conserva ese backend. La gestión de un workspace Orca sigue correspondiendo a Orca; ejecución de workers y propiedad del workspace son decisiones distintas. Una ejecución activa conserva el backend con el que empezó. Se mantienen perfiles de modelos, scopes y revisión independiente.

La 1.0.13 añade prevalidación de resultados sin registrar entregas, plantillas con estados canónicos, tiempos de pared observados y salida UTF-8. Admite rutas Git literales como `[action]` y confirma el borrado asíncrono de Orca antes de darlo por terminado; los errores de cleanup devuelven un código de salida no cero. El flujo prioriza revisión y pruebas dirigidas antes de comprobaciones finales costosas. El arranque incierto de Orca se reconcilia sin duplicar encargos; esta skill no modifica el runtime de Orca.

Skill portable para Codex y Claude Code. El paquete contiene instrucciones, helpers y tests; la instalación es una operación explícita independiente de su creación. La 1.0.12 añade el nivel lite+review (`--lite --review`), `code_map` con `--context-from` para no releer código entre workers y la sugerencia de modelo de sesión. La 1.0.11 añade codegraph optativo y aísla DevFlow de las skills de proceso de otros plugins. La 1.0.10 separa incidencia reportada de defecto corregido, añade presupuesto por worker (`overdue_tasks`), identidad Git antes del primer commit, `template`/`record --dry-run`/`check-close`, cleanup de contenido equivalente con otro SHA y residuos, y lite con untracked ajenos. La versión 1.0.8 añade métricas de uso (`stats`), perfil de comandos verificados, olas de lectura también en native, tests afectados durante correcciones y menos llamadas por checkpoint. La 1.0.7 hizo la memoria optativa por proyecto, aligeró lite y limitó cleanup al repositorio actual. Mantiene el adaptador Orca Build, olas de lectura, Context7 y lite proporcional. Conserva memoria en Git e historial en cleanup; Engram queda fuera.

## Requisitos

Python 3.11+ y Git. La configuración predeterminada usa JSON válido como YAML y no necesita dependencias adicionales. YAML de bloques requiere PyYAML opcional.

## Comandos de la skill

`error`, `feature`, `optimize`, `help`, `status`, `stats`, `config`, `cleanup`. `--plan-only` analiza sin escribir. El CLI Python es soporte determinista, no un agente LLM autónomo. Coordinator permanece en el chat principal y ocho perfiles worker se eligen según necesidad.

## Modo lite

`error` y `feature` aceptan `--lite` o `--full`, y `--review`; sin flag de nivel, el Coordinator propone uno. Lite es para cambios claros de hasta 3 archivos de producto, incluidos tests, sin migraciones, datos ni concurrencia. Si además tocan permisos/seguridad o reglas de negocio relevantes, o se pide review, el nivel es lite+review: `pol-reviewer` revisa el diff de la rama lite y no hay `done` sin review vigente. Crea una rama nueva en la carpeta actual (sin worktree, así `node_modules` y `.env` siguen disponibles) y delega todo el trabajo en el worker `pol-lite`, que usa el modelo ligero de models.yaml. Si la tarea deja de ser pequeña, pasa a full sobre la misma rama. Optimize siempre es full.

## Modelo de la sesión

El Coordinator usa el modelo con el que se abrió la sesión y es quien hace más turnos. Para lite y tareas rutinarias conviene un modelo ligero (p. ej. Sonnet en Claude, Luna en Codex); para full complejo, uno fuerte (Opus / gpt-6.1-sol). Los workers usan siempre sus modelos configurados.

## Estadísticas y perfil del proyecto

`stats [--all] [--since DAYS]` muestra tokens, tiempo y modelos por rol y tipo de tarea, solo con valores que el runtime reportó; lo demás figura como desconocido. El perfil (`_profile`) guarda fuera del repositorio los comandos verificados (test, test_affected, lint, build…) para no redescubrirlos en cada run y marca `stale` cuando cambian dependencias o tooling. `.devflow/project.json` solo se crea si el usuario lo pide.

## Orca y Context7

Con executor orca, elegido por petición explícita o tras comprobar que falta delegación nativa, leer [adaptador Orca](adapters/orca/README.md) y la guía de su ejecutable. La presencia de una sesión Orca no sustituye la API nativa de Codex o Claude cuando esta está disponible. Orca gobierna actividad, Tasks/Dispatches, mensajes y settlement; DevFlow conserva criterios, scopes y evidencia. El puente _orca genera specs y registra link/settle/account, sin lanzar procesos ni autenticar recibos. En full, --executor orca crea rama en el checkout limpio actual, sin worktree adicional. Writers secuenciales y olas de lectura independientes, como en native. Modelos elegidos por usuario o herencia, comprobando selección efectiva.

Antes de completar, registrar resultado y decisión de reutilización/retención/liberación y comprobar el Run real. El helper no reemplaza worker-release. Cleanup no detiene workers: registra propiedad y puede retirar worktrees Orca mediante su runtime después de verificar inactividad, integración y confirmación del alcance. La versión inicial del puente es local; ejecución remota y writers paralelos en worktrees separados quedan pendientes.

Si el proyecto tiene índice de codegraph (`.codegraph/codegraph.db`), los roles que leen código lo consultan antes de abrir archivos; DevFlow nunca crea el índice. Durante DevFlow no se activan skills de proceso de otros plugins (p. ej. superpowers). [Context7](core/rules/technical-context.md) se consulta ante dudas de API/versión: comprobar dependencia instalada, obtener extractos pertinentes y compartirlos en contextos. Si falta o no cubre esa versión, usar documentación oficial/evidencia local. No instalar MCPs ni añadir Engram incidentalmente. Plan-only no escribe ni crea recursos Orca.

## Limpieza

`cleanup` lista las ramas, worktrees y ejecuciones que dejó DevFlow e indica cuáles están mezcladas en main. `cleanup --apply` retira solo lo mezclado y limpio, tras una confirmación del alcance mostrado. `--remote REMOTO` incluye el remoto explícitamente; `--orca-idle-confirmed` registra la comprobación de actividad previa para worktrees Orca propios. Sin estas opciones no se presume borrado remoto ni cierre de workers. Una rama sin mezclar solo se borra con `--discard RAMA`, confirmada una por una. Nunca toca ramas que DevFlow no creó.

## Documentación y memoria

La memoria es optativa por proyecto: se activa si el repositorio ya tiene `docs/devflow/`, si sus instrucciones (CLAUDE.md, AGENTS.md o README) la piden o si el usuario la solicita. Sin activación, DevFlow no crea `docs/devflow/`, PROJECT/DECISIONS/STATUS ni informes en el repositorio; el resumen va al informe final del chat y solo se corrige la documentación existente que el cambio deje incorrecta. Puede ofrecer crear la base una vez, nunca en silencio.

Con memoria activada, construye contexto a partir de documentación, código, configuración y pruebas; distingue hechos, inferencias y dudas, reutiliza documentos existentes y registra revisión/cobertura para comprobar cambios al continuar. Cada tarea full guarda un informe clasificado como feature, bugfix, optimization, documentation o bootstrap. En lite el worker escribe solo un informe breve y, como mucho, 2 documentos/memoria del área tocada; el Coordinator no lee las reglas de memoria. Plan-only no escribe memoria.

En tareas concurrentes el índice de memoria referencia registros de revisión por área; preserva evidencia previa y evita sobrescribir la revisión de otra tarea. El informe contiene pruebas y límites; runbook e inventario enlazan la evidencia sin duplicar todo el informe.

Ver [reglas de memoria](core/rules/project-memory.md). El mantenimiento semántico corresponde a Coordinator y workers; los helpers no acreditan por sí solos que se haya leído y entendido el proyecto.

Cleanup conserva por defecto registros y evidencia. `--purge-history` requiere una confirmación específica para eliminarlos; nunca borra documentación versionada del repositorio por esa opción.

## Instalación y actualización

```text
python scripts/install.py --runtime all
python scripts/uninstall.py --runtime all
```

Se puede elegir codex o claude. El instalador actualiza únicamente archivos propios cuyo hash coincide con el manifiesto; ante edición manual, se detiene. Conserva configuración central de modelos, ejecuciones, ramas y worktrees; crea backup transaccional. No modifica config.toml ni settings.json del runtime.

El SKILL.md del ZIP es el origen portable. Claude recibe las claves nativas disable-model-invocation y argument-hint del adaptador; Codex recibe su política explícita en agents/openai.yaml. La diferencia de metadatos está documentada y no representa divergencia de workflows.

Al actualizar, el adaptador de Claude conserva una única disable-model-invocation: true incluso si el origen ya tiene metadatos nativos. No sustituir el SKILL.md instalado por el archivo portable del ZIP: usar el instalador.

`python scripts/validate.py` valida el paquete portable, o la instalación completa si se ejecuta desde una skill registrada. Para comprobar explícitamente un runtime instalado desde el paquete, usar `python scripts/validate.py --runtime codex` o `--runtime claude`. La validación de instalación comprueba metadatos nativos y todos los hashes; un healthy del paquete portable no prueba que la instalación mantenga sus restricciones.

## Modelos

```text
$pol-devflow config show
$pol-devflow config validate
$pol-devflow config set --runtime codex --role reviewer --model MODELO --effort high
$pol-devflow config set --runtime claude --role implementer --model MODELO
$pol-devflow config set --runtime codex --role tester --inherit
```

En Orca, sin configuración central ni perfiles gestionados previos, la selección hereda la sesión. Este paquete conserva el preset personal ya elegido; la instalación native usa esa configuración cuando no existe una central. Las actualizaciones locales preservan las preferencias instaladas. Configurar un modelo no prueba acceso real. Cambios afectan a ejecuciones futuras; Coordinator usa el modelo del chat.

## Garantías y límites

Scopes contrastados con cambios confirmados, staged, sin stage y archivos nuevos no ignorados. Comprobaciones obligatorias no reducibles; hallazgos conservados y resolución por evidencia actual. Fixer requiere clave estable, con tres ciclos por problema. Inicio exige runtime explícito. Reviewer recibe diff completo con hash. Coordinator no puede acreditarse como reviewer independiente.

El helper comprueba identidades declaradas, no las autentica; Coordinator verifica la asociación con sesiones nativas. Los archivos ignorados y modificaciones externas a Git no son una frontera de seguridad del helper. El worktree conserva contenido versionado; preparar dependencias/configuración y acceso según el proyecto antes de ejecutar tests. Carpetas cortas reducen el riesgo de rutas largas sin garantizar compatibilidad de todos los proyectos Windows.

Ver [procedimiento](core/coordinator.md), [entorno Git](core/rules/git-worktrees.md) y VERIFICATION.md para evidencia y limitaciones. La carga efectiva de agentes y su funcionamiento con un proyecto real requieren una prueba en sesión nativa.

## Licencia

MIT. Ver [LICENSE](LICENSE).
