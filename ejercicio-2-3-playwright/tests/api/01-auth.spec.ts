/**
 * Registro y login.
 *
 * Los mensajes de error que se afirman aquí se copiaron de la API real, no se
 * inventaron. Un test que espera un texto que la API nunca devuelve es peor que
 * no tener test: pasa a rojo permanente y se termina ignorando.
 */

import { test, expect } from '@playwright/test';
import {
  RUTAS,
  credencialesUnicas,
  esquemaError,
  esquemaLogin,
  esquemaRegistro,
  validar,
} from './contrato';

test.describe('Registro', () => {
  test('registra un usuario nuevo y devuelve 201 con sus datos', async ({ request }) => {
    const nuevo = credencialesUnicas();

    const respuesta = await request.post(RUTAS.registro, { data: nuevo });

    expect(respuesta.status(), 'el registro exitoso debe devolver 201').toBe(201);
    const cuerpo = validar(esquemaRegistro, await respuesta.json(), 'POST /auth/register');

    expect(cuerpo.user.name, 'el nombre debe volver tal cual se envió').toBe(nuevo.name);
    expect(cuerpo.user.email, 'el email debe volver tal cual se envió').toBe(nuevo.email);

    // La contraseña jamás debe viajar de vuelta, ni siquiera hasheada.
    expect(JSON.stringify(cuerpo)).not.toContain(nuevo.password);
    expect(cuerpo.user).not.toHaveProperty('password');
  });

  test('rechaza un email ya registrado', async ({ request }) => {
    const usuario = credencialesUnicas();
    await request.post(RUTAS.registro, { data: usuario });

    const duplicado = await request.post(RUTAS.registro, { data: usuario });

    expect(duplicado.status()).toBe(400);
    const cuerpo = validar(esquemaError, await duplicado.json(), 'POST /auth/register duplicado');
    expect(cuerpo.msg).toBe('Email address already exists');
  });

  test('rechaza un registro sin campos obligatorios', async ({ request }) => {
    const respuesta = await request.post(RUTAS.registro, { data: {} });

    expect(respuesta.status()).toBe(400);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'POST /auth/register vacío');
    expect(cuerpo.msg).toBe('Please provide a name, email address and password');
  });
});

test.describe('Login', () => {
  test('con credenciales válidas devuelve 200 y un JWT', async ({ request }) => {
    const usuario = credencialesUnicas();
    await request.post(RUTAS.registro, { data: usuario });

    const respuesta = await request.post(RUTAS.login, {
      data: { email: usuario.email, password: usuario.password },
    });

    expect(respuesta.status()).toBe(200);
    const cuerpo = validar(esquemaLogin, await respuesta.json(), 'POST /auth/login');
    expect(cuerpo.msg).toBe('Successfully logged in');

    // El esquema ya verificó la forma del JWT; aquí se comprueba que el
    // contenido corresponde a quien inició sesión, no a otra persona.
    const payload = JSON.parse(
      Buffer.from(cuerpo.token.split('.')[1], 'base64').toString('utf8'),
    );
    expect(payload.email).toBe(usuario.email);
    expect(payload.name).toBe(usuario.name);
    expect(payload.exp, 'el token debe traer fecha de expiración').toBeGreaterThan(
      Math.floor(Date.now() / 1000),
    );
  });

  test('con contraseña incorrecta devuelve 401 e Invalid Credentials', async ({ request }) => {
    const usuario = credencialesUnicas();
    await request.post(RUTAS.registro, { data: usuario });

    const respuesta = await request.post(RUTAS.login, {
      data: { email: usuario.email, password: 'contraseña-equivocada' },
    });

    expect(respuesta.status(), 'las credenciales inválidas deben devolver 401').toBe(401);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'POST /auth/login inválido');
    expect(cuerpo.msg).toBe('Invalid Credentials');
  });

  test('con un email inexistente también devuelve 401, sin revelar si existe', async ({
    request,
  }) => {
    const respuesta = await request.post(RUTAS.login, {
      data: { email: `nadie.${Date.now()}@example.com`, password: 'loQueSea123' },
    });

    expect(respuesta.status()).toBe(401);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'POST /auth/login inexistente');

    // Mismo mensaje que para contraseña incorrecta: la API no filtra qué
    // correos están registrados, que es el comportamiento correcto.
    expect(cuerpo.msg).toBe('Invalid Credentials');
  });

  test('rechaza un login sin contraseña', async ({ request }) => {
    const respuesta = await request.post(RUTAS.login, { data: { email: 'a@example.com' } });

    expect(respuesta.status()).toBe(400);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'POST /auth/login incompleto');
    expect(cuerpo.msg).toBe('Please provide an email address and password');
  });
});
