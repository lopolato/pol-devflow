# error

Objetivo: eliminar el defecto reportado y demostrar la corrección en la revisión actual.
Si el nivel es lite, seguir [lite](lite.md) en lugar de estos pasos.
1. Inspeccionar preflight y comportamiento esperado. Preparar el entorno del worktree.
2. Usar Debugger para diagnóstico no trivial; reproducir y separar causa confirmada de hipótesis.
3. Asignar Fixer con diagnóstico, reproducción, alcance mínimo y correction_key estable obligatoria.
4. Registrar cada intento bajo esa misma clave; respetar el presupuesto restante.
5. Verificar la reproducción original y comportamientos cercanos; añadir regresión cuando sea útil.
6. Confirmar rutas propias y registrar tests/build/typecheck/lint pertinentes con su revisión.
7. Obtener review independiente obligatoria, corregir blockers aceptados y resolverlos con evidencia actual.
8. Cerrar mediante controles; si faltan verificaciones, informar partial/blocked preservando el trabajo.

Un bug pequeño puede combinar Fixer/Tester en Coordinator sin lanzar todos los perfiles.
