# Piloto de Pol DevFlow 1.0.8

Objetivo: probar la skill con un proyecto real antes de añadir nada más, y decidir qué partes recortar.

Usar un proyecto pequeño y propio, con Git limpio y en main. Abrir una sesión nueva (Claude Code o Codex) para que cargue la 1.0.8.

## Pasos

| # | Comando | Qué comprobar |
|---|---|---|
| 1 | `/pol-devflow cleanup` | Lista coherente; no borra nada; no aparecen ramas de otros proyectos. |
| 2 | `/pol-devflow error --plan-only <bug real>` | Propone lite o full con un motivo razonable; no crea ramas ni archivos. |
| 3 | `/pol-devflow error --lite <bug real pequeño>` | Crea la rama en la misma carpeta; el trabajo lo hace `pol-lite` (Sonnet / gpt-6-luna); tests reales; commit solo de los archivos tocados; no escribe `docs/devflow/`. |
| 4 | Mezclar la rama a mano y `/pol-devflow cleanup` | Propone retirar la rama; con `--apply` y tu confirmación, la borra. |
| 5 | `/pol-devflow feature <feature mediana>` | Worktree con entorno preparado; reviewer con Opus / gpt-6.1-sol; cierre con evidencia. |

## Qué anotar en cada paso

- ¿Hizo lo esperado? Si no, qué hizo.
- Modelos que aparecen en el resumen final (configurado y efectivo).
- Tiempo y tokens: tras cada tarea, `/pol-devflow stats` muestra lo registrado por rol.
- Si se guardó el perfil del proyecto (`_profile show`) y si la segunda tarea reutilizó sus comandos sin redescubrirlos.
- Reglas o pasos que parecieron sobrar o que el Coordinator se saltó (`/pol-devflow retro` resume las retros guardadas).
- Preguntas que hizo y si eran necesarias.

## Después del piloto: candidatos a recortar

Revisar con las notas y con `/pol-devflow stats --features --all` (`never_used`) si se usan de verdad; lo que no se use, hacerlo optativo o quitarlo:

- Adaptador Orca y su accounting (si no se usa Orca a diario).
- Borrado remoto en cleanup (`--remote`).
- Memoria por áreas (`schema_version: 2`) y retención de historial.
- Context7 (si las dudas de API son raras).
- Plantilla de resultado de 21 campos en full (si los workers la rellenan mal o encarece mucho).

## Flujo de mantenimiento

Este repositorio es la fuente única. `main` está protegida en GitHub: exige los checks de CI (ubuntu/windows × Python 3.11/3.12), también para administradores, así que nada se confirma directamente en main.

```text
git switch -c feat/X                      # editar en una rama
python -m unittest discover -s tests      # y python scripts/validate.py
# versión: scripts/devflow/__init__.py, sección "## X.Y.Z" en VERIFICATION.md,
#          primer título "# Pol DevFlow X.Y.Z" en README.md y línea en su Historial
git push -u origin feat/X                 # esperar CI verde
git switch main && git merge --ff-only feat/X && git push origin main
python scripts/release.py X.Y.Z --push --install
```

`scripts/release.py` no edita ni confirma nada: comprueba main limpia y al día con origin, versión mayor que el último tag y ya declarada en `__init__.py`, VERIFICATION y README; verifica los checks de GitHub del commit con `gh` si está autenticado (`--skip-ci-check` para omitirlo); ejecuta tests y `validate.py` (`--skip-tests` avisa de que CI debe estar en verde); crea el tag anotado `vX.Y.Z`; con `--push` publica main y el tag de forma atómica, y con `--install` instala en ambos runtimes y valida cada instalación. `--dry-run` muestra cada paso sin cambiar nada. `--evals` ejecuta además `evals/check_claude_nesting.py` y el escenario `lite-small-bug` (gastan tokens; pide confirmación o `--yes`).

Modelos: `python scripts/devflow.py config set ...` (regenera los agentes; no editarlos a mano).

Evaluaciones de comportamiento (gastan tokens; ver `evals/README.md`): `python evals/run_evals.py --dry-run` para preparar, `--scenario ID` para ejecutar una.
