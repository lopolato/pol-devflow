# Adaptador de Claude Code

Generar `pol-<rol>.md` con frontmatter YAML e instrucciones compartidas. El modelo hereda por defecto. Prohibir delegación Agent. Reviewer usa Read/Glob/Grep y lee el diff completo generado por `_run task`, cuya ruta y hash aparecen en review_diff; no necesita ejecutar Bash.

El entrypoint del ZIP es portable. Al instalar, el adaptador añade `disable-model-invocation: true` y `argument-hint` al SKILL.md de Claude. Esta transformación es deliberada: el contenido operativo comparte origen y los metadatos son específicos del runtime. No añadir esas claves al entrypoint de Codex.

La transformación es idempotente: una actualización desde un entrypoint ya adaptado conserva una única copia de cada clave nativa. No copiar directamente el entrypoint portable sobre el instalado. `scripts/validate.py --runtime claude` comprueba que la restricción está en el frontmatter instalado y que los archivos coinciden con el manifiesto.

Coordinator permanece en la conversación principal. Seleccionar perfil nativo y pasar el encargo. Comprobar sustituciones/advertencias reales de modelos. Inicio, espera, recogida y cancelación son acciones de la sesión, no otro proceso Claude oculto.

Pasar el workspace exacto, comprobar permiso de acceso al worktree y al archivo de diff mediante mecanismos nativos existentes. No ampliar globalmente permisos ni desactivar comprobaciones. Si falta acceso necesario, informar el bloqueo y solicitar únicamente el acceso concreto.

V1 usa un workspace secuencial, no uno por rol. Preparar dependencias y configuración según reglas Git. Las identidades declaradas no son autenticadas por el helper; Coordinator mantiene el mapeo real. Si no puede acreditar review independiente obligatoria, informar partial.

[Documentación oficial](https://code.claude.com/docs/en/sub-agents).
