/**
 * Contrato de la Goal Tracker API.
 *
 * Todo lo que hay aquí se descubrió explorando la API real con curl, no se
 * dedujo del enunciado: el enunciado no especifica los códigos de creación, la
 * forma de los payloads ni los mensajes de error. Validar contra el contrato
 * real es la diferencia entre "probé la API" y "validé la API".
 */

import { z } from 'zod';

export const RUTAS = {
  status: '/api/v1/status',
  registro: '/api/v1/auth/register',
  login: '/api/v1/auth/login',
  goals: '/api/v1/goals',
  goal: (id: string) => `/api/v1/goals/${id}`,
} as const;

/** Un ObjectId de MongoDB: 24 caracteres hexadecimales. */
export const esquemaId = z.string().regex(/^[a-f0-9]{24}$/i, 'no parece un ObjectId válido');

export const esquemaStatus = z.object({
  status: z.literal('OPERATIONAL'),
});

export const esquemaRegistro = z.object({
  user: z.object({
    name: z.string().min(1),
    email: z.string().email(),
  }),
});

export const esquemaLogin = z.object({
  msg: z.string(),
  // JWT: tres segmentos separados por puntos.
  token: z.string().regex(/^[\w-]+\.[\w-]+\.[\w-]+$/, 'no tiene forma de JWT'),
});

export const esquemaError = z.object({
  msg: z.string().min(1),
});

export const esquemaGoal = z.object({
  _id: esquemaId,
  title: z.string().min(1),
  description: z.string().min(1),
  status: z.enum(['to-do', 'in-progress', 'done']),
  priority: z.enum(['low', 'medium', 'high']),
  createdBy: esquemaId,
  createdAt: z.string().datetime(),
});

export const esquemaGoalCreado = z.object({ goal: esquemaGoal });
export const esquemaListaGoals = z.object({ goals: z.array(esquemaGoal) });

export type Goal = z.infer<typeof esquemaGoal>;

/**
 * Valida un payload contra su esquema y falla con un mensaje legible.
 *
 * Zod ya trae `.parse()`, pero su error crudo es ilegible en el reporte de
 * Playwright. Esto lo aplana a "campo: problema", que es lo que uno quiere leer
 * cuando una prueba falla en CI a las dos de la mañana.
 */
export function validar<T>(esquema: z.ZodType<T>, payload: unknown, contexto: string): T {
  const r = esquema.safeParse(payload);
  if (!r.success) {
    const detalles = r.error.issues
      .map((i) => `  - ${i.path.join('.') || '(raíz)'}: ${i.message}`)
      .join('\n');
    throw new Error(
      `El contrato de ${contexto} no se cumple:\n${detalles}\n` +
        `Payload recibido: ${JSON.stringify(payload)}`,
    );
  }
  return r.data;
}

/** Credenciales únicas por corrida: la suite tiene que poder repetirse. */
export function credencialesUnicas() {
  const sello = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  return {
    name: 'QA Automatizado',
    email: `qa.automatizado.${sello}@example.com`,
    password: 'Passw0rd!23',
  };
}
