# Evals de comportamiento

Los tests unitarios (`tests/`) solo comprueban los helpers Python. Estas evals comprueban si el **Coordinator real** sigue la skill: elige lite o full correctamente, pol-lite respeta los límites, no crea `docs/devflow/` sin opt-in, no hace push, confirma solo los archivos tocados y nunca hace commit en main.

> **Coste:** cada escenario lanza una sesión real del LLM y consume tokens (los escenarios lite delegan además en `pol-lite`). No se ejecutan en CI. Empieza con `--dry-run` y con un solo `--scenario`.

## Qué hace

[run_evals.py](run_evals.py) (solo stdlib), por cada escenario de [scenarios/](scenarios/):

1. Crea un repo Git mínimo en un directorio temporal (rama `main` con commit, ramas extra o cambio sin commit si el escenario lo pide). Nunca usa tus repos.
2. Ejecuta el agente con `cwd` = ese repo y `DEVFLOW_DATA_HOME` aislado (el estado DevFlow no toca tu historial real).
3. Guarda la transcripción y evalúa expectativas deterministas sobre Git y el texto.

Se evalúa la skill **instalada** en el runtime (p. ej. `~/.claude/skills/pol-devflow`), no este checkout: reinstala antes si has cambiado algo.

| Escenario | Comprueba |
| --- | --- |
| `lite-small-bug` | rama `fix/`, ≤3 archivos de producto, main intacto, sin `docs/devflow`, tests verdes en la rama, checkout limpio |
| `plan-only` | sin ramas, commits ni cambios en el working tree |
| `lite-dirty-checkout` | con cambios del usuario sin commit: no hay commits y el cambio se conserva |
| `auth-chooses-full` | tarea de permisos sin flag (en `--plan-only`): la transcripción menciona full |
| `cleanup-no-history` | `cleanup --apply` sin historial DevFlow: no se borra ninguna rama |
| `lite-memory-opt-in` | con `docs/devflow/memory.json`: informe en `docs/devflow/reports/` en la rama `fix/` |

Vocabulario de expectativas: `branch_created_prefix`, `no_new_branches`, `branches_preserved`, `main_unchanged`, `no_new_commits`, `max_product_files_changed` (excluye `docs/devflow/`), `path_absent`, `path_present`, `worktree_clean`, `user_change_preserved`, `command_passes`, `transcript_contains_any`, `no_remote_push`.

## Cómo ejecutar

```bash
python evals/run_evals.py --list                                   # escenarios
python evals/run_evals.py --dry-run                                # crea fixtures y muestra comandos; no llama al agente
python evals/run_evals.py --scenario lite-small-bug                # uno, con Claude (gasta tokens)
python evals/run_evals.py                                          # todos
python evals/run_evals.py --runner codex --scenario plan-only      # Codex (plantilla best-effort)
python evals/run_evals.py --runner-cmd "mi-agente --prompt {prompt}"   # comando propio ({prompt}, {repo})
```

Opciones: `--model`, `--permission-mode` (por defecto `acceptEdits`), `--allowed-tools` (por defecto permite `git` y `python` en Bash), `--timeout` (s por escenario, 900), `--keep` (conserva los repos temporales), `--out DIR` (fuera de cualquier repo Git).

`--allow-skip-permissions` añade el flag de bypass del runner (`--dangerously-skip-permissions` / `--dangerously-bypass-approvals-and-sandbox`). Solo si lo pasas explícitamente; imprime un aviso. Sin él, cualquier bypass se rechaza.

## Cómo leer los resultados

La tabla final muestra por escenario `PASS`, `FAIL` (alguna expectativa falla; se lista cuál y por qué) o `ERROR` (el agente no arrancó o superó el timeout). `results.json` y `<escenario>/transcript.txt` quedan en el directorio de salida indicado al final.

Un `FAIL` es una señal para revisar la transcripción, no un veredicto: el LLM no es determinista y `transcript_contains_any` es tolerante a propósito. Repite el escenario antes de cambiar la skill. Con Codex, la transcripción incluye el prompt, así que las comprobaciones de texto son menos fiables.
