# Cierre, integración y limpieza

`completed` acredita desarrollo y comprobaciones, no push, despliegue ni limpieza. En la entrega separar cada operación solicitada: desarrollo/revisión (SHA), integración (destino/SHA), publicación (remoto/ref/SHA observado), producción (revisión ejecutada y salud) y limpieza (rama local/remota, worktree Git, workspace Orca y carpeta residual). Indicar comprobada, pendiente, no solicitada o fallida; nunca inferir una de otra.

No dejar main/master en el workspace temporal de tarea. Integrar en el checkout principal cuando sea viable; si ya está en el temporal, preparar el traslado con ambos checkouts limpios y sin escritores. Preservar checkouts de otras tareas activas. Cleanup nunca elimina main/master.

Reconciliar Run/Task/Dispatch con la actividad real antes del cierre. Registrar settlement/accounting también de intentos fallidos o sustituidos. No marcar detenido por antigüedad o ausencia de respuesta. Conservar el bloqueo concreto si no se puede comprobar; no presentar incertidumbre operativa como limpieza terminada.

Mostrar una vista previa del alcance concreto y obtener una confirmación de cleanup. Esta cubre todos los elementos y pasos enumerados; no repetirla por paso. Añadir otra rama/workspace, descartar commits sin integrar o purgar evidencia exige ampliar el alcance. El borrado remoto es optativo (`--remote REMOTO`); borrar localmente no borra GitHub.

En Orca comprobar identidad y actividad de workers/terminales con la guía instalada. `--orca-idle-confirmed` registra la declaración del Coordinator, no la autentica ni detiene procesos. Tras error de transporte consultar Git y Orca antes de reintentar. Comprobar también la carpeta residual y comunicar cualquier resultado parcial; no forzar borrados ni eludir una denegación de política.

Contrastar archivos/diffs e historia antes de afirmar «no está integrado»: una función puede existir bajo otros commits. Distinguir la función principal de una mejora pendiente y las ramas de respaldo del trabajo actual.
