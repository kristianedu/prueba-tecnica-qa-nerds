# Ejercicio 3 — Pruebas de interfaz del chatbot web

Automatización del asistente de chat embebido en el sitio de documentación de
Botpress (`https://botpress.com/docs`), con Playwright + TypeScript.


## Evidencia de ejecución

El enunciado pide *"screenshots o video, y/o reporte del test runner"*. Se
entregan las tres cosas:

| Artefacto | Dónde |
|---|---|
| Capturas de pantalla | `output/ejercicio-3/capturas/*.png` |
| Reporte HTML del runner | `output/playwright-report-ui/index.html` |
| Reporte JSON | `output/playwright-ui.json` |
| Métricas de tiempo de respuesta | `output/ejercicio-3/metricas-chatbot.json` |

Las capturas se toman **en las corridas que pasan**, no solo cuando algo falla.
Playwright por defecto solo guarda imágenes ante un fallo —correcto para
depurar—, pero eso deja la entrega de un ejercicio de interfaz sin una sola
imagen cuando todo va bien. Un JSON con nombres de casos no demuestra que el
chatbot respondiera; una captura de la conversación sí.

Se capturan cuatro momentos:

| Archivo | Qué prueba |
|---|---|
| `01-sitio-cargado.png` | El sitio de documentación renderizó su contenido |
| `02-panel-cerrado.png` | El botón de cerrar colapsa el panel y deja el disparador accesible |
| `02-panel-reabierto.png` | El panel se restaura con su compositor operativo |
| `03-conversacion-con-respuesta.png` | "Hola" en el historial y la respuesta del bot en pantalla |

Cada captura queda además adjunta al reporte HTML, junto al caso que la generó.

## Cómo ejecutarlas

Desde `ejercicio-2-3-playwright/`:

```bash
npm install
npx playwright install chromium   # solo la primera vez
npm run test:ui                   # PW_TAG=ui playwright test --project=ui
```

> Usa `npm run test:ui` y no `npx playwright test --project=ui` a secas: el
> script exporta `PW_TAG=ui`, que es lo que separa los reportes de este
> ejercicio de los del Ejercicio 2 en `output/`.

Para ver el reporte HTML con capturas, vídeo y traza de los fallos:

```bash
npm run report:ui
```

La URL bajo prueba se toma de `CHATBOT_URL` (ver `.env.example` en la raíz del
repo); si no está definida, el `playwright.config.ts` usa
`https://botpress.com/docs`.

### Artefactos que genera

| Ruta | Contenido |
| --- | --- |
| `output/ejercicio-3/metricas-chatbot.json` | Tiempos de respuesta del bot (lo consume el Ejercicio 5) |
| `output/playwright-report-ui/` | Reporte HTML con capturas, vídeo y trazas |
| `output/playwright-ui.json` | Resultados en JSON del runner |

Capturas, vídeo y traza se guardan **solo cuando un test falla**, según la
configuración compartida de la suite.

## Hallazgo principal: aquí no hay iframe

El enunciado da por hecho que el widget vive en un **iframe cross-origin** y
recomienda Playwright por eso mismo. Se verificó contra el sitio real y **hoy no
es así**:

- `https://botpress.com/docs` no monta ningún `<iframe>` del chat. El asistente
  ("Ask Docs") se renderiza **inline en el documento principal**, como una isla
  de Astro (`<astro-island>`) dentro de `div.ai-panel-container`.
- `https://botpress.com` (la portada comercial) tampoco expone el webchat
  clásico en el DOM inicial; los únicos `<iframe>` presentes son píxeles de
  analítica de terceros. Sí hay un botón flotante de chat que probablemente monte
  su widget bajo demanda, pero **no es el sitio que pide el enunciado** ni el que
  apunta `CHATBOT_URL`.

