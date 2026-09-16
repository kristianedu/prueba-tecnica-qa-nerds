/**
 * Caso 1 del enunciado: acceso al sitio.
 *
 * Comprobamos dos cosas distintas que suelen confundirse: que el servidor
 * responde 200 (capa de red) y que la página realmente pinta su contenido
 * (capa de render). Un 200 con la página en blanco seguiría siendo un fallo.
 */
import { test, expect } from '@playwright/test';

/**
 * Se navega a '' en lugar de '/': el baseURL del proyecto `ui` lleva ruta
 * (https://botpress.com/docs) y un '/' absoluto la descartaría, midiendo la
 * portada comercial en vez del sitio de documentación bajo prueba.
 */
const RUTA = '';

test.describe('Ejercicio 3 — Acceso al sitio de documentación', () => {
  test('el sitio responde 200 y entrega HTML', async ({ page }) => {
    const respuesta = await page.goto(RUTA, { waitUntil: 'domcontentloaded' });

    expect(respuesta, 'la navegación debe producir una respuesta').not.toBeNull();
    expect(respuesta!.status(), 'código de estado HTTP').toBe(200);
    expect(respuesta!.headers()['content-type']).toContain('text/html');
  });

  test('los elementos clave de la página son visibles', async ({ page }) => {
    await page.goto(RUTA, { waitUntil: 'domcontentloaded' });

    // El título es lo primero que se rompe si la ruta cambia o si un despliegue
    // deja la página sin contenido.
    await expect(page).toHaveTitle(/Botpress/i);

    await expect(
      page.getByRole('heading', { name: 'Botpress documentation', level: 1 }),
    ).toBeVisible();

    // El buscador es el control principal de la cabecera: si falta, la página
    // se cargó a medias aunque el h1 esté.
    await expect(page.getByRole('button', { name: 'Search docs' })).toBeVisible();

    // Enlaces de navegación reales de la portada de docs.
    await expect(page.getByRole('link', { name: /Botpress Studio/ }).first()).toBeVisible();
  });
});
