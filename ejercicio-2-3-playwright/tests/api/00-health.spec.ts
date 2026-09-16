/**
 * Health check.
 *
 * Va numerado como 00 a propósito: además de validar el endpoint, es el que
 * absorbe el arranque en frío. La API está desplegada en el plan gratuito de
 * Render, que duerme el contenedor tras un rato de inactividad y tarda hasta un
 * minuto en levantarlo. Sin este calentamiento, la primera prueba que tocara la
 * red fallaría por timeout y el pipeline se vería roto sin estarlo.
 */

import { test, expect } from '@playwright/test';
import { RUTAS, esquemaStatus, validar } from './contrato';

test.describe('Health check', () => {
  test('el servicio responde 200 y se reporta OPERATIONAL', async ({ request }) => {
    test.setTimeout(120_000);

    const inicio = Date.now();
    const respuesta = await request.get(RUTAS.status, { timeout: 100_000 });
    const transcurrido = Date.now() - inicio;

    expect(respuesta.status(), 'el health check debe devolver 200').toBe(200);

    const cuerpo = validar(esquemaStatus, await respuesta.json(), 'GET /status');
    expect(cuerpo.status).toBe('OPERATIONAL');

    // Se registra, no se asevera: un arranque en frío lento es información
    // operativa, no un defecto de la API.
    console.log(`  health check respondió en ${transcurrido} ms`);
  });

  test('responde con JSON, no con HTML de error', async ({ request }) => {
    const respuesta = await request.get(RUTAS.status);
    expect(respuesta.headers()['content-type']).toContain('application/json');
  });
});
