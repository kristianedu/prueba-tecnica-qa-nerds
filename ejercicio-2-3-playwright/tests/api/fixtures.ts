/**
 * Fixtures del Ejercicio 2.
 *
 * Cada corrida registra su propio usuario con un email único. Es deliberado: la
 * suite tiene que poder ejecutarse cien veces seguidas en CI sin arrastrar
 * estado de la anterior ni chocar contra datos que ya existen.
 */

import { test as base, expect, type APIRequestContext } from '@playwright/test';
import { RUTAS, credencialesUnicas, esquemaLogin, esquemaRegistro, validar } from './contrato';

type Credenciales = ReturnType<typeof credencialesUnicas>;

type FixturesWorker = {
  credenciales: Credenciales;
  token: string;
};

type FixturesTest = {
  /** Contexto ya autenticado: evita repetir la cabecera en cada prueba. */
  apiAuth: APIRequestContext;
};

export const test = base.extend<FixturesTest, FixturesWorker>({
  credenciales: [
    async ({}, use) => {
      await use(credencialesUnicas());
    },
    { scope: 'worker' },
  ],

  token: [
    async ({ credenciales, playwright }, use, workerInfo) => {
      const baseURL = workerInfo.project.use.baseURL!;
      const api = await playwright.request.newContext({ baseURL });

      const registro = await api.post(RUTAS.registro, { data: credenciales });
      expect(
        registro.status(),
        'el registro del usuario de pruebas debe devolver 201',
      ).toBe(201);
      validar(esquemaRegistro, await registro.json(), 'POST /auth/register');

      const login = await api.post(RUTAS.login, {
        data: { email: credenciales.email, password: credenciales.password },
      });
      expect(login.status(), 'el login del usuario de pruebas debe devolver 200').toBe(200);
      const { token } = validar(esquemaLogin, await login.json(), 'POST /auth/login');

      await api.dispose();
      await use(token);
    },
    { scope: 'worker' },
  ],

  apiAuth: async ({ playwright, token }, use, testInfo) => {
    const ctx = await playwright.request.newContext({
      baseURL: testInfo.project.use.baseURL!,
      extraHTTPHeaders: { Authorization: `Bearer ${token}` },
    });
    await use(ctx);
    await ctx.dispose();
  },
});

export { expect };
