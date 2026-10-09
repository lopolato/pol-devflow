# error

Objetivo: eliminar el defecto reportado, demostrar la corrección en la revisión actual y comprobar la incidencia reportada. Corregir un defecto no prueba que fuera la causa del síntoma.
Si el nivel es lite, seguir [lite](lite.md) en lugar de estos pasos.
1. Inspeccionar preflight y comportamiento esperado. Preparar el entorno del worktree. Registrar pronto `incident` {symptom, status, evidence} con `_run update`.
2. Usar Debugger para diagnóstico no trivial; reproducir y separar causa confirmada de hipótesis.
3. Asignar Fixer con diagnóstico, reproducción, alcance mínimo y correction_key estable obligatoria.
4. Registrar cada intento bajo esa misma clave; respetar el presupuesto restante.
5. Verificar la reproducción original y comportamientos cercanos con tests afectados; añadir un test de regresión del defecto. Verificar la incidencia es reproducir o inspeccionar el caso reportado (datos y ruta reales que produjeron el síntoma), no solo un defecto en código cercano. Fijar `incident.status`: resolved, not_verified, different_cause o accepted_unverified (con `accepted_by`, solo si el usuario lo acepta expresamente).
6. Confirmar rutas propias y obtener review independiente obligatoria; puede ir en paralelo con un Tester de pruebas dirigidas sobre el mismo candidato limpio. Corregir blockers aceptados y resolverlos con evidencia actual.
7. Tras aprobar las correcciones, ejecutar tests/build/typecheck/lint completos y las verificaciones costosas requeridas sobre el candidato final, con su revisión.
8. Cerrar mediante controles; completed exige incidencia resolved o accepted_unverified. Si no, informar partial/blocked preservando el trabajo.
9. Con el defecto corregido, proponer una regla `must_not` con `_rules add` (rutas del defecto, test de regresión `path::name`, source {type: bug, ref: RUN_ID}); queda `inferred` hasta que el usuario la confirme (`_rules confirm`). Optativa: nunca retrasa el cierre.

Un bug pequeño puede combinar Fixer/Tester en Coordinator sin lanzar todos los perfiles.
