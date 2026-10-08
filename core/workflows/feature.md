# feature

Objetivo: implementar el comportamiento acordado dentro de la arquitectura existente.
Si el nivel es lite, seguir [lite](lite.md) en lugar de estos pasos.
1. Inspeccionar convenciones, criterios, base y dependencias. Resolver ambigüedades relevantes de producto.
2. Preparar el entorno del worktree y comprobar su funcionamiento inicial.
3. Usar Architect para diseño no trivial; definir contratos antes de dividir tareas.
4. Asignar implementación con scopes y dependencias explícitos. Las escrituras son secuenciales; las investigaciones independientes de lectura pueden ir en una ola antes de implementar.
5. Implementar, añadir tests útiles y crear checkpoints propios. En cambios con estado y varios pasos, incluir la prueba de integración del recorrido principal en la primera entrega.
6. Obtener revisión independiente del diff integrado cuando sea obligatoria y ejecutar pruebas dirigidas (Tester y Reviewer de lectura pueden ir en paralelo). Corregir solo blockers aceptados y usar tests afectados durante las correcciones; las sugerencias no disparan fixes.
7. Tras aprobar las correcciones, ejecutar las comprobaciones completas y costosas sobre el candidato final; cerrar con evidencia actual de todos los criterios.

En tareas pequeñas Coordinator puede implementar y probar; su propia revisión no acredita independencia.
