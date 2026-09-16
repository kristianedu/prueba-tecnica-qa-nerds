/**
 * Ciclo de vida completo de los goals.
 *
 * El bloque principal va en modo `serial` porque es exactamente eso: un ciclo
 * de vida. Crear, consultar, listar y borrar son pasos encadenados de un mismo
 * recorrido, y partirlos en pruebas independientes obligaría a recrear el
 * estado en cada una, que es más lento y prueba menos.
 *
 * Las validaciones y los casos de autorización sí van aparte, porque no
 * dependen de ese estado.
 */

import { test, expect } from './fixtures';
import {
  RUTAS,
  esquemaError,
  esquemaGoal,
  esquemaGoalCreado,
  esquemaListaGoals,
  validar,
  type Goal,
} from './contrato';

const GOALS_A_CREAR = [
  {
    title: 'Automatizar la suite de API',
    description: 'Cubrir el ciclo completo de usuario y goals con Playwright',
    status: 'to-do',
    priority: 'high',
  },
  {
    title: 'Documentar los hallazgos',
    description: 'Redactar el reporte consolidado de la prueba técnica',
    status: 'in-progress',
    priority: 'medium',
  },
] as const;

test.describe.serial('Ciclo de vida de los goals', () => {
  const creados: Goal[] = [];

  test('crea dos goals distintos con 201 y datos íntegros', async ({ apiAuth }) => {
    for (const entrada of GOALS_A_CREAR) {
      const antes = Date.now();
      const respuesta = await apiAuth.post(RUTAS.goals, { data: entrada });

      expect(respuesta.status(), `crear "${entrada.title}" debe devolver 201`).toBe(201);
      const { goal } = validar(esquemaGoalCreado, await respuesta.json(), 'POST /goals');

      // Campos obligatorios: vuelven tal cual se enviaron.
      expect(goal.title).toBe(entrada.title);
      expect(goal.description).toBe(entrada.description);
      expect(goal.status).toBe(entrada.status);
      expect(goal.priority).toBe(entrada.priority);

      // ID generado por el servidor (el esquema ya validó su forma).
      expect(goal._id).toBeTruthy();

      // Fecha de creación: tiene que ser real y de ahora, no un placeholder.
      const creadoEn = new Date(goal.createdAt).getTime();
      expect(Number.isNaN(creadoEn), 'createdAt debe ser una fecha parseable').toBe(false);
      expect(creadoEn).toBeGreaterThanOrEqual(antes - 60_000);
      expect(creadoEn).toBeLessThanOrEqual(Date.now() + 60_000);

      creados.push(goal);
    }

    expect(creados[0]._id, 'cada goal debe recibir un ID distinto').not.toBe(creados[1]._id);
  });

  test('consulta un goal por su ID y los datos coinciden con los creados', async ({ apiAuth }) => {
    const esperado = creados[0];
    const respuesta = await apiAuth.get(RUTAS.goal(esperado._id));

    expect(respuesta.status()).toBe(200);
    const cuerpo = validar(
      esquemaGoal.or(esquemaGoalCreado),
      await respuesta.json(),
      'GET /goals/:id',
    );
    const goal = 'goal' in cuerpo ? cuerpo.goal : cuerpo;

    // Integridad: el recurso leído es idéntico al que devolvió la creación.
    expect(goal).toEqual(esperado);
  });

  test('el listado incluye los dos goals creados y su cantidad es correcta', async ({
    apiAuth,
  }) => {
    const respuesta = await apiAuth.get(RUTAS.goals);

    expect(respuesta.status()).toBe(200);
    const { goals } = validar(esquemaListaGoals, await respuesta.json(), 'GET /goals');

    // El usuario es único por corrida, así que el listado es exactamente lo que
    // esta suite creó: se puede afirmar la cantidad sin riesgo de flakiness.
    expect(goals).toHaveLength(GOALS_A_CREAR.length);

    const idsListados = goals.map((g) => g._id).sort();
    const idsCreados = creados.map((g) => g._id).sort();
    expect(idsListados).toEqual(idsCreados);

    for (const esperado of GOALS_A_CREAR) {
      expect(
        goals.some((g) => g.title === esperado.title),
        `el listado debe contener "${esperado.title}"`,
      ).toBe(true);
    }
  });

  test('elimina un goal y deja de existir después', async ({ apiAuth }) => {
    const objetivo = creados[0];

    const borrado = await apiAuth.delete(RUTAS.goal(objetivo._id));
    expect(borrado.status(), 'el borrado exitoso debe devolver 200').toBe(200);
    const cuerpo = validar(esquemaError, await borrado.json(), 'DELETE /goals/:id');
    expect(cuerpo.msg).toBe('Success! Goal removed.');

    // Lo que importa no es el 200 del borrado, sino que el recurso ya no esté.
    const posterior = await apiAuth.get(RUTAS.goal(objetivo._id));
    expect(posterior.status(), 'el goal borrado ya no debe encontrarse').toBe(404);

    // Y el listado tiene que reflejarlo.
    const listado = await apiAuth.get(RUTAS.goals);
    const { goals } = validar(esquemaListaGoals, await listado.json(), 'GET /goals tras borrar');
    expect(goals).toHaveLength(GOALS_A_CREAR.length - 1);
    expect(goals.some((g) => g._id === objetivo._id)).toBe(false);
  });

  test('borrar dos veces el mismo goal devuelve 404', async ({ apiAuth }) => {
    const respuesta = await apiAuth.delete(RUTAS.goal(creados[0]._id));
    expect(respuesta.status()).toBe(404);
  });
});