Por eso estas pruebas **no usan `frameLocator()`**: introducirlo sería añadir una
indirección que no corresponde al DOM real. La clase `WidgetChat` está diseñada
para absorber el cambio si Botpress vuelve al iframe — ver "Si el widget cambia".

Segunda consecuencia práctica: al no haber frontera de iframe, el ámbito del
widget hay que acotarlo a mano, porque los localizadores por rol chocarían con el
contenido de la página de documentación (que también tiene párrafos, botones y
encabezados).

## Qué cubre cada spec

### `01-acceso.spec.ts` — Acceso al sitio
- El sitio responde **HTTP 200** y entrega `text/html`.
- La página realmente pinta: `<title>`, el `h1` "Botpress documentation", el
  botón de búsqueda de la cabecera y los enlaces de navegación de la portada.

Se separan a propósito la capa de red y la de render: un 200 con la página en
blanco sigue siendo un fallo.

### `02-widget.spec.ts` — Existencia e interacción con el widget
- El widget está montado: disparador "Ask Docs" visible, contenedor del panel
  adjunto al DOM, compositor y botón de envío presentes.
- **Cerrar y reabrir**: se colapsa con "Close panel" y se restaura con
  "Ask Docs". Se comprueba que al cerrar el disparador sigue visible (si no, el
  widget quedaría inaccesible).
- **Nombre del bot**: se leen y validan las tres señales de identidad que el
  widget muestra (ver limitaciones).

### `03-conversacion.spec.ts` — Conversación
- Se envía **"Hola"**, se verifica que aparece en el historial **con su texto
  literal** y que el compositor queda vacío.
- Se verifica que llega respuesta del bot, que tiene contenido real (>10
  caracteres) y que no es un eco del saludo.
- Se mide el **tiempo de respuesta** y se registra en
  `output/ejercicio-3/metricas-chatbot.json`.
- Segundo caso: el historial **sobrevive a cerrar y reabrir** el panel (fallo
  clásico cuando un widget desmonta su estado al ocultarse). Aporta además una
  segunda muestra de latencia al informe.

## Selectores descubiertos

Todo se localiza por **rol, texto o placeholder**. Ninguna clase autogenerada.

| Elemento | Localizador | Notas |
| --- | --- | --- |
| Ámbito del panel | `.ai-panel-container` | **Única excepción CSS** — ver abajo |
| Abrir / disparador | `getByRole('button', { name: 'Ask Docs' })` | En la barra superior del sitio |
| Cerrar panel | `getByRole('button', { name: 'Close panel' })` | `aria-label` en la cabecera del panel |
| Campo de mensaje | `getByPlaceholder('Ask a question...')` | Es un `<textarea>` |
| Enviar | `getByRole('button', { name: 'Send' })` | `type="submit"` del formulario |
| Título de conversación | `getByText('New chat', { exact: true })` | Cabecera del panel |
| Identidad del bot | `getByText("You're chatting with an AI agent")` | Descargo al pie |
| Mensaje del usuario | `getByText('<texto>', { exact: true })` | Se renderiza como `<div>` |
| Respuesta del bot | `getByRole('paragraph')` sin el texto del descargo | Markdown → `<p>` |

Otros controles detectados y no usados por las pruebas: `Expand panel`,
`New conversation`, `Conversation history`, `Close assistant`.

### Por qué hay una clase CSS

`.ai-panel-container` es el **único** gancho por clase de toda la suite. No es
una clase autogenerada por un bundler (tipo `css-1x2y3z`), sino un nombre
semántico escrito a mano que delimita la isla del asistente. Hace falta porque el
panel **no expone ningún landmark ARIA ni `role` propio** con el que anclarlo, y
sin acotar el ámbito los localizadores por rol colisionarían con la página de
documentación. Todo lo demás cuelga de ahí por rol, texto o placeholder.

### Cómo se distingue quién habla

