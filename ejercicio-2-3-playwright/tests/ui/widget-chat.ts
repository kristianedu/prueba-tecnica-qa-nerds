/**
 * Page Object del widget de chat de la documentación de Botpress.
 *
 * HALLAZGO IMPORTANTE (ver README.md de este directorio): el enunciado asume un
 * webchat clásico embebido en un iframe cross-origin. A día de hoy
 * botpress.com/docs ya NO monta ese iframe: el asistente ("Ask Docs") se
 * renderiza inline en el documento principal como una isla de Astro. Por eso
 * aquí no hay `frameLocator()`. La API pública de esta clase se diseñó para que,
 * si Botpress vuelve a un iframe, baste con cambiar `raiz` por
 * `page.frameLocator(...)` y ningún spec se entere.
 */
import { expect, type Locator, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Único gancho por clase CSS de toda la suite. No es una clase autogenerada por
 * un bundler (tipo `css-1x2y3z`), sino un nombre semántico escrito a mano por
 * Botpress que delimita la isla del asistente. Lo necesitamos porque el panel no
 * expone ningún landmark ARIA ni `role` propio con el que anclarlo, y sin acotar
 * el ámbito los localizadores por rol colisionarían con el contenido de la
 * página de documentación (que también tiene párrafos, botones y encabezados).
 * Todo lo demás cuelga de aquí por rol, texto o placeholder.
 */
const SELECTOR_PANEL = '.ai-panel-container';

/** Texto del descargo legal que el widget fija al pie, fuera del hilo de mensajes. */
const DESCARGO_IA = "You're chatting with an AI agent";

/** El bot es un servicio externo con LLM detrás: generoso a propósito. */
export const TIMEOUT_RESPUESTA_BOT_MS = 60_000;

export class WidgetChat {
  readonly page: Page;

  /** Ámbito del widget. Sustituir por un `frameLocator()` si vuelve al iframe. */
  readonly raiz: Locator;

  /** Botón de la barra superior que abre/reabre el panel del asistente. */
  readonly botonAbrir: Locator;

  /** Botón de la cabecera del panel que lo colapsa. */
  readonly botonCerrar: Locator;

  /** Caja de redacción del mensaje. */
  readonly campoMensaje: Locator;

  /** Botón de envío (es el submit del formulario del compositor). */
  readonly botonEnviar: Locator;

  /** Título de la conversación en la cabecera del panel. */
  readonly tituloConversacion: Locator;

  /** Descargo de identidad del bot, al pie del panel. */
  readonly identidadBot: Locator;

  constructor(page: Page) {
    this.page = page;
    this.raiz = page.locator(SELECTOR_PANEL);

    this.botonAbrir = page.getByRole('button', { name: 'Ask Docs' });
    this.botonCerrar = this.raiz.getByRole('button', { name: 'Close panel' });
    this.campoMensaje = this.raiz.getByPlaceholder('Ask a question...');
    this.botonEnviar = this.raiz.getByRole('button', { name: 'Send' });
    this.tituloConversacion = this.raiz.getByText('New chat', { exact: true });
    this.identidadBot = this.raiz.getByText(DESCARGO_IA);
  }

  /**
   * Burbujas de respuesta del bot.
   *
   * El widget no marca los mensajes con `role` ni `data-*`, pero sí usa
   * semántica HTML: la respuesta del asistente se renderiza como Markdown, o sea
   * uno o más `<p>`, mientras que el mensaje del usuario es un `<div>`. Dentro
   * del panel el único `<p>` que no pertenece a una respuesta es el descargo
   * legal del pie, así que lo excluimos por texto.
   */
  get respuestasBot(): Locator {
    return this.raiz.getByRole('paragraph').filter({ hasNotText: DESCARGO_IA });
  }

  /** Localiza el mensaje del usuario en el historial por su texto exacto. */
  mensajeUsuario(texto: string): Locator {
    return this.raiz.getByText(texto, { exact: true });
  }

  /**
   * Navega al sitio y espera a que el widget esté operativo.
   *
   * En viewport de escritorio (>= lg de Tailwind) el panel viene abierto por
   * defecto, así que no hay que pulsar nada. La condición de "listo" es que el
   * compositor acepte escritura, no un tiempo fijo.
   *
   * Se navega a '' y no a '/': el baseURL incluye la ruta (.../docs) y un '/'
   * la descartaría, aterrizando en la portada comercial de botpress.com, que no
   * monta este widget.
   */
  async ir(): Promise<void> {
    await this.page.goto('', { waitUntil: 'domcontentloaded' });
    await expect(this.campoMensaje).toBeVisible({ timeout: 45_000 });
  }

  async cerrar(): Promise<void> {
    await this.botonCerrar.click();
    await expect(this.campoMensaje).toBeHidden();
  }

  async abrir(): Promise<void> {
    await this.botonAbrir.click();
    await expect(this.campoMensaje).toBeVisible();
  }

  /** `true` si el panel está desplegado y listo para recibir texto. */
  async estaAbierto(): Promise<boolean> {
    return this.campoMensaje.isVisible();
  }

  /**
   * Envía un mensaje y cronometra hasta que aparece la primera respuesta.
   *
   * El cronómetro arranca en el clic de enviar y para cuando la primera burbuja
   * del bot ya tiene texto legible. Medimos *time to first token visible*, no la
   * respuesta completa: el widget escribe en streaming y esperar al último token
   * mediría la longitud de la respuesta, no la latencia del servicio.
   */
  async enviarYCronometrar(mensaje: string): Promise<ResultadoInteraccion> {
    await this.campoMensaje.fill(mensaje);

    const inicio = Date.now();
    const timestampUtc = new Date().toISOString();
    await this.botonEnviar.click();

    // El mensaje propio debe entrar al historial antes de esperar nada del bot:
    // si esto falla, el problema es el envío, no la latencia del servicio.
    await expect(this.mensajeUsuario(mensaje)).toBeVisible({ timeout: 15_000 });

    let respuestaRecibida = true;
    let extracto = '';
    let tiempoRespuestaCompletaMs: number | null = null;
    let tiempoPrimerToken = 0;

    try {
      const primera = this.respuestasBot.first();
      // Dos condiciones: que exista la burbuja y que traiga contenido real.
      // Con el streaming, el `<p>` puede montarse vacío por unos milisegundos.
      await expect(primera).toHaveText(/\S{5,}/, { timeout: TIMEOUT_RESPUESTA_BOT_MS });
      tiempoPrimerToken = Date.now() - inicio;

      // El texto capturado justo en el primer token estaría cortado a media
      // palabra. Dejamos que el streaming termine antes de guardar el extracto,
      // sin tocar la latencia ya medida.
      await this.esperarFinDeStreaming(primera);
      tiempoRespuestaCompletaMs = Date.now() - inicio;
      extracto = ((await this.respuestasBot.allTextContents()).join(' ')).trim();
    } catch {
      respuestaRecibida = false;
      tiempoPrimerToken = Date.now() - inicio;
    }

    return {
      mensaje,
      respuestaRecibida,
      tiempoRespuestaMs: tiempoPrimerToken,
      tiempoRespuestaCompletaMs,
      timestampUtc,
      extracto,
    };
  }

  /**
   * Espera a que la respuesta deje de crecer.
   *
   * No hay indicador fiable de "terminó de escribir" en el DOM, así que la
   * condición es el propio contenido: dos lecturas consecutivas idénticas
   * separadas por el intervalo de sondeo significan que el stream se detuvo.
   * Es una espera por condición, no un `waitForTimeout` fijo.
   */
  private async esperarFinDeStreaming(burbuja: Locator): Promise<void> {
    let anterior: string | null = null;
    await expect
      .poll(
        async () => {
          const actual = (await burbuja.textContent()) ?? '';
          const estable = actual.length > 0 && actual === anterior;
          anterior = actual;
          return estable;
        },
        { timeout: 30_000, intervals: [700] },
      )
      .toBe(true);
  }
}

export interface ResultadoInteraccion {
  mensaje: string;
  respuestaRecibida: boolean;
  /** Latencia hasta el primer texto visible del bot (time to first token). */
  tiempoRespuestaMs: number;
  /** Latencia hasta que el streaming se detiene. `null` si no hubo respuesta. */
  tiempoRespuestaCompletaMs: number | null;
  timestampUtc: string;
  extracto: string;
}

// --------------------------------------------------------------------------
// Registro de métricas
// --------------------------------------------------------------------------

const RUTA_METRICAS = path.resolve(
  __dirname, '..', '..', '..', 'output', 'ejercicio-3', 'metricas-chatbot.json',
);

/**
 * Acumulador en memoria. La suite corre con `workers: 1` (ver playwright.config),
 * así que un único proceso escribe el archivo y no hay carrera. Reescribimos el
 * JSON completo en cada registro para que el archivo quede consistente aunque la
 * corrida se interrumpa a mitad.
 */
const interaccionesDeLaCorrida: (ResultadoInteraccion & { caso: string })[] = [];

/**
 * Persiste una interacción en output/ejercicio-3/metricas-chatbot.json.
 *
 * El Ejercicio 5 consolida este archivo, así que el contrato es explícito y
 * autodescriptivo: nombres de campo en español, tiempos siempre en milisegundos
 * y marcas de tiempo en ISO-8601 UTC.
 */
export function registrarMetrica(
  resultado: ResultadoInteraccion,
  contexto: { caso: string; sitio: string },
): void {
  interaccionesDeLaCorrida.push({ ...resultado, caso: contexto.caso });

  const conRespuesta = interaccionesDeLaCorrida.filter((i) => i.respuestaRecibida);
  const tiempos = conRespuesta.map((i) => i.tiempoRespuestaMs);
  const promedio = tiempos.length
    ? Math.round(tiempos.reduce((a, b) => a + b, 0) / tiempos.length)
    : null;

  const informe = {
    ejercicio: 3,
    descripcion: 'Tiempos de respuesta del asistente de chat de la documentación de Botpress',
    sitio: contexto.sitio,
    widget: {
      nombre: 'Ask Docs',
      tipo: 'panel inline (isla de Astro en el documento principal, no iframe)',
      identidad_declarada: "You're chatting with an AI agent.",
    },
    generado_utc: new Date().toISOString(),
    metodologia:
      'tiempo_respuesta_ms va del clic en Enviar a la primera burbuja del bot con ' +
      'texto visible (time to first token): es la métrica principal, porque no ' +
      'depende de lo larga que sea la respuesta. tiempo_respuesta_completa_ms mide ' +
      'hasta que el streaming deja de crecer, a título informativo.',
    resumen: {
      total_interacciones: interaccionesDeLaCorrida.length,
      respuestas_recibidas: conRespuesta.length,
      tiempo_respuesta_ms_promedio: promedio,
      tiempo_respuesta_ms_min: tiempos.length ? Math.min(...tiempos) : null,
      tiempo_respuesta_ms_max: tiempos.length ? Math.max(...tiempos) : null,
    },
    interacciones: interaccionesDeLaCorrida.map((i, indice) => ({
      id: indice + 1,
      caso: i.caso,
      mensaje_enviado: i.mensaje,
      respuesta_recibida: i.respuestaRecibida,
      tiempo_respuesta_ms: i.tiempoRespuestaMs,
      tiempo_respuesta_completa_ms: i.tiempoRespuestaCompletaMs,
      timestamp_utc: i.timestampUtc,
      extracto_respuesta: i.extracto.slice(0, 300),
    })),
  };

  fs.mkdirSync(path.dirname(RUTA_METRICAS), { recursive: true });
  fs.writeFileSync(RUTA_METRICAS, JSON.stringify(informe, null, 2) + '\n', 'utf-8');
}
