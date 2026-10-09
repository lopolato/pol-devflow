# Pol DevFlow 1.0.18

La 1.0.18 admite entregas breves que el Coordinator prepara y registra en una pasada con los mismos guards, reviews delta ligadas a cobertura independiente y ancestros Git, y métricas opcionales por actividad. Las pautas priorizan pruebas/review de lectura en paralelo sobre el candidato limpio, regresión exacta antes del fix y suite completa una vez al final.

Skill portable para Codex y Claude Code que orquesta `error`, `feature` y `optimize` con workers, Git seguro, pruebas reales y revisión independiente. El Coordinator es la sesión del chat; el CLI Python solo aporta operaciones deterministas (estado, Git, evidencia), no es un agente.

## Cómo se usa en 2 minutos

1. **Instalar** (Python 3.11+ y Git): `python scripts/install.py --runtime all` (o `codex` / `claude`). Abrir una sesión nueva.
2. **Pedir trabajo** (en Codex, `$pol-devflow` en lugar de `/pol-devflow`):

   ```text
   /pol-devflow error --lite el total del carrito no suma el envío
   /pol-devflow feature --plan-only exportar pedidos a CSV
   /pol-devflow cleanup
   ```

3. **Elegir nivel** (sin flag, el Coordinator propone uno y lo justifica):

   | Nivel | Cuándo | Qué hace |
   |---|---|---|
   | `--lite` | Cambio claro, ≤3 archivos de producto con tests, sin migraciones, datos ni concurrencia | Rama en la carpeta actual; trabaja `pol-lite` con modelo ligero |
   | `--lite --review` | Lo anterior, pero toca permisos/seguridad o reglas de negocio, o pides review | Igual, más `pol-reviewer` independiente sobre el diff |
   | `--full` | Todo lo demás; `optimize` siempre | Worktree propio, roles según necesidad, review y `check-close` |

   Lite no usa worktree (`node_modules` y `.env` siguen disponibles); si la tarea crece, pasa a full sobre la misma rama.

4. **Modelo de la sesión**: el Coordinator usa el modelo con que abriste el chat y es quien más turnos hace. Para lite y tareas rutinarias, uno ligero (Sonnet / Luna); para full complejo, uno fuerte (Opus / gpt-6.1-sol). Los workers usan su modelo configurado.

`--plan-only` analiza y presenta el plan sin escribir nada. DevFlow nunca hace push, merge a main ni despliegue sin que lo pidas.

## Comandos

`error`, `feature`, `optimize`, `help`, `status`, `stats`, `retro`, `rules`, `config`, `cleanup`. Detalle en [comandos](core/commands.md).

