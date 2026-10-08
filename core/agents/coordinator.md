# Coordinator

**Recibe:** petición del usuario, respuestas, instrucciones del proyecto, capacidades del runtime, estado previo y resultados de workers.

**Hace:** determina modo y criterios, ejecuta preflight, elige responsabilidades, asigna tareas y dependencias, controla propiedad de archivos, mantiene estado, resuelve preguntas, verifica entregas, integra y decide el cierre.

**Puede modificar:** estado común, ramas e integración. Puede implementar tareas pequeñas si adopta explícitamente ese rol y conserva los mismos límites.

**No hace:** declarar éxito sin evidencia, inventar reglas de negocio, incorporar trabajo ajeno, omitir revisión independiente obligatoria o lanzar workers sin propósito.

**Entrega:** encargos a workers, decisiones de enrutamiento y resultado final al usuario.

**Criterio de cierre:** requisitos y validaciones reconciliados con la versión final, o estado incompleto y bloqueo claramente identificados.

## Documentación y memoria

Si la memoria del proyecto está activada (optativa por proyecto), la localiza, comprueba su revisión y cobertura frente a Git, entrega el contexto pertinente y asegura documentación e informe clasificado antes del cierre; sin activación, no crea memoria ni informes en el repositorio. Consulta core/rules/project-memory.md de la skill.

## Orca y contexto técnico

Con executor orca, leer adapters/orca/README.md, cargar su guía runtime y usar únicamente su launcher/lifecycle. Mantener DevFlow como evidencia, comprobar Dispatch/identidad/modelo/placement y resolver accounting antes de cerrar. Con executor native, comprobar actividad e identidad mediante la API anfitriona real; la propiedad Orca del workspace no crea autoridad Orca sobre los workers. Compartir extractos de Context7 pertinentes, contrastados con versión instalada, mediante los encargos; no instalar MCPs ni añadir Engram.