test.describe('Validaciones al crear', () => {
  test('rechaza un goal sin título ni descripción', async ({ apiAuth }) => {
    const respuesta = await apiAuth.post(RUTAS.goals, { data: {} });

    expect(respuesta.status()).toBe(400);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'POST /goals vacío');
    expect(cuerpo.msg).toContain('Please add a title');
    expect(cuerpo.msg).toContain('Please add a description');
  });

  test('rechaza un goal sin título', async ({ apiAuth }) => {
    const respuesta = await apiAuth.post(RUTAS.goals, { data: { description: 'Solo descripción' } });

    expect(respuesta.status()).toBe(400);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'POST /goals sin título');
    expect(cuerpo.msg).toContain('Please add a title');
  });

  test('aplica valores por defecto de status y priority', async ({ apiAuth }) => {
    const respuesta = await apiAuth.post(RUTAS.goals, {
      data: { title: 'Sin estado explícito', description: 'Debe tomar los valores por defecto' },
    });

    expect(respuesta.status()).toBe(201);
    const { goal } = validar(esquemaGoalCreado, await respuesta.json(), 'POST /goals por defecto');
    expect(goal.status).toBe('to-do');
    expect(goal.priority).toBe('low');

    await apiAuth.delete(RUTAS.goal(goal._id));
  });
});

test.describe('Consultas inexistentes', () => {
  test('un ID válido pero ausente devuelve 404', async ({ apiAuth }) => {
    const respuesta = await apiAuth.get(RUTAS.goal('6aa9f249baddca5830be4999'));

    expect(respuesta.status()).toBe(404);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'GET /goals/:id ausente');
    expect(cuerpo.msg).toContain('No goal with id');
  });

  test('un ID malformado también devuelve 404 y no un 500', async ({ apiAuth }) => {
    // Importa distinguirlo: un 500 aquí significaría que un ID basura llega sin
    // filtrar hasta la capa de base de datos.
    const respuesta = await apiAuth.get(RUTAS.goal('no-es-un-object-id'));

    expect(respuesta.status()).toBe(404);
    validar(esquemaError, await respuesta.json(), 'GET /goals/:id malformado');
  });
});

test.describe('Autorización', () => {
  test('sin token devuelve 401', async ({ request }) => {
    const respuesta = await request.get(RUTAS.goals);

    expect(respuesta.status()).toBe(401);
    const cuerpo = validar(esquemaError, await respuesta.json(), 'GET /goals sin token');
    expect(cuerpo.msg).toBe('Authentication invalid');
  });

  test('con un token inválido devuelve 401', async ({ playwright }, testInfo) => {
    const ctx = await playwright.request.newContext({
      baseURL: testInfo.project.use.baseURL!,
      extraHTTPHeaders: { Authorization: 'Bearer token.completamente.falso' },
    });

    const respuesta = await ctx.get(RUTAS.goals);
    expect(respuesta.status()).toBe(401);

    await ctx.dispose();
  });

  test('no se puede crear un goal sin autenticación', async ({ request }) => {
    const respuesta = await request.post(RUTAS.goals, {
      data: { title: 'Intruso', description: 'No debería crearse' },
    });
    expect(respuesta.status()).toBe(401);
  });
});
