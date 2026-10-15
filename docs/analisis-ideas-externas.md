# Ideas externas adoptadas en la 1.0.24

Fecha: 15/10/2026. Se toman ideas, no texto ni código.

## Fuentes

- [Ponytail](https://github.com/DietrichGebert/ponytail) (MIT): reglas de minimalismo para agentes de código.
- [Context Mode](https://github.com/mksglu/context-mode) (ELv2): saca del contexto las salidas grandes de herramientas.
- [Skills de Matt Pocock](https://github.com/mattpocock/skills) (MIT), en particular `grill-me`.

## Adoptado

| Idea | Origen | En DevFlow |
|---|---|---|
| Escalera de decisión antes de escribir código; nunca recortar validación, pérdida de datos, seguridad ni accesibilidad | Ponytail | Contrato de worker, roles que escriben código |
| Atajos con un límite conocido, anotados | Ponytail (`ponytail:` y `/ponytail-debt`) | Se declaran en `risks` del resultado, sin comentarios en el código del proyecto |
| Revisión de lo que sobra | Ponytail (`/ponytail-review`) | Lente `simplicity`, solo sugerencias |
| Salida completa en disco, resumen en el contexto | Context Mode (sandbox y búsqueda posterior) | `_check run` con log por run o lite |
| Interrogar el plan pregunta a pregunta, con respuesta recomendada | `grill-me` | Regla de aclaración |

## No adoptado

- Instalar Ponytail o Context Mode tal cual: sus hooks actúan en todas las sesiones (Context Mode además bloquea y redirige herramientas), sin control por tarea ni forma de medir su efecto dentro de DevFlow. Context Mode tiene licencia ELv2 y pide Node 22.5 o superior.
- Niveles de intensidad de Ponytail (lite/full/ultra): DevFlow ya decide el nivel por riesgo.
- Índice FTS5 y memoria de sesión de Context Mode: el estado de cada run ya vive fuera del chat (`status --brief`).
- XERJ (buscador local), claude-code-mcp (archivado, salta permisos) y Code Modernization (código heredado): no aplican.

## Cómo medir

Comparar con `stats` antes y después: `avg_task_elapsed_s` por rol, tokens cuando el anfitrión los informe y líneas cambiadas por tarea. La cifra de Ponytail (−54% de código, −22% de tokens) procede de un solo proyecto, 12 tareas y un modelo, y su README advierte que con modelos de razonamiento escuetos el coste puede subir.
