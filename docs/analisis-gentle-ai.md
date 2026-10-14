# Análisis de gentle-ai para Pol DevFlow

Fecha: 14/10/2026. Fuente: código de [gentle-ai](https://github.com/Gentleman-Programming/gentle-ai) v4.1.1 (licencia MIT), notas de la versión v4.1.0 y la página de desarrolladores de Gentleman Programming. Se toman ideas, no texto ni código.

## Punto de partida: datos reales de DevFlow (14 ejecuciones, 5–9/10/2026)

| Dato | Valor |
|---|---|
| Ejecuciones en full | 13 de 14 |
| Con revisión obligatoria | 13 de 14 |
| Reviewers por ejecución | ~2 de media (máximo 4) |
| Fixers por ejecución | ~1,3 de media (máximo 3) |
| Funciones opcionales usadas (`retro`, `rules`, `profile`, codegraph) | ninguna |
| Consumo de tokens registrado | prácticamente nulo |

El mayor coste observado es el ciclo revisión → corrección → nueva revisión.

## Qué hace gentle-ai y qué adoptamos

### 1. Revisión precisa (adoptado en 1.0.21)
- **Filtro de precisión.** El reviewer solo informa defectos reales y defendibles con evidencia; el estilo está prohibido salvo que oculte un defecto. Principio: un detalle no detectado no cuesta nada; un falso positivo cuesta un ciclo de corrección completo.
- **Presupuesto de pasadas.** Una pasada por lente (dos en zonas críticas); no se revisa "hasta que no quede nada".
- **Refutador.** Antes de corregir, un único verificador independiente intenta desmontar cada bloqueo con evidencia del código: `corroborated`, `refuted` o `inconclusive`. Solo los corroborados pasan al fixer.
- **Umbral de gravedad.** Solo los bloqueos graves corroborados entran en corrección y nueva revisión; avisos y sugerencias se informan una vez y no se revisan de nuevo.
- **Re-revisión acotada.** La segunda revisión recibe la lista congelada de bloqueos y el delta de la corrección; comprueba que están arreglados y que no hay regresión, sin buscar defectos nuevos.
- **Una sola corrección por candidato.** Sin bucle hasta quedar limpio; si una corrección no basta, decide el humano.

### 2. Contexto y compactación (adoptado en 1.0.21)
- **Compactación.** gentle-ai obliga a que el resumen compactado empiece con una instrucción para guardar el resumen en su memoria (Engram) e incluya objetivo, descubrimientos, trabajo hecho, siguientes pasos y archivos tocados. En DevFlow el estado de cada ejecución ya vive fuera del chat (CLI), así que basta con recuperar con `status` tras compactar.
- **Presupuestos numéricos.** Decidir en línea con como mucho 3 llamadas y unos 10.000 tokens; si hacen falta más de unas 5 búsquedas seguidas, un explorador que devuelve como mucho unos 2.000 tokens con `archivo:línea`, y el Coordinator no vuelve a leer lo ya resumido; salidas de comandos acotadas (recuentos, `--stat`, `tail`); aviso orientativo hacia los 150.000 tokens de contexto.

### 3. Normalizar antes de revisar (adoptado en 1.0.21)
Los formateadores y correcciones automáticas se ejecutan antes de congelar el candidato para revisión; si cambian el código después, la revisión deja de valer.

### 4. Ya adoptado antes
- Delegar por un motivo y decidir el nivel por riesgo y comprensión, no por número de archivos (1.0.19).
- Especificación literal del usuario por referencia (1.0.19, `request_ref`).
- Limpieza al retirar funciones y control de deriva de la documentación (1.0.19).
- Revisión proporcional por lentes (1.0.20, `review_plan`).

### 5. Adaptado, no copiado
- **Delegación.** gentle-ai trabaja en línea por defecto y delega solo con motivo. DevFlow delega para usar modelos más baratos que el Coordinator, lo que sí compensa; se adopta no lanzar un worker para lo que el Coordinator resuelve en dos llamadas y no repetir lecturas entre workers (`code_map`).

### 6. No adoptado
- Protocolos muy extensos (por ejemplo, el de informar defectos propios en su GitHub): el tamaño de las instrucciones también es un problema para ellos.
- Engram: se valoró y se descartó por ahora (memoria sin verificación ligada a commits, solapamiento con perfil, reglas y codegraph, datos de clientes).
- Judgment Day (dos jueces y un fixer): demasiado coste para el volumen actual.
- Instalador de su shell, plugins de OpenCode y versionado de su contrato de proveedores. Cuando se use OpenCode, revisar su adaptador.

## Cómo medir el efecto
Comparar con `stats` antes y después de la 1.0.21: revisiones y fixers por ejecución (hoy ~2 y ~1,3) y tiempo por ejecución full.
