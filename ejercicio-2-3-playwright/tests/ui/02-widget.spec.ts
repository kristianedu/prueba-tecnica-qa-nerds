/**
 * Casos 2 y 3 del enunciado: existencia del widget e interacción con él
 * (abrir, cerrar y leer el nombre del bot).
 */
import { test, expect } from '@playwright/test';
import { WidgetChat, capturarEvidencia } from './widget-chat';

test.describe('Ejercicio 3 — Widget de chat', () => {
  test('el widget existe y está montado en la página', async ({ page }) => {
    const chat = new WidgetChat(page);
    await chat.ir();

    // El disparador de la barra superior es la prueba de que el widget forma
    // parte del sitio, no de que esté abierto.
    await expect(chat.botonAbrir).toBeVisible();
    await expect(chat.raiz).toBeAttached();

    // Controles propios del asistente: compositor y envío.
    await expect(chat.campoMensaje).toBeVisible();
    await expect(chat.botonEnviar).toBeVisible();
  });

  test('el botón de cerrar colapsa el panel y el de abrir lo restaura', async ({ page }, testInfo) => {
    const chat = new WidgetChat(page);
    await chat.ir();

    // En escritorio el panel viene desplegado de fábrica, así que el recorrido
    // natural es cerrar primero y reabrir después.
    expect(await chat.estaAbierto(), 'el panel debería venir abierto en escritorio').toBe(true);

    await chat.cerrar();
    await expect(chat.campoMensaje).toBeHidden();
    await capturarEvidencia(page, '02-panel-cerrado', testInfo);
    // Al cerrar, el disparador debe seguir ahí: si no, el widget quedaría
    // inaccesible para el usuario.
    await expect(chat.botonAbrir).toBeVisible();

    await chat.abrir();
    await expect(chat.campoMensaje).toBeVisible();
    await expect(chat.botonEnviar).toBeVisible();
    await capturarEvidencia(page, '02-panel-reabierto', testInfo);
  });

  test('el widget muestra su nombre y declara que es un agente de IA', async ({ page }) => {
    const chat = new WidgetChat(page);
    await chat.ir();

    // El asistente no expone un nombre propio tipo "Bot Sarah": se identifica
    // por el nombre del widget ("Ask Docs"), por el título de la conversación
    // y por el descargo del pie. Validamos los tres porque juntos son lo que el
    // usuario lee como "con quién estoy hablando".
    await expect(chat.botonAbrir).toHaveText(/Ask Docs/);
    await expect(chat.tituloConversacion).toBeVisible();
    await expect(chat.identidadBot).toBeVisible();
    await expect(chat.identidadBot).toHaveText(/You're chatting with an AI agent/);
  });
});
