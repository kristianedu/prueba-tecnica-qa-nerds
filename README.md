# Prueba Técnica — QA Engineer: AI Agents, LLMs

Los cinco ejercicios de la prueba, cada uno en su carpeta, más un pipeline de
CI/CD que los ejecuta en cada cambio y un reporte consolidado.

```
ejercicio-1-llm-eval/        Evaluación conversacional de agentes LLM   (Python)
ejercicio-2-3-playwright/    API y Chatbot web                          (TypeScript)
ejercicio-5-reporte/         Consolidación y métricas globales          (Python)
.github/workflows/qa.yml     Pipeline de CI/CD
output/                      Resultados generados
```

## Puesta en marcha

```bash
cp .env.example .env          # opcional: solo hace falta para la corrida real del Ejercicio 1

# Ejercicio 1
cd ejercicio-1-llm-eval
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Ejercicios 2 y 3
cd ../ejercicio-2-3-playwright
npm install && npx playwright install chromium
```

## Ejecución

```bash
# Ejercicio 1 — evaluación conversacional
cd ejercicio-1-llm-eval
.venv/bin/python -m pytest tests/ -v                       # pruebas del evaluador
.venv/bin/python src/runner.py --todos --proveedor mock \
    --fixture fixtures/asistente-sano.yaml                 # sin credenciales
.venv/bin/python src/runner.py --todos --proveedor anthropic   # corrida real

# Ejercicios 2 y 3
cd ejercicio-2-3-playwright
npm run test:api
npm run test:ui

# Ejercicio 5 — reporte consolidado
cd ..
ejercicio-1-llm-eval/.venv/bin/python ejercicio-5-reporte/consolidar.py \
    --entrada output --salida output
```

Todo salvo la corrida real del Ejercicio 1 funciona **sin credenciales**.

---

## Los cinco ejercicios

### 1 — Evaluación Conversacional de Agentes LLM

Conversaciones de 6 turnos entre un usuario simulado y un asistente LLM, sobre 5
escenarios, evaluadas automáticamente. Detalle completo en
[`ejercicio-1-llm-eval/README.md`](ejercicio-1-llm-eval/README.md).

Tres decisiones sostienen la validez de la medición:

- **Universo cerrado.** El asistente recibe una base de conocimiento de 10 hechos
  sobre una empresa ficticia. Cualquier afirmación fuera de ella es alucinación
  *por construcción*, no por opinión de un juez. Eso hace medible
  `hallucination_rate`.
- **Canario en el system prompt.** Un token único que no existe en ningún otro
  lugar. Si aparece en una respuesta, hubo fuga: binario, sin interpretación.
- **Evaluador híbrido.** Todo lo que puede escribirse como aserción se resuelve
  en código, gratis y reproducible. Al juez LLM solo llega lo que de verdad
  necesita criterio, con rúbrica anclada y la obligación de citar evidencia
  —que el código verifica—.

Y sobre todo: **el evaluador tiene sus propias pruebas.** 22 casos que le plantan
fugas, alucinaciones, olvidos e injections obedecidas y exigen que las detecte,
más respuestas correctas exigiendo que no invente hallazgos.

### 2 — Automatización de API

22 pruebas sobre la Goal Tracker API, **22/22 en verde**. El contrato completo se
descubrió explorando la API real con `curl` antes de escribir una sola aserción;
el enunciado no lo especifica. Validación de esquema con Zod, usuario único por
corrida y absorción del arranque en frío de Render. Detalle en
[`ejercicio-2-3-playwright/README.md`](ejercicio-2-3-playwright/README.md).

### 3 — Automatización de Chatbot Web

Pruebas de interfaz sobre el widget de chat de Botpress Docs, que vive en un
iframe cross-origin. Detalle en
[`ejercicio-2-3-playwright/tests/ui/README.md`](ejercicio-2-3-playwright/tests/ui/README.md).

### 4 — CI/CD

[`.github/workflows/qa.yml`](.github/workflows/qa.yml) — corre los tres
ejercicios en cada push y pull request.

Dos decisiones que vale la pena señalar:

- **Los jobs de pruebas llevan `continue-on-error`.** Sin eso, el primer fallo
  aborta el pipeline y el reporte consolidado nunca se genera, justo cuando más
  se necesita. Aquí siempre se produce, y un job final decide si el pipeline
  pasa. El reporte se publica en el *Job Summary* de GitHub.
- **El job del LLM corre primero las pruebas del evaluador**, y después una
  contraprueba: con el fixture defectuoso los 5 escenarios *tienen* que fallar.
  Si pasan, el evaluador dejó de detectar y el pipeline se entera.

El orden de los jobs es Web → API → LLM porque así lo pide el enunciado.
Técnicamente convendría el inverso —la API es la más rápida y barata, y fallar
ahí primero ahorra minutos de runner—, pero en una prueba técnica se sigue la
especificación y se documenta la observación.

### 5 — Consolidación

[`ejercicio-5-reporte/consolidar.py`](ejercicio-5-reporte/consolidar.py) produce
`output/reporte-consolidado.{json,md,html}` con métricas globales y la detección
automática transversal de las cinco categorías del enunciado.

Es tolerante a entradas ausentes a propósito: si un job falló, el consolidado se
genera igual y dice qué falta. Y las categorías sin ningún check que las
alimente se reportan como **no evaluadas**, no como cero — un cero significa "se
buscó y no había", y decir cero cuando no se midió nada es mentir con
estadística.

---

## Decisiones técnicas transversales

**Reproducibilidad.** El Ejercicio 1 cachea en disco cada respuesta del modelo,
indexada por el hash de la petición completa: una segunda corrida es idéntica a
la primera y no cuesta nada. Esto importa más de lo que parece, porque Claude 4.6
en adelante **eliminó el parámetro `temperature`** y devuelve HTTP 400 si se
envía. En esos modelos la reproducibilidad no puede venir del muestreo, así que
viene de la caché.

**Todo corre sin credenciales.** El Ejercicio 1 trae un proveedor `mock` con
conversaciones pregrabadas, en dos variantes: un asistente sano (que debe dar
5/5 PASS) y uno defectuoso (que debe dar 5/5 FAIL). Eso permite que el pipeline
corra en cualquier fork sin secrets, y es además la demostración de que el motor
discrimina: detecta las fallas **sin inventarlas**.

**Honestidad en el reporte.** Una corrida en modo mock se marca a sí misma con
`coherence_score: null` y `evaluacion_parcial: true`. Nadie debería poder
confundirla con una evaluación real.

## Variables de entorno

Ver [`.env.example`](.env.example). Solo `ANTHROPIC_API_KEY` (o la del proveedor
que elijas) es necesaria, y únicamente para la corrida real del Ejercicio 1.
