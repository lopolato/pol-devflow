# Adaptador de Claude Code

Generar `pol-<rol>.md` con frontmatter YAML e instrucciones compartidas. El modelo hereda por defecto. Solo los padres lectores con grant explícito pueden invocar Agent en full/native; las instrucciones bloquean la herramienta para hojas sin grant. El Coordinator registra y conserva el estado de cada hijo. Reviewer usa Read/Glob/Grep y lee el diff completo generado por `_run task`, cuya ruta y hash aparecen en review_diff; no necesita ejecutar Bash.

El entrypoint del ZIP es portable. Al instalar, el adaptador añade `disable-model-invocation: true` y `argument-hint` al SKILL.md de Claude. Esta transformación es deliberada: el contenido operativo comparte origen y los metadatos son específicos del runtime. No añadir esas claves al entrypoint de Codex.

La transformación es idempotente: una actualización desde un entrypoint ya adaptado conserva una única copia de cada clave nativa. No copiar directamente el entrypoint portable sobre el instalado. `scripts/validate.py --runtime claude` comprueba que la restricción está en el frontmatter instalado y que los archivos coinciden con el manifiesto.

Coordinator permanece en la conversación principal. Habilitar subdelegación solo tras un preflight vivo en la sesión Claude que compruebe Agent anidado, y registrar el texto de evidencia con --can-delegate, --native-nesting-evidence y --native-max-workers. En una sesión Claude Code, preferir su herramienta Agent comprobada y el perfil `pol-<rol>.md`, incluso dentro de Orca. Si solo hay agente genérico, incluir contrato y rol sin afirmar que se cargó un perfil. Aplicar run.config_snapshot y comprobar sustituciones/advertencias reales; no inventar equivalencias con modelos Codex. Inicio, espera, recogida y cancelación son acciones de la sesión anfitriona, nunca otro proceso Claude oculto ni pegado en TUI. Una petición explícita de workers Orca usa su adaptador; sin API nativa, comprobar Orca o informar bloqueo. Un CLI Claude instalado o una prueba Codex no acreditan acceso a Agent en esta sesión.

Pasar el workspace exacto, comprobar permiso de acceso al worktree y al archivo de diff mediante mecanismos nativos existentes. No ampliar globalmente permisos ni desactivar comprobaciones. Si falta acceso necesario, informar el bloqueo y solicitar únicamente el acceso concreto.

V1 usa un workspace compartido, no uno por rol: lecturas independientes pueden ir en ola sobre la misma revisión limpia; writers de uno en uno. Al completar un subagente, Claude Code informa tokens y duración: pasarlos en `usage` del resultado. Preparar dependencias y configuración según reglas Git. Las identidades declaradas no son autenticadas por el helper; Coordinator mantiene el mapeo real. Si no puede acreditar review independiente obligatoria, informar partial.

[Documentación oficial](https://code.claude.com/docs/en/sub-agents).
