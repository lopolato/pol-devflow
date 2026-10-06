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
- Reglas o pasos que parecieron sobrar o que el Coordinator se saltó.
- Preguntas que hizo y si eran necesarias.

## Después del piloto: candidatos a recortar

Revisar con las notas si se usan de verdad; lo que no se use, hacerlo optativo o quitarlo:

- Adaptador Orca y su accounting (si no se usa Orca a diario).
- Borrado remoto en cleanup (`--remote`).
- Memoria por áreas (`schema_version: 2`) y retención de historial.
- Context7 (si las dudas de API son raras).
- Plantilla de resultado de 21 campos en full (si los workers la rellenan mal o encarece mucho).

## Flujo de mantenimiento

Este repositorio es la fuente única. Para cambiar algo:

```text
editar → python -m unittest discover -s tests → python scripts/validate.py
git commit → python scripts/install.py --runtime all
python scripts/validate.py --runtime claude
python scripts/validate.py --runtime codex
```

Modelos: `python scripts/devflow.py config set ...` (regenera los agentes; no editarlos a mano).

Evaluaciones de comportamiento (gastan tokens; ver `evals/README.md`): `python evals/run_evals.py --dry-run` para preparar, `--scenario ID` para ejecutar una.
