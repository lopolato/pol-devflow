# Validación, review y evidencia

Con memoria activada, el cierre incluye el informe clasificado y la evaluación de impacto según [memoria del proyecto](project-memory.md); sin ella, el resumen va en el informe final del chat. Verificar documentación afectada frente al código y conservar evidencia de revisión/cobertura. Documentación necesaria pendiente impide completed; no obligar a editar documentos sin impacto.

Con executor orca, completed exige settlement aceptado y accounting registrado de cada encargo, además de comprobar el Run real y ausencia de terminales reclamables. El CLI verifica consistencia del puente; no autentica recibos ni consulta actividad. Con executor native, contrastar entregas, identidad y actividad con la API anfitriona real; la propiedad Orca del workspace no exige settlement/accounting Orca para esos workers. Context7/documentación externa aportan contexto versionado, nunca evidencia suficiente de implementación por sí solos.

Cada comprobación registra procedimiento o comando, workspace, versión del código y resultado:

La suite completa también puede acreditarse con CI solo si valida el mismo SHA y el entorno aplica al proyecto. No repetir una suite local completa ya cubierta por ese resultado; ejecutar localmente las regresiones afectadas por cambios posteriores.

~~~text
passed | failed | not_run | not_applicable
~~~

`not_run` incluye el motivo. `not_applicable` exige una justificación concreta; no sirve para ocultar una comprobación necesaria que no pudo ejecutarse.

La evidencia final se vincula a un commit y un workspace sin modificaciones posteriores relevantes. Si hay cambios después, invalidar y repetir las comprobaciones afectadas.

La primera review inspecciona el diff completo y el código relevante. Una review posterior puede usar `--review-from TASK_ID` solo si una review registrada con veredicto `passed` o `changes_required` incluye cobertura explícita de un reviewer independiente y su revisión es ancestro Git del candidato. Una review `incomplete` no puede ser fuente. El encargo conserva el artefacto/hash del diff completo y agrega el delta desde esa revisión y los hallazgos pendientes. El Reviewer inspecciona el delta y la cobertura previa; la decisión sigue siendo nueva y explícita. Sin fuente válida, se encarga una review completa.

El encargo reviewer conserva `review_diff` completo con ruta absoluta, SHA-256 y revisiones, y puede añadir `review_delta` con sus propios hashes/revisiones. El Reviewer inspecciona el artefacto indicado en el encargo; un resumen del Coordinator no equivale al diff. Si falta acceso o evidencia, devolver incomplete. Toda review incluye `review.coverage` explícita. El CLI comprueba la integridad de los artefactos al recibir el resultado.

Clasificar hallazgos:

- **blocker:** incumplimiento o regresión que impide cerrar;
- **suggestion:** mejora opcional que no impide cumplir el objetivo;
- **out_of_scope:** problema ajeno que se informa sin arreglar automáticamente.

Cada blocker incluye ubicación, condición de aparición, impacto y evidencia. El Coordinator verifica su pertinencia antes de encargar la corrección. Las sugerencias no activan al Fixer.

Una aprobación corresponde únicamente a la versión revisada. Después de corregir un blocker, verificar la corrección, las regresiones relacionadas y el diff final.

required_checks conserva las comprobaciones establecidas. validations y criteria_results conservan su historial. Los hallazgos existentes no se borran ni editan por update. Resolver por id mediante _run resolve con evidencia, revisión actual y nombre de una validación passed de esa versión; conservar el historial de resolución. Un fallo posterior de esa comprobación invalida el cierre aunque hubiera pasado antes.

Para optimización, registrar métrica, datos, condiciones y mediciones comparables antes/después. Usar varias muestras cuando haya variabilidad apreciable. Si no se puede demostrar la mejora mediante mediciones o evidencia objetiva alternativa, entregar parcial con la optimización sin verificar.
