# NOVUM

**Transformamos lo que pasa en oportunidades de mejora.**

Convertí comentarios informales sobre el día a día del trabajo en sugerencias
de mejora estructuradas — con un ícono de apoyo generado por IA para cada una.

## ¿Qué problema resuelve?

En el día a día de una operación surgen constantemente ideas de mejora en
charlas informales: cambios en un recorrido, observaciones de seguridad,
comentarios sobre el lugar de trabajo. Vienen de quienes viven la operación
todos los días, pero no tienen ningún canal formal para registrarlas: se
comentan y se pierden, y nadie tiene tiempo de "traducir" charlas sueltas en
propuestas concretas dirigidas al área que corresponde.

## ¿Cómo funciona?

1. La persona ingresa (por ahora solo como anónimo; el login con legajo y
   DNI está preparado en la interfaz para una futura etapa con seguimiento
   de estado por base de datos).
2. Escribe libremente, en lenguaje natural, qué está pasando.
3. Un modelo de **texto-a-texto** (Groq) extrae la o las sugerencias y
   devuelve, para cada una, un JSON estructurado con: categoría,
   descripción, beneficio esperado, prioridad, **área responsable** de
   evaluarla, y un concepto visual.
4. Un modelo de **texto-a-imagen** (OpenAI) genera un ícono de apoyo simple
   para cada sugerencia, a partir de ese concepto visual.
5. La persona puede enviar el comentario (pasa a una pantalla de
   agradecimiento) o descartarlo y escribir uno nuevo.

## Stack

- **Framework:** [Streamlit](https://streamlit.io/) (Python)
- **Texto-a-texto:** [Groq](https://groq.com/) — `openai/gpt-oss-20b`, zero-shot
  con JSON Schema estricto (garantiza el formato de cada sugerencia).
- **Texto-a-imagen:** [OpenAI](https://platform.openai.com/) — `gpt-image-1-mini`,
  con dos técnicas de prompting seleccionables y comparables desde la sidebar:
  - **Zero-shot**: cada ícono se genera solo con una descripción de texto.
  - **One-shot** (default): se genera una única imagen de referencia por
    sesión, y cada ícono nuevo se genera pidiéndole al modelo que imite su
    estilo — más consistente visualmente entre sugerencias, a cambio de
    ~2x el costo y el tiempo de generación.

## Requisitos

- Python 3.10+
- Una API key de Groq (gratuita) → https://console.groq.com/keys
- Una API key de OpenAI (requiere método de pago cargado) → https://platform.openai.com/api-keys

## Instalación local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Creá `.streamlit/secrets.toml` con tus keys (ese archivo no se versiona):

```toml
GROQ_API_KEY = "tu-key-de-groq"
OPENAI_API_KEY = "tu-key-de-openai"
```

La app queda disponible en `http://localhost:8501`. Si preferís no usar
`secrets.toml`, también podés pegar cada key directamente en su campo de la
barra lateral (nunca se precargan ahí, así que en un deploy público no quedan
expuestas).

Si al analizar aparece un error de conexión con la API (típico en Windows con
antivirus o proxy corporativo que inspecciona el tráfico HTTPS), la app ya
incluye `truststore` para usar el almacén de certificados del sistema
operativo en vez de depender solo de `certifi`.

## Costos (medidos, no estimados)

| Modelo | Técnica | Costo por uso | Tiempo |
|---|---|---|---|
| Texto (Groq) | Zero-shot + JSON Schema | ~US$ 0.0003 | ~1-2s |
| Imagen (OpenAI) | Zero-shot | US$ 0.00235 | ~8.6s |
| Imagen (OpenAI) | One-shot | US$ 0.00485 | ~16.9s |

La imagen de referencia del one-shot se genera una única vez por sesión y se
reutiliza para todos los íconos siguientes, para no pagarla de nuevo en cada
sugerencia.

## Manejo de las keys

Ninguna key queda hardcodeada ni versionada en el repo:

- En local se cargan desde `.streamlit/secrets.toml` (excluido por
  `.gitignore`) o se pegan manualmente en la sidebar.
- En producción (Streamlit Community Cloud) se cargan en
  **Settings → Secrets** de la app deployada, y Streamlit se las inyecta en
  runtime sin que pasen por el repo.

## Deploy

1. Subir el repo a GitHub (`.streamlit/secrets.toml` queda afuera por el
   `.gitignore`).
2. En [share.streamlit.io](https://share.streamlit.io) → **New app** →
   elegir el repo y `app.py` como archivo principal.
3. **Settings → Secrets** → pegar:
   ```toml
   GROQ_API_KEY = "tu-key-de-groq"
   OPENAI_API_KEY = "tu-key-de-openai"
   ```
4. Deploy.
