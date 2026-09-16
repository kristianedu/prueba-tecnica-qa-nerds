# Ejercicios 2 y 3 — API y Chatbot Web

Suite compartida de Playwright + TypeScript. Dos `projects` en un solo
`playwright.config.ts`: `api` (Ejercicio 2) y `ui` (Ejercicio 3), para compartir
configuración, reportes y pipeline entre ambos ejercicios.

## Instalación

```bash
npm install
npx playwright install chromium
```

## Ejecución

```bash
npm run test:api     # Ejercicio 2 — pruebas de API
npm run test:ui      # Ejercicio 3 — pruebas del chatbot
npm test             # ambos
npm run report       # abre el reporte HTML
```

Los reportes se escriben en `../output/`: `playwright-report/` (HTML) y
`playwright-resultados.json`, que es lo que consume el reporte consolidado del
Ejercicio 5.

---

## Ejercicio 2 — API

22 pruebas sobre la Goal Tracker API. **Resultado: 22/22 en verde (~13 s).**

### El contrato se descubrió, no se supuso

El enunciado no especifica los códigos de creación, la forma de los payloads ni
los mensajes de error. Antes de escribir una sola aserción se exploró la API
real con `curl` y se documentó el contrato en
[`tests/api/contrato.ts`](tests/api/contrato.ts):

| Endpoint | Éxito | Error |
|---|---|---|
| `GET /api/v1/status` | 200 `{status:"OPERATIONAL"}` | — |
| `POST /api/v1/auth/register` | 201 `{user:{name,email}}` | 400 `Email address already exists` / `Please provide a name, email address and password` |
| `POST /api/v1/auth/login` | 200 `{msg,token}` | 401 `Invalid Credentials` / 400 `Please provide an email address and password` |
| `GET /api/v1/goals` | 200 `{goals:[…]}` | 401 `Authentication invalid` |
| `POST /api/v1/goals` | 201 `{goal:{…}}` | 400 `Please add a description,Please add a title` |
| `GET /api/v1/goals/:id` | 200 `{goal:{…}}` | 404 `No goal with id: …` |
| `DELETE /api/v1/goals/:id` | 200 `Success! Goal removed.` | 404 |

Forma de un goal: `_id`, `title`, `description`, `status` (`to-do` \| `in-progress` \| `done`),
`priority` (`low` \| `medium` \| `high`), `createdBy`, `createdAt`. Los valores por
defecto son `to-do` y `low`.

### Decisiones de diseño

**Validación de esquema con Zod, no solo códigos de estado.** Un 201 con un
cuerpo deforme pasaría una prueba que solo mire el status. Cada respuesta se
valida contra su esquema, y el error se aplana a `campo: problema` para que sea
legible en el reporte de CI.

**Usuario único por corrida.** Cada ejecución registra su propio email con sello
de tiempo. Eso permite afirmar la cantidad exacta de goals en el listado sin
riesgo de flakiness, y que la suite se repita indefinidamente sin arrastrar
estado.

**El health check absorbe el arranque en frío.** La API vive en el plan gratuito
de Render, que duerme el contenedor y tarda hasta un minuto en despertarlo. Va
numerado `00` y con timeout de 120 s: sin eso, la primera prueba que tocara la
red fallaría por timeout y el pipeline se vería roto sin estarlo.

**El ciclo de vida va en `serial`.** Crear, consultar, listar y borrar son pasos
encadenados de un mismo recorrido. Partirlos en pruebas independientes obligaría
a recrear el estado en cada una: más lento y prueba menos.

### Qué se cubre más allá del enunciado

- La contraseña no viaja de vuelta en el registro, ni siquiera hasheada.
- El JWT se decodifica para verificar que su payload corresponde a quien inició
  sesión y que trae expiración futura.
- Un email inexistente devuelve el mismo `Invalid Credentials` que una
  contraseña incorrecta: la API no filtra qué correos están registrados.
- Un ID malformado devuelve 404 y **no** 500 — un 500 ahí significaría que un ID
  basura llega sin filtrar hasta la capa de base de datos.
- Borrar dos veces el mismo goal devuelve 404.
- Valores por defecto de `status` y `priority` al omitirlos.

### Estructura

```
tests/api/
  contrato.ts        esquemas Zod, rutas y helper de validación
  fixtures.ts        usuario único por worker y contexto autenticado
  00-health.spec.ts  health check + absorción del arranque en frío
  01-auth.spec.ts    registro y login, positivos y negativos
  02-goals.spec.ts   ciclo de vida, validaciones, 404 y autorización
```

---

## Ejercicio 3 — Chatbot Web

Ver [`tests/ui/README.md`](tests/ui/README.md).
