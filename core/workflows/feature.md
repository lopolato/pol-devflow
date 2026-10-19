# feature

Objetivo: implementar el comportamiento acordado dentro de la arquitectura existente.
Si el nivel es lite, seguir [lite](lite.md) en lugar de estos pasos.
1. Inspeccionar convenciones, criterios, base y dependencias. Resolver ambigüedades relevantes de producto.
2. Preparar el entorno del worktree y comprobar su funcionamiento inicial.
3. Usar Architect para diseño no trivial; definir contratos antes de dividir tareas.
4. Asignar implementación con scopes y dependencias explícitos. Las escrituras son secuenciales; las investigaciones independientes de lectura pueden ir en una ola antes de implementar.
5. Implementar, añadir tests útiles y crear checkpoints propios. En cambios con estado y varios pasos, incluir la prueba de integración del recorrido principal en la primera entrega.
   Si cambia una interfaz y hay navegador disponible, comprobar pronto el recorrido crítico con la página y los assets reales, antes de la primera review; no sustituirlo por pruebas de cadenas o renderizado. Al reutilizar una interfaz compartida, verificar también su contexto original y el orden real de carga/registro de eventos. Cubrir los extremos que cambian la navegación o el resultado (p. ej. mezcla de filas válidas y omitidas, o todas omitidas), sin ampliar pruebas ajenas al cambio. Si falta navegador, registrar ese límite y seguir la condición de cierre del paso 7.
6. Obtener revisión independiente del diff integrado cuando sea obligatoria y ejecutar pruebas dirigidas (Tester y Reviewer de lectura pueden ir en paralelo). Corregir solo blockers aceptados y usar tests afectados durante las correcciones; las sugerencias no disparan fixes.
7. Tras aprobar las correcciones, ejecutar las comprobaciones completas y costosas sobre el candidato final; cerrar con evidencia actual de todos los criterios. Un criterio visual se comprueba en un navegador si la sesión tiene uno; si no, pedir al usuario una comprobación concreta antes de cerrar como parcial.

En tareas pequeñas Coordinator puede implementar y probar; su propia revisión no acredita independencia.
