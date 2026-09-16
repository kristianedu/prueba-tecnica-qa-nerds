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
.venv/bin/python -m pytest tests/ -v                     # 74 pruebas del evaluador
.venv/bin/python src/runner.py --todos --proveedor groq  # evaluación real

# Ejercicios 2 y 3
cd ejercicio-2-3-playwright
npm run test:api
npm run test:ui

# Ejercicio 5 — reporte consolidado
cd ..
ejercicio-1-llm-eval/.venv/bin/python ejercicio-5-reporte/consolidar.py \
    --entrada output --salida output
```

Las pruebas del evaluador y los Ejercicios 2 y 3 corren **sin credenciales**.
El Ejercicio 1 evalúa contra un LLM real, así que necesita una clave de Groq
(tier gratuito): https://console.groq.com

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

Y sobre todo: **el evaluador tiene sus propias pruebas.** 65 casos que le plantan
fugas, alucinaciones, olvidos, injections obedecidas, respuestas hostiles y
llamadas a herramientas con argumentos inventados, exigiendo que las detecte —
más respuestas correctas, exigiendo que no invente hallazgos.

Las cinco categorías de detección del bonus (alucinaciones, prompt injection,
respuestas tóxicas, pérdida de contexto y tool calling incorrecto) están
cubiertas y se miden de verdad: el reporte consolidado deduce de los checks que
realmente se ejecutaron si una categoría fue evaluada, y dice "no evaluado" en
vez de cero cuando no lo fue.

### 2 — Automatización de API

22 pruebas sobre la Goal Tracker API, **22/22 en verde**. El contrato completo se
descubrió explorando la API real con `curl` antes de escribir una sola aserción;
el enunciado no lo especifica. Validación de esquema con Zod, usuario único por
corrida y absorción del arranque en frío de Render. Detalle en
[`ejercicio-2-3-playwright/README.md`](ejercicio-2-3-playwright/README.md).

### 3 — Automatización de Chatbot Web

7 pruebas sobre el widget de chat de Botpress Docs, **7/7 en verde**, estables en
5 corridas consecutivas. Tiempo de respuesta medido del bot: **~1.0 s** al primer
token. Detalle en
[`ejercicio-2-3-playwright/tests/ui/README.md`](ejercicio-2-3-playwright/tests/ui/README.md).

> **Hallazgo: el enunciado parte de una premisa que ya no se cumple.**
>
> El enunciado asume que el widget vive en un **iframe cross-origin**, y
> recomienda Playwright sobre Cypress justamente por esa razón. Verificado contra
> el sitio real, hoy **no hay ningún `<iframe>`**: el asistente "Ask Docs" se
> renderiza inline en el documento principal como isla de Astro.
>
> Por eso las pruebas **no** usan `frameLocator()` — sería una indirección que no
> corresponde al DOM real. El Page Object aísla ese detalle, así que si Botpress
> vuelve al iframe basta cambiar una asignación y ningún spec se entera.
>
> La recomendación de Playwright sigue siendo correcta por otros motivos, pero el
> argumento del iframe ya no aplica.

### 4 — CI/CD

[`.github/workflows/qa.yml`](.github/workflows/qa.yml) — corre los tres
ejercicios en cada push y pull request.

Dos decisiones que vale la pena señalar:

- **El reporte se genera aunque algo falle**, gracias al `if: always()` del job
  de consolidación, y se publica en el *Job Summary* de GitHub. Lo que los jobs
  de pruebas **no** llevan es `continue-on-error`: lo tuvieron, y con esa
  bandera un job en rojo no tumbaba la ejecución, así que el pipeline se
  reportaba en verde con el Ejercicio 1 fallando.
- **El job del LLM corre primero las 74 pruebas del evaluador**, sin gastar una
  sola llamada. Si el motor está roto, se corta ahí: no tiene sentido pagar 71
  llamadas al modelo para que las evalúe un evaluador que no funciona.

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

**El evaluador se prueba a sí mismo sin gastar llamadas.** Las 74 pruebas plantan
fallas —fugas, alucinaciones, olvidos, injections obedecidas, hostilidad,
argumentos de herramienta inventados— y exigen que las detecte, además de exigir
que **no** invente hallazgos ante respuestas correctas. Corren sin credenciales y
sin red, y van antes de la evaluación en el pipeline: si el motor está roto, no
tiene sentido gastar 71 llamadas al modelo.

**Artefactos separados por proyecto.** Los dos projects de Playwright escriben
`playwright-report-{api,ui}/` y `playwright-{api,ui}.json`. En CI corren en jobs
distintos y sus artefactos se fusionan en un mismo directorio: con nombres
compartidos, uno sobrescribiría al otro.

**El pipeline evalúa contra el LLM real en cada push**, así que necesita el
secret `GROQ_API_KEY`.

**Rojo significa "el arnés falló", no "el modelo tiene defectos".** El pipeline
se pone en rojo si las pruebas de API o de interfaz fallan, si el runner se cae,
o si faltan resultados de algún ejercicio. Los escenarios en FAIL del Ejercicio 1
—el modelo inventando capacidades que no existen en su base de conocimiento— son
el *resultado* de la evaluación, no un error de la suite: se publican en el
reporte consolidado y en el resumen del job, con el pipeline en verde.
Confundir ambas cosas haría que un modelo defectuoso pareciera un pipeline roto.

**Honestidad en el reporte.** El consolidado deduce de los checks realmente
ejecutados si una categoría fue evaluada, y dice "no evaluado" en vez de cero
cuando no lo fue. Un cero significa "se buscó y no había"; decirlo sin haber
medido es mentir con estadística.

## Variables de entorno

Ver [`.env.example`](.env.example). Solo `ANTHROPIC_API_KEY` (o la del proveedor
que elijas) es necesaria, y únicamente para la corrida real del Ejercicio 1.