- `status [--run ID]`: estado, tareas vencidas (`overdue_tasks`) y presupuesto del run.
- `stats [--all] [--since DAYS] [--features]`: tokens, tiempo y modelos registrados por rol (lo no reportado figura como desconocido, nunca estimado). `--features` cuenta qué funciones se usan y lista `never_used`, candidatas a recortar.
- `retro [--since DAYS] [--category C]`: resumen de las autoevaluaciones de proceso que el Coordinator guarda al cerrar.
- `rules [--path P ...]`: reglas del proyecto (must_not, requirement, convention) y las que afectan a unas rutas. Tras corregir un bug se propone una `must_not` ligada a su test de regresión (inferida hasta que la confirmes); se consultan antes de asignar writers y las comprueba el Reviewer. Se guardan fuera del repositorio salvo `--repo-file` (`.devflow/rules.json`). Reglas y retro son optativas y nunca bloquean.
- Presupuesto en full: `--max-workers N` / `--max-tokens N` al iniciar. Superar workers se rechaza hasta que apruebes subirlo; superar tokens solo se avisa.
- `cleanup [--apply] [--remote R] [--discard RAMA] [--purge-history]`: ver [Limpieza](#limpieza).

## Perfil, codegraph y Context7

El perfil (`_profile`) guarda fuera del repositorio los comandos verificados (test, test_affected, lint, build…) para no redescubrirlos y marca `stale` si cambian dependencias o tooling; `.devflow/project.json` solo si lo pides. Si el proyecto tiene `.codegraph/codegraph.db`, los roles lo consultan antes de abrir archivos (DevFlow nunca crea el índice). [Context7](core/rules/technical-context.md) se usa solo ante dudas de API/versión. Durante DevFlow no se activan skills de proceso de otros plugins (p. ej. superpowers).

## Orca

Se prefiere la delegación nativa comprobada (subagentes Codex, Agent en Claude Code), también dentro de Orca. Workers Orca solo por petición explícita o falta de API nativa: ver [adaptador Orca](adapters/orca/README.md). Orca gobierna actividad, Dispatches y settlement; DevFlow conserva criterios, scopes y evidencia. Un run no cambia de executor en silencio.

## Limpieza

`cleanup` lista ramas, worktrees y ejecuciones que dejó DevFlow en este repositorio y cuáles están mezcladas. `--apply` retira solo lo mezclado y limpio tras confirmar el alcance; `--remote` incluye el remoto explícitamente; una rama sin mezclar solo se borra con `--discard RAMA`. Conserva por defecto registros y evidencia; `--purge-history` exige su propia confirmación. Nunca toca ramas que DevFlow no creó.

## Documentación y memoria

Optativa por proyecto: se activa si existe `docs/devflow/`, si las instrucciones del proyecto la piden o si la solicitas. Sin activación no se escribe memoria ni informes en el repositorio; el resumen va al chat. Ver [reglas de memoria](core/rules/project-memory.md).

## Instalación, actualización y mantenimiento

```text
python scripts/install.py --runtime all
python scripts/uninstall.py --runtime all
python scripts/validate.py [--runtime codex|claude]
```

El instalador actualiza solo archivos propios cuyo hash coincide con el manifiesto (ante edición manual se detiene), conserva configuración de modelos, ejecuciones, ramas y worktrees, y crea backup transaccional. No modifica config.toml ni settings.json. Claude recibe `disable-model-invocation` y `argument-hint` del adaptador; Codex, su política en agents/openai.yaml. No copiar el SKILL.md del ZIP a mano: usar el instalador. `validate.py` sin `--runtime` valida el paquete portable, no la instalación.

Publicar una versión: `main` está protegida (exige CI verde), así que la versión se prepara en una rama y `scripts/release.py VERSION --push --install` solo etiqueta, publica e instala. Pasos en [PILOTO.md](PILOTO.md#flujo-de-mantenimiento).

## Modelos

```text
$pol-devflow config show
$pol-devflow config set --runtime codex --role reviewer --model MODELO --effort high
$pol-devflow config set --runtime claude --role implementer --model MODELO
$pol-devflow config set --runtime codex --role tester --inherit
```

Configurar un modelo no prueba acceso real. Los cambios afectan a ejecuciones futuras (las abiertas conservan su snapshot). En Orca, sin configuración central, se hereda la sesión.

## Garantías y límites

Scopes contrastados con cambios confirmados, staged, sin stage y archivos nuevos no ignorados. Comprobaciones obligatorias no reducibles y hallazgos conservados. Fixer con clave estable y tres ciclos por problema. Reviewer recibe el diff completo con hash; el Coordinator nunca cuenta como reviewer independiente. El helper compara identidades declaradas, no las autentica. Archivos ignorados y cambios externos a Git no son frontera de seguridad. Ver [procedimiento](core/coordinator.md), [entorno Git](core/rules/git-worktrees.md) y VERIFICATION.md.

## Licencia

MIT. Ver [LICENSE](LICENSE).

## Historial

- 1.0.17: presupuesto por run, registro de funciones usadas (`stats --features`), retro de proceso, reglas del proyecto y `scripts/release.py`.
- 1.0.18: entrega breve con guards, review delta ligada a cobertura/ancestro, pautas de pruebas seguras y métricas por actividad.
- 1.0.16: subdelegación comprobada en Claude Code y espera obligatoria de los hijos.
- 1.0.15: subdelegación nativa optativa de un nivel en full (grants, solo lectura, máx. 4 workers activos).
- 1.0.14: delegación nativa preferida también dentro de Orca; executor fijo por run.
- 1.0.13: prevalidación de resultados, plantillas canónicas, tiempos de pared, salida UTF-8 y borrado Orca confirmado.
- 1.0.12: nivel lite+review, `code_map` con `--context-from` y sugerencia de modelo de sesión.
- 1.0.11: codegraph optativo y aislamiento de skills de proceso de otros plugins.
- 1.0.10: incidencia frente a defecto, presupuesto por worker, identidad Git, `check-close` y cleanup de contenido equivalente.
- 1.0.9: commits con finales de línea CRLF.
- 1.0.8: métricas (`stats`), perfil de comandos verificados, olas de lectura en native, CI y evals.
- 1.0.7: memoria optativa por proyecto, lite más ligero y cleanup limitado al repositorio actual.
