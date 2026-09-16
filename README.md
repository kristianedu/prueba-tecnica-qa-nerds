# Prueba Técnica — QA Engineer: AI Agents, LLMs

[![QA — Prueba Técnica](https://github.com/kristianedu/prueba-tecnica-qa-nerds/actions/workflows/qa.yml/badge.svg)](https://github.com/kristianedu/prueba-tecnica-qa-nerds/actions/workflows/qa.yml)

Los cinco ejercicios de la prueba, cada uno en su carpeta, más un pipeline de
CI/CD que los ejecuta en cada cambio y un reporte consolidado.

| Ejercicio | Qué hace | Stack |
|---|---|---|
| [1 — Evaluación de agentes LLM](ejercicio-1-llm-eval/README.md) | Conversaciones simuladas de varios turnos, evaluadas automáticamente en coherencia, contexto, alucinación y seguridad | Python |
| [2 — API](ejercicio-2-3-playwright/README.md) | Pruebas funcionales de la Goal Tracker API | Playwright + TypeScript |
| [3 — Chatbot web](ejercicio-2-3-playwright/tests/ui/README.md) | Pruebas de interfaz del asistente de chat de Botpress Docs | Playwright + TypeScript |
| [4 — CI/CD](ejercicio-4-cicd/README.md) | Pipeline que corre los tres anteriores en cada push | GitHub Actions |
| [5 — Consolidación](ejercicio-5-reporte/consolidar.py) | Métricas globales y detección transversal de fallas | Python |

Cada carpeta tiene su propio README con el detalle: decisiones de diseño,
cobertura, selectores, hallazgos y limitaciones.

## Evidencia de ejecución

**No hace falta instalar nada para comprobar que todo funciona.** Cada push
ejecuta los tres ejercicios contra los sistemas reales —la Goal Tracker API, el
chatbot de Botpress y un LLM en Groq— y publica los resultados:

| Dónde | Qué se ve |
|---|---|
| [Historial de ejecuciones](https://github.com/kristianedu/prueba-tecnica-qa-nerds/actions/workflows/qa.yml) | Todas las corridas, con su resultado |
| Resumen de cada ejecución | El **reporte consolidado completo**, renderizado en la propia página |
| Registro de cada job | La salida del runner, caso por caso |
| Artefactos de cada ejecución | Reportes HTML de Playwright y los JSON de resultados (90 días) |

Los mismos artefactos están además commiteados en [`output/`](output/), así que
siguen disponibles aunque expiren los de Actions. Los reportes HTML de Playwright
son archivos autocontenidos: GitHub los muestra como código fuente, pero al
descargarlos abren directamente en el navegador.

## Estructura

```
ejercicio-1-llm-eval/        Evaluación conversacional de agentes LLM   (Python)
ejercicio-2-3-playwright/    API y Chatbot web                          (TypeScript)
ejercicio-4-cicd/            CI/CD — apunta al workflow, que por exigencia
                             de GitHub Actions vive en .github/workflows/
ejercicio-5-reporte/         Consolidación y métricas globales          (Python)
.github/workflows/qa.yml     Pipeline de CI/CD (Ejercicio 4)
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
.venv/bin/python -m pytest tests/ -v                     # pruebas del propio evaluador
.venv/bin/python src/runner.py --ver 4                   # leer una conversación ya evaluada
.venv/bin/python src/runner.py --todos --proveedor groq  # evaluación real

# Ejercicios 2 y 3
cd ../ejercicio-2-3-playwright
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

## Criterios transversales

Las decisiones concretas están documentadas en el README de cada ejercicio.
Estos son los criterios que las ordenan:

- **Medir, no opinar.** Todo lo que puede escribirse como aserción se resuelve en
  código. Al juicio de un LLM solo llega lo que de verdad necesita criterio, y
  aun ahí se le exige citar evidencia verificable.
- **Reproducibilidad.** Las corridas del Ejercicio 1 se cachean en disco, así que
  una segunda corrida idéntica da el mismo resultado y no cuesta nada.
- **El evaluador se prueba a sí mismo**, sin credenciales ni red, y antes de la
  evaluación real: si el motor está roto, no tiene sentido gastar llamadas al
  modelo.
- **Rojo significa "el arnés falló", no "el modelo tiene defectos".** Un escenario
  en FAIL es el *resultado* de la evaluación, y se publica con el pipeline en
  verde.
- **Honestidad en el reporte.** Una categoría que no se midió se reporta como
  "no evaluado", nunca como cero.