El widget no marca los mensajes con `role` ni `data-*`, pero sí usa semántica
HTML: la respuesta del asistente se renderiza como Markdown (uno o más `<p>`)
mientras que el mensaje del usuario es un `<div>`. Dentro del panel el único
`<p>` ajeno a una respuesta es el descargo del pie, que se excluye por texto.

## Cómo se mide el tiempo de respuesta

Se registran dos cifras por interacción:

- **`tiempo_respuesta_ms`** (principal): del clic en Enviar a la primera burbuja
  del bot con texto visible — *time to first token*. Es la métrica que importa
  porque no depende de lo larga que sea la respuesta.
- **`tiempo_respuesta_completa_ms`** (informativa): hasta que el streaming deja
  de crecer. El fin del streaming se detecta por **condición** (dos lecturas
  consecutivas del texto idénticas), no con una espera fija.

Ninguna prueba usa `waitForTimeout`. Todas las esperas son por condición
(`toBeVisible`, `toHaveText`, `toHaveCount`, `expect.poll`).

Valores medidos en cuatro corridas consecutivas: **1.0 – 1.6 s** al primer token,
**~2.5 s** a respuesta completa. El timeout para la respuesta del bot es de
**60 s** (`TIMEOUT_RESPUESTA_BOT_MS`), holgado a propósito porque detrás hay un
LLM externo.

## Si el widget cambia

1. **Vuelve a un iframe** → es el caso previsto. En `widget-chat.ts`, cambiar
   solo la asignación de `this.raiz` por
   `page.frameLocator('iframe[title="..."]').locator('body')`. Los specs no se
   enteran: todos operan contra la API pública de `WidgetChat`.
2. **Cambia `.ai-panel-container`** → actualizar la constante `SELECTOR_PANEL`,
   arriba del archivo. Es el único punto de la suite atado a una clase.
3. **Cambian los textos de los botones** (`Ask Docs`, `Close panel`, `Send`) →
   actualizar los localizadores del constructor de `WidgetChat`. Ojo: el sitio
   está en inglés aunque las pruebas estén en español; los nombres accesibles son
   los literales del sitio.
4. **El panel deja de venir abierto por defecto** → `ir()` asume que en viewport
   de escritorio (≥ `lg`, 1024 px) el panel ya está desplegado. Si eso cambia,
   añadir un `abrir()` condicional en `ir()`. Por debajo de `lg` el panel está
   oculto (`hidden lg:flex`), así que reducir el viewport rompería la suite.
5. **Para redescubrir selectores**, lo más rápido es:
   `npx playwright codegen https://botpress.com/docs`.

## Limitaciones conocidas

- **No hay un "nombre de bot" propiamente dicho.** El asistente no se presenta
  con un nombre tipo "Sarah". Se validan las tres señales de identidad que el
  usuario sí ve: el nombre del widget ("Ask Docs"), el título de la conversación
  ("New chat") y el descargo del pie ("You're chatting with an AI agent."). Se
  documenta aquí en vez de inventar una aserción sobre un nombre inexistente.
- **El bot es un servicio externo.** Responde según su propio criterio; las
  aserciones validan que *llega una respuesta con contenido*, nunca un texto
  concreto. A "Hola" contesta hoy con un mensaje de encuadre ("I'm here
  specifically for Botpress documentation questions..."), pero eso puede cambiar
  sin previo aviso y las pruebas no dependen de ello.
- **Sin aislamiento de sesión entre tests.** Cada test arranca con contexto nuevo
  de Playwright, así que el historial empieza vacío; `03-conversacion` lo
  verifica explícitamente con `toHaveCount(0)` antes de enviar nada. Sin esa
  comprobación, un historial heredado haría pasar la aserción de "llegó
  respuesta" sin que el bot contestara.
- **Solo Chromium / escritorio.** El project `ui` corre con `Desktop Chrome`. No
  se cubre el comportamiento móvil del panel, que es distinto (aparece como
  overlay y usa el botón `Close assistant` en lugar de `Close panel`).
