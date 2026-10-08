# Adaptador de Codex

Generar perfiles independientes `pol-<rol>.toml` con name, description y developer_instructions. Omitir model/effort hereda la sesión. Instalar en agents únicamente por una petición de instalación/actualización.

La skill usa agents/openai.yaml con policy.allow_implicit_invocation: false para impedir selección implícita. Es la política nativa de Codex; disable-model-invocation pertenece a Claude. `scripts/validate.py --runtime codex` comprueba política y hashes de la instalación registrada.

En una sesión Codex, preferir su API nativa comprobada (`spawn_agent` y herramientas de seguimiento de esa sesión) para lanzar, esperar, recoger, dirigir y cancelar workers, incluso dentro de un workspace Orca. Preferir selección de perfil si está disponible. Si solo existe un worker genérico, incluir contrato y rol en su encargo; pasar modelo/esfuerzo desde run.config_snapshot solo si la herramienta lo admite y puede respetarlo. No inventar un modelo equivalente ni trasladar nombres de modelos Claude a Codex. Ante una selección explícita incompatible, comunicar la limitación sin sustituirla. No afirmar que se cargó un perfil si no se pudo seleccionar.

Comprobar capacidades reales. No lanzar subprocessos Claude/Codex en segundo plano ni pegar encargos en TUIs como sustituto de la API native. Una petición explícita de workers Orca usa su adaptador; sin API nativa, comprobar Orca o informar bloqueo. Disponibilidad de Codex no demuestra delegación nativa Claude, y viceversa. Generar archivos demuestra formato, no carga efectiva ni acceso a modelos. El sandbox de lectura puede verse sustituido por permisos de sesión; mantener límites de scope. Si review independiente es obligatoria y no hay worker independiente, informar partial. No crear chats del usuario para delegación interna. Incluir `usage` solo si la herramienta reporta tokens/tiempo; si no, omitirlo.

[Documentación oficial](https://learn.chatgpt.com/docs/agent-configuration/subagents).
