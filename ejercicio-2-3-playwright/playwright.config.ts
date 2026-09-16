import { defineConfig, devices } from '@playwright/test';
import * as dotenv from 'dotenv';
import * as path from 'path';

dotenv.config({ path: path.resolve(__dirname, '..', '.env') });

// Salida unificada: el Ejercicio 5 consolida desde aquí.
const SALIDA = path.resolve(__dirname, '..', 'output');

// Sufijo por proyecto. Los jobs de CI corren en runners distintos y sus
// artefactos se fusionan en un mismo directorio: si ambos escribieran con el
// mismo nombre, uno sobrescribiría al otro y el consolidado perdería medio
// ejercicio. Lo fijan los scripts de npm.
const TAG = process.env.PW_TAG ?? 'resultados';

export default defineConfig({
  testDir: './tests',
  // La API en Render duerme en el plan gratuito: el primer golpe puede tardar
  // casi un minuto en levantar el contenedor.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(SALIDA, `playwright-report-${TAG}`), open: 'never' }],
    ['json', { outputFile: path.join(SALIDA, `playwright-${TAG}.json`) }],
  ],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      // Ejercicio 2 — pruebas de API. Sin navegador.
      name: 'api',
      testDir: './tests/api',
      use: { baseURL: process.env.API_BASE_URL ?? 'https://goal-tracker-api.onrender.com' },
    },
    {
      // Ejercicio 3 — pruebas de interfaz sobre el widget de chat.
      name: 'ui',
      testDir: './tests/ui',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: process.env.CHATBOT_URL ?? 'https://botpress.com/docs',
      },
    },
  ],
});
