# feature

Objetivo: implementar el comportamiento acordado dentro de la arquitectura existente.
Si el nivel es lite, seguir [lite](lite.md) en lugar de estos pasos.
1. Inspeccionar convenciones, criterios, base y dependencias. Resolver ambigüedades relevantes de producto.
2. Preparar el entorno del worktree y comprobar su funcionamiento inicial.
3. Usar Architect para diseño no trivial; definir contratos antes de dividir tareas.
4. Asignar implementación con scopes y dependencias explícitos. Las escrituras son secuenciales; las investigaciones independientes de lectura pueden ir en una ola antes de implementar.
5. Implementar, añadir tests útiles y crear checkpoints propios; en correcciones, solo tests afectados.
6. Validar el candidato final con las comprobaciones completas y obtener revisión independiente del diff integrado cuando sea obligatoria (Tester de ejecución y Reviewer pueden ir en paralelo); las sugerencias no disparan fixes.
7. Verificar correcciones aceptadas y cerrar con evidencia actual de todos los criterios.

En tareas pequeñas Coordinator puede implementar y probar; su propia revisión no acredita independencia.
