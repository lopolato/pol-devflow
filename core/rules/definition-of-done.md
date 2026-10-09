# Validación, review y evidencia

Con memoria activada, el cierre incluye el informe clasificado y la evaluación de impacto según [memoria del proyecto](project-memory.md); sin ella, el resumen va en el informe final del chat. Verificar documentación afectada frente al código y conservar evidencia de revisión/cobertura. Documentación necesaria pendiente impide completed; no obligar a editar documentos sin impacto.

Con executor orca, completed exige settlement aceptado y accounting registrado de cada encargo, además de comprobar el Run real y ausencia de terminales reclamables. El CLI verifica consistencia del puente; no autentica recibos ni consulta actividad. Con executor native, contrastar entregas, identidad y actividad con la API anfitriona real; la propiedad Orca del workspace no exige settlement/accounting Orca para esos workers. Context7/documentación externa aportan contexto versionado, nunca evidencia suficiente de implementación por sí solos.

Cada comprobación registra procedimiento o comando, workspace, versión del código y resultado:

~~~text
passed | failed | not_run | not_applicable
~~~

`not_run` incluye el motivo. `not_applicable` exige una justificación concreta; no sirve para ocultar una comprobación necesaria que no pudo ejecutarse.

La evidencia final se vincula a un commit y un workspace sin modificaciones posteriores relevantes. Si hay cambios después, invalidar y repetir las comprobaciones afectadas.

El Reviewer inspecciona el requisito, los criterios, el diff entre base y versión final y el código relevante. Los handoffs aportan contexto, pero no sustituyen la inspección independiente.

El encargo reviewer aporta el diff completo en review_diff con ruta absoluta, SHA-256 y revisiones. Claude lo inspecciona con Read; un resumen del Coordinator no equivale al diff. Si falta acceso o evidencia, devolver incomplete. El CLI exige el rol reviewer del encargo y comprueba integridad del artefacto al recibir su resultado.

Clasificar hallazgos:

- **blocker:** incumplimiento o regresión que impide cerrar;
- **suggestion:** mejora opcional que no impide cumplir el objetivo;
- **out_of_scope:** problema ajeno que se informa sin arreglar automáticamente.

Cada blocker incluye ubicación, condición de aparición, impacto y evidencia. El Coordinator verifica su pertinencia antes de encargar la corrección. Las sugerencias no activan al Fixer.

Una aprobación corresponde únicamente a la versión revisada. Después de corregir un blocker, verificar la corrección, las regresiones relacionadas y el diff final.

required_checks conserva las comprobaciones establecidas. validations y criteria_results conservan su historial. Los hallazgos existentes no se borran ni editan por update. Resolver por id mediante _run resolve con evidencia, revisión actual y nombre de una validación passed de esa versión; conservar el historial de resolución. Un fallo posterior de esa comprobación invalida el cierre aunque hubiera pasado antes.

Para optimización, registrar métrica, datos, condiciones y mediciones comparables antes/después. Usar varias muestras cuando haya variabilidad apreciable. Si no se puede demostrar la mejora mediante mediciones o evidencia objetiva alternativa, entregar parcial con la optimización sin verificar.
