# Subdelegación nativa optativa

Solo un run full con executor `native` puede habilitar un nivel adicional. Lite, Orca y los runs sin grant mantienen el flujo plano. La subdelegación es una capacidad concedida por encargo y el texto de un worker nunca puede concedérsela a sí mismo.

El Coordinator habilita un padre `architect`, `reviewer` o `tester` con `--can-delegate`, un `--native-nesting-evidence` concreto obtenido en la sesión actual y `--native-max-workers` entre 2 y 4. El padre tiene `write_scope` vacío y `read_scope` explícito. El Coordinator comprueba la herramienta nativa, registra el hijo antes de lanzarlo y verifica la relación real de sesiones.

Cada padre puede reservar dos encargos hijos como máximo. Un hijo es solo lectura (`explorer`, `debugger` o `tester`), tiene `read_scope` explícito contenido en el del padre, y comparte workspace y revisión. El máximo de trabajadores reservados en todo el run incluye a los padres y es el límite fijado durante el primer grant. Una sustitución conserva el padre, la profundidad, la plaza lógica y el límite del run. No hay un tercer nivel.

El padre no escribe el estado compartido: el Coordinator registra cada hijo antes de lanzarlo o de lanzar al padre que lo usará. Si el padre recibe directamente la respuesta del hijo (Claude Code), la devuelve junto a su resultado; si no, el Coordinator se la entrega. En ambos casos el Coordinator registra el estado del hijo. El padre consolida sus resultados en `subdelegation_trace`; el helper comprueba que los IDs correspondan a hijos registrados. El padre solo puede terminar después de que todos sus hijos hayan terminado y el Coordinator haya observado la actividad nativa correspondiente. Un resultado `done` del helper representa el encargo registrado, no autentica el runtime.

Los helpers no prueban que Codex/Claude haya cargado un perfil ni que la herramienta Agent/subagent exista en vivo. El Coordinator debe hacer ese preflight en cada run; el texto aportado queda como evidencia declarada. La review independiente sigue exigiendo un reviewer distinto de autores y Coordinator, y un hijo que haya contribuido al candidato no puede acreditar esa review.
