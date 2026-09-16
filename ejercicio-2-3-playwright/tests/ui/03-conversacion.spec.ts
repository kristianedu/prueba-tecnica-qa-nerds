/**
 * Caso 4 del enunciado: conversación real con el bot.
 *
 * Se envía "Hola", se verifica que el mensaje entra al historial, que llega una
 * respuesta y se registra el tiempo de respuesta en
 * output/ejercicio-3/metricas-chatbot.json para el Ejercicio 5.
 */
import { test, expect } from '@playwright/test';
import {
  WidgetChat,
  capturarEvidencia,
  registrarMetrica,
  TIMEOUT_RESPUESTA_BOT_MS,
} from './widget-chat';

const MENSAJE = 'Hola';

test.describe('Ejercicio 3 — Conversación con el bot', () => {
  // El timeout global de la suite (90 s) está calibrado para la API del
  // Ejercicio 2. Aquí se suman la carga del sitio y la latencia de un LLM
  // externo, así que este caso necesita su propio margen.
  test.setTimeout(TIMEOUT_RESPUESTA_BOT_MS + 90_000);

  test('envía "Hola", recibe respuesta y registra el tiempo', async ({ page }, testInfo) => {
    const chat = new WidgetChat(page);
    await chat.ir();

    // Punto de partida limpio: sin esto, un historial previo haría que la
    // aserción de "llegó respuesta" pasara sin que el bot contestara nada.
    await expect(chat.respuestasBot).toHaveCount(0);

    const resultado = await chat.enviarYCronometrar(MENSAJE);

    registrarMetrica(resultado, {
      caso: testInfo.title,
      sitio: test.info().project.use.baseURL ?? 'https://botpress.com/docs',
    });

    // --- El mensaje se envió: aparece en el historial con su texto exacto ---
    await expect(
      chat.mensajeUsuario(MENSAJE),
      'el mensaje enviado debe aparecer en el historial con su texto literal',
    ).toBeVisible();

    // El compositor se vacía tras enviar: confirma que el formulario se procesó
    // y no que el texto siga pendiente en la caja.
    await expect(chat.campoMensaje).toHaveValue('');

    // --- Se recibió respuesta del bot ---
    expect(
      resultado.respuestaRecibida,
      `el bot no respondió en ${TIMEOUT_RESPUESTA_BOT_MS} ms`,
    ).toBe(true);
    await expect(chat.respuestasBot.first()).toBeVisible();

    // Contenido con sustancia, no una burbuja vacía ni un eco del saludo.
    expect(resultado.extracto.length, 'la respuesta debe tener contenido real')
      .toBeGreaterThan(10);
    expect(resultado.extracto).not.toBe(MENSAJE);

    // --- Tiempo de respuesta medido y dentro de un rango creíble ---
    expect(resultado.tiempoRespuestaMs).toBeGreaterThan(0);
    expect(resultado.tiempoRespuestaMs).toBeLessThan(TIMEOUT_RESPUESTA_BOT_MS);

    // Evidencia visual de que la conversación ocurrió de verdad: es lo que
    // pide el enunciado y lo que un JSON de resultados no puede demostrar.
    await capturarEvidencia(page, '03-conversacion-con-respuesta', testInfo);

    // Queda en el reporte HTML como evidencia junto al JSON de métricas.
    await testInfo.attach('metrica-respuesta', {
      body: JSON.stringify(resultado, null, 2),
      contentType: 'application/json',
    });
    console.log(
      `[métrica] "${MENSAJE}" respondido en ${resultado.tiempoRespuestaMs} ms — ` +
      `"${resultado.extracto.slice(0, 80)}..."`,
    );
  });

  test('el historial conserva la conversación tras cerrar y reabrir el panel', async ({ page }, testInfo) => {
    const chat = new WidgetChat(page);
    await chat.ir();

    const resultado = await chat.enviarYCronometrar(MENSAJE);
    // Segunda muestra de latencia: con una sola medición el min/max/promedio del
    // informe no diría nada sobre la variabilidad del servicio.
    registrarMetrica(resultado, {
      caso: testInfo.title,
      sitio: test.info().project.use.baseURL ?? 'https://botpress.com/docs',
    });
    expect(resultado.respuestaRecibida, 'se necesita una respuesta para validar la persistencia').toBe(true);

    await chat.cerrar();
    await chat.abrir();

    // Cerrar el panel no debe descartar la conversación en curso: es el fallo
    // clásico cuando el widget desmonta su estado al ocultarse.
    await expect(chat.mensajeUsuario(MENSAJE)).toBeVisible();
    await expect(chat.respuestasBot.first()).toBeVisible();
  });
});
