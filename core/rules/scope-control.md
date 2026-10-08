# Alcance

Implementar la petición y lo necesario para satisfacerla o corregir su causa.
Registrar hallazgos ajenos como out_of_scope; no corregirlos automáticamente.
Respetar permisos, tests, selección de modelos y convenciones del proyecto.
Los roles son responsabilidades; usar la estructura mínima que cumpla los criterios. En cambios que cruzan varios subsistemas, fijar entregables con contratos, rutas y aceptación verificable por frontera; evitar un único encargo amplio sin checkpoints útiles. Esto no autoriza writers concurrentes en el mismo checkout: secuenciar las escrituras y agrupar solo lecturas independientes.
Exigir revisión independiente para permisos/seguridad, reglas de negocio relevantes, migraciones, concurrencia, integración paralela y requisitos explícitos del usuario/proyecto. Lite+review la aporta en cambios que cumplen lite; el resto, full.
El Reviewer debe ser distinto de todos los autores y del Coordinator. Las etiquetas del CLI no autentican esa independencia; comprobar el mapeo con la ejecución nativa.
