# Ejercicio 4 — CI/CD

> **El pipeline vive en [`.github/workflows/qa.yml`](../.github/workflows/qa.yml),
> no en esta carpeta.** GitHub Actions solo ejecuta workflows desde
> `.github/workflows/`: moverlo aquí lo dejaría inerte. Esta carpeta existe para
> que el ejercicio se encuentre desde la raíz del repositorio, junto a los demás.

Pipeline que ejecuta los Ejercicios 1, 2 y 3 en cada push y cada pull request, y
publica un reporte consolidado.

## Evidencia de ejecución

- Historial completo: https://github.com/kristianedu/prueba-tecnica-qa-nerds/actions
- El reporte consolidado se publica en el **resumen de cada ejecución**, y queda
  además como artefacto descargable junto a los reportes HTML de Playwright.

## Los cuatro jobs

| Job | Qué hace |
|---|---|
| **Ejercicio 3 — Chatbot Web** | `npm ci`, instala Chromium y corre las pruebas de interfaz |
| **Ejercicio 2 — API** | `npm ci`, despierta la API y corre las pruebas de API |
| **Ejercicio 1 — Evaluación LLM** | Instala dependencias, corre las 74 pruebas del evaluador y después evalúa contra el modelo real |
| **Ejercicio 5 — Consolidado** | Recupera los artefactos de los tres, genera el reporte y decide el resultado |

El orden Web → API → LLM es el que pide el enunciado. Técnicamente convendría el
inverso —la API es la más rápida y barata, y fallar ahí primero ahorra minutos de
runner—, pero en una prueba técnica se sigue la especificación y se documenta la
observación.

## Decisiones que vale la pena mirar

**Rojo significa "el arnés falló", no "el modelo tiene defectos".** El pipeline
se pone en rojo si las pruebas de API o de interfaz fallan, si el runner se cae,
o si faltan resultados de algún ejercicio. Los escenarios en FAIL del Ejercicio 1
—el modelo inventando capacidades que no existen en su base de conocimiento— son
el *resultado* de la evaluación, no un error de la suite: se publican en el
reporte con el pipeline en verde. Confundir ambas cosas haría que un modelo
defectuoso pareciera un pipeline roto.

**Las pruebas del evaluador van antes de la evaluación.** Corren sin credenciales
y sin red. Si el motor está roto, se corta ahí: no tiene sentido gastar 71
llamadas al modelo para que las evalúe un evaluador que no funciona.

**El reporte se genera aunque algo falle**, gracias al `if: always()` del job de
consolidación. Los jobs de pruebas **no** llevan `continue-on-error`: lo tuvieron,
y con esa bandera un job en rojo no tumbaba la ejecución, así que el pipeline se
reportaba en verde con el Ejercicio 1 fallando.

**Cada job parte de `output/` vacío.** El checkout trae los resultados ya
commiteados; sin esa limpieza, cada job los volvería a subir y, al fusionar los
artefactos, el último en copiarse sobrescribiría lo que generaron los demás con
archivos que ni siquiera tocó.

**Artefactos separados por proyecto.** Los dos projects de Playwright escriben
`playwright-report-{api,ui}/` y `playwright-{api,ui}.json`. Con nombres
compartidos, al juntar los artefactos de jobs distintos uno borraría al otro.

## Configuración necesaria

El Ejercicio 1 evalúa contra un LLM real, así que el repositorio necesita el
secret `GROQ_API_KEY` en *Settings → Secrets and variables → Actions*:

```bash
gh secret set GROQ_API_KEY --repo <usuario>/<repo>
```

Sin él, el job corta con un mensaje explícito en vez de dejar que el SDK falle
más adelante con un error de red que no dice qué configurar.

Opcionalmente, `LLM_MODEL` y `JUDGE_MODEL` como *variables* del repositorio
sobrescriben los modelos por defecto (`openai/gpt-oss-20b` y
`openai/gpt-oss-120b`).
