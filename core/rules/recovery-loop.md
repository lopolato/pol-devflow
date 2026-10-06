# Estados, recuperación y cancelación

## Estados de cierre

| Estado | Significado |
|---|---|
| `completed` | Criterios cumplidos y comprobaciones necesarias aprobadas o justificadamente no aplicables; review aprobada si es obligatoria. |
| `partial` | Hay trabajo entregable, pero falta parte del objetivo, una validación o una review. |
| `blocked` | No se puede avanzar sin una respuesta, capacidad, dependencia o cambio externo identificado. |
| `cancelled` | El usuario solicitó detener el trabajo. |

Durante la ejecución se usan fases activas; estos son estados de cierre de DevFlow, no los estados internos de las herramientas. Si una ejecución bloqueada o cancelada contiene trabajo útil, también se describe.

No emitir `DEVFLOW COMPLETE` para resultados parciales. El informe usa `DEVFLOW RESULT`, el estado real, cambios, validación, evidencia pendiente y siguiente acción.

## Recuperación acotada

Distinguir fallos del cambio, fallos preexistentes y problemas de entorno. Corregir automáticamente solo los relacionados con el objetivo o las regresiones introducidas.

Máximo obligatorio: tres ciclos por tarea. Un ciclo comprende corrección y comprobación posterior. Cambiar de worker no reinicia el contador. Repetir una comprobación sin cambiar código no crea un ciclo nuevo.

Fixer recibe correction_key explícita y estable; los reemplazos heredan esa clave y no pueden sobrescribirla. Registrar el resultado del ciclo después de ejecutarlo y antes de encargar el siguiente. El contador registra ciclos realizados, no reservas; al registrar el tercero se impide asignar el cuarto. Coordinator mantiene la correspondencia entre problemas y claves; el helper no deduce que dos etiquetas distintas describan el mismo problema.

Detener antes si se repite el mismo fallo sin evidencia nueva. Un nuevo enfoque puede probarse con el presupuesto restante si tiene fundamento.

Registrar además hasta tres ciclos de corrección de integración: los presupuestos de tareas hijas no permiten reparar indefinidamente la raíz.

Al agotar el límite, entregar parcial o bloqueado según la causa, con intentos, estado actual y siguiente paso. No desactivar tests ni rebajar criterios para declarar éxito.

## Cancelación y ambigüedades

Al cancelar el usuario, dejar de asignar trabajo, solicitar cancelación de workers y registrar qué llegó a modificarse. No eliminar resultados automáticamente.

Ante una ambigüedad material, detener el trabajo dependiente de esa decisión y continuar únicamente tareas independientes. Solo el Coordinator pregunta al usuario. El silencio no se interpreta como una elección.
