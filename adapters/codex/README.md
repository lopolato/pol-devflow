# Adaptador de Codex

Generar perfiles independientes `pol-<rol>.toml` con name, description y developer_instructions. Omitir model/effort hereda la sesión. Instalar en agents únicamente por una petición de instalación/actualización.

La skill usa agents/openai.yaml con policy.allow_implicit_invocation: false para impedir selección implícita. Es la política nativa de Codex; disable-model-invocation pertenece a Claude. `scripts/validate.py --runtime codex` comprueba política y hashes de la instalación registrada.

Coordinator usa herramientas nativas para lanzar, esperar, recoger, dirigir y cancelar workers. Preferir selección de perfil si está disponible. Si solo existe un worker genérico, incluir contrato y rol en su encargo; pasar modelo/esfuerzo solo si la herramienta lo admite. No afirmar que se cargó un perfil si no se pudo seleccionar.

Comprobar capacidades reales. Generar archivos demuestra formato, no carga efectiva ni acceso a modelos. El sandbox de lectura puede verse sustituido por permisos de sesión; mantener límites de scope. Si review independiente es obligatoria y no hay worker independiente, informar partial. No crear chats del usuario para delegación interna.

[Documentación oficial](https://learn.chatgpt.com/docs/agent-configuration/subagents).
