"""NOVUM.

App Streamlit que transforma comentarios informales de empleados en
sugerencias de mejora estructuradas (texto-a-texto, Groq) y genera un
ícono de apoyo para cada una (texto-a-imagen, OpenAI).
"""

import base64
import io
import json
import time

import truststore

truststore.inject_into_ssl()

import streamlit as st
from groq import Groq
import groq
from openai import OpenAI
import openai

SYSTEM_PROMPT = """Actuás como un asistente que ayuda a una empresa a capturar ideas de mejora
de sus empleados. Vas a recibir un comentario informal, escrito en lenguaje
natural, que puede referirse a cualquier aspecto del trabajo diario
(operativo, comedor, uniforme, forma de trabajar, seguridad, etc.).

Respondé siempre en español rioplatense, sin importar en qué idioma esté
escrito el comentario de entrada.

Tu tarea es extraer la o las sugerencias y devolver, para cada una:
- categoria: una de ["operativo", "comedor", "uniforme", "forma_de_trabajo", "seguridad", "otro"]
- descripcion: la mejora propuesta, reformulada de forma clara y concisa
- beneficio_esperado: qué se ganaría si se implementa
- prioridad: "alta", "media" o "baja", según el impacto potencial
- area_responsable: el área de la empresa que debería hacerse cargo de
  evaluar o implementar la mejora, una de ["operaciones_logistica",
  "mantenimiento", "rrhh", "seguridad_e_higiene", "compras_abastecimiento",
  "sistemas_it", "direccion_gerencia", "otro"]
- concepto_visual: una frase corta describiendo un ícono simple y plano que
  represente la idea central de la sugerencia, sin texto dentro de la imagen

Devolvé únicamente un JSON con la clave "sugerencias" y un array de objetos
con esos seis campos. Si el comentario menciona varias ideas distintas,
generá un objeto por cada una. Si no hay ninguna sugerencia real en el
texto, devolvé un array vacío."""

MODELOS_TEXTO = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
MODELO_IMAGEN = "gpt-image-1-mini"
TAMANO_IMAGEN = "1024x1024"
CALIDAD_IMAGEN = "low"

PRIORIDAD_BADGE_COLOR = {
    "alta": "red",
    "media": "orange",
    "baja": "green",
}

CATEGORIA_ICONO = {
    "operativo": "⚙️",
    "comedor": "🍽️",
    "uniforme": "🦺",
    "forma_de_trabajo": "🧭",
    "seguridad": "⚠️",
    "otro": "✨",
}

AREA_ICONO = {
    "operaciones_logistica": "📦",
    "mantenimiento": "🔧",
    "rrhh": "🧑‍💼",
    "seguridad_e_higiene": "🛟",
    "compras_abastecimiento": "🛒",
    "sistemas_it": "💻",
    "direccion_gerencia": "🏢",
    "otro": "✨",
}

AREA_NOMBRE = {
    "operaciones_logistica": "Operaciones y Logística",
    "mantenimiento": "Mantenimiento",
    "rrhh": "Recursos Humanos",
    "seguridad_e_higiene": "Seguridad e Higiene",
    "compras_abastecimiento": "Compras y Abastecimiento",
    "sistemas_it": "Sistemas / IT",
    "direccion_gerencia": "Dirección / Gerencia",
    "otro": "el área correspondiente",
}

# Precios oficiales publicados por cada proveedor (USD por 1M tokens), usados
# para cuantificar el costo real de cada análisis con los tokens que
# devuelve cada respuesta.
PRECIO_TEXTO = {
    "openai/gpt-oss-20b": {"entrada": 0.075, "salida": 0.30},
    "openai/gpt-oss-120b": {"entrada": 0.15, "salida": 0.60},
}
PRECIO_IMAGEN = {"texto_entrada": 2.00, "imagen_entrada": 2.50, "salida": 8.00}

MAX_COMPLETION_TOKENS = 2560

# JSON Schema estricto: obliga al modelo a devolver siempre exactamente estos
# 6 campos por sugerencia.
RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "sugerencias_mejora",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "sugerencias": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "categoria": {
                                "type": "string",
                                "enum": [
                                    "operativo",
                                    "comedor",
                                    "uniforme",
                                    "forma_de_trabajo",
                                    "seguridad",
                                    "otro",
                                ],
                            },
                            "descripcion": {"type": "string"},
                            "beneficio_esperado": {"type": "string"},
                            "prioridad": {"type": "string", "enum": ["alta", "media", "baja"]},
                            "area_responsable": {
                                "type": "string",
                                "enum": [
                                    "operaciones_logistica",
                                    "mantenimiento",
                                    "rrhh",
                                    "seguridad_e_higiene",
                                    "compras_abastecimiento",
                                    "sistemas_it",
                                    "direccion_gerencia",
                                    "otro",
                                ],
                            },
                            "concepto_visual": {"type": "string"},
                        },
                        "required": [
                            "categoria",
                            "descripcion",
                            "beneficio_esperado",
                            "prioridad",
                            "area_responsable",
                            "concepto_visual",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["sugerencias"],
            "additionalProperties": False,
        },
    },
}

# Estilo visual único de Novum, reutilizado en todos los prompts de imagen
# para que los íconos sean coherentes entre sí. Regla fija, sin excepciones:
# ninguna imagen lleva texto incrustado.
ESTILO_BASE = (
    "Ilustración digital plana (flat design), fondo blanco, paleta de "
    "colores suaves (violeta #6D5DF6, gris azulado #5E8A96), sin sombras "
    "duras, esquinas redondeadas, un solo elemento central, formato "
    "cuadrado 1:1, sin texto, sin marcas de agua."
)
CONCEPTO_REFERENCIA = "un engranaje simple representando mejora continua"

FONDO_PATH = "assets/banner.jpg"
COLOR_TITULO = "#7A4A00"


@st.cache_data
def _imagen_como_data_uri(ruta):
    with open(ruta, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:image/jpeg;base64,{b64}"


def render_fondo():
    """Imagen de fondo fija, a pantalla completa, solo en el área principal
    (no en la sidebar). Se llama una vez al inicio de main(), así queda
    presente en todas las vistas (login, formulario, resultados, gracias)."""
    fondo = _imagen_como_data_uri(FONDO_PATH)
    st.markdown(
        f"""
        <style>
        [data-testid="stMain"] {{
            background-color: #FFDC00;
            background-image: url("{fondo}");
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            background-attachment: fixed;
        }}
        [class*="st-key-novum_sugerencia_"] {{
            background: rgba(255, 255, 255, 0.65);
            border-radius: 12px;
        }}
        .st-key-novum_gracias_texto {{
            background: rgba(255, 255, 255, 0.65);
            border-radius: 16px;
            padding: 1.5rem 2rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def obtener_secreto(nombre):
    """Lee una key de st.secrets. Si no existe secrets.toml, no rompe."""
    try:
        return st.secrets.get(nombre, "")
    except Exception:
        return ""


def render_sidebar():
    """Dibuja la configuración de la barra lateral y devuelve sus valores.

    Los campos de key arrancan siempre vacíos: si tuvieran como valor
    precargado la key de st.secrets, esa key quedaría visible en el HTML de
    la página para cualquiera que abra la app pública. La key del servidor
    se usa como fallback silencioso solo si el campo queda vacío.
    """
    groq_key_servidor = obtener_secreto("GROQ_API_KEY")
    openai_key_servidor = obtener_secreto("OPENAI_API_KEY")

    with st.sidebar:
        st.header("⚙️ Configuración")

        st.caption("Modelo de texto (Groq)")
        groq_key_ingresada = st.text_input(
            "Groq API Key",
            value="",
            type="password",
            help="Si hay una key configurada en el servidor se usa automáticamente.",
        )
        groq_key = groq_key_ingresada or groq_key_servidor
        if groq_key_servidor and not groq_key_ingresada:
            st.caption("✅ Usando la key de Groq del servidor.")

        modelo_texto = st.selectbox("Modelo de texto", MODELOS_TEXTO, index=0)
        temperatura = st.slider(
            "Temperatura", min_value=0.0, max_value=1.0, value=0.3, step=0.05
        )

        st.divider()
        st.caption("Modelo de imagen (OpenAI)")
        openai_key_ingresada = st.text_input(
            "OpenAI API Key",
            value="",
            type="password",
            help="Si hay una key configurada en el servidor se usa automáticamente.",
        )
        openai_key = openai_key_ingresada or openai_key_servidor
        if openai_key_servidor and not openai_key_ingresada:
            st.caption("✅ Usando la key de OpenAI del servidor.")

        generar_iconos = st.checkbox(
            "Generar íconos con IA",
            value=True,
            help="Tiene un costo adicional por imagen. Desactivalo para probar solo el análisis de texto.",
        )
        tecnica_imagen = st.radio(
            "Técnica de prompting para los íconos",
            ["One-shot (con imagen de referencia)", "Zero-shot (sin referencia)"],
            help="Comparación de las dos técnicas de fast prompting aplicadas al modelo de imagen.",
            disabled=not generar_iconos,
        )

    return {
        "groq_key": groq_key,
        "modelo_texto": modelo_texto,
        "temperatura": temperatura,
        "openai_key": openai_key,
        "generar_iconos": generar_iconos,
        "one_shot": tecnica_imagen.startswith("One-shot"),
    }


def analizar_comentario(groq_key, modelo, temperatura, comentario):
    """Llama a la API de Groq (texto-a-texto, zero-shot + JSON Schema estricto).

    Devuelve (respuesta, tiempo_respuesta, error).
    """
    client = Groq(api_key=groq_key, timeout=30.0)
    inicio = time.time()
    try:
        respuesta = client.chat.completions.create(
            model=modelo,
            temperature=temperatura,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            response_format=RESPONSE_SCHEMA,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": comentario},
            ],
        )
    except groq.AuthenticationError:
        return None, None, "La API key de Groq no es válida. Revisala en la barra lateral."
    except groq.RateLimitError:
        return None, None, "Se alcanzó el límite de uso de la API de Groq. Probá de nuevo en unos minutos."
    except groq.APITimeoutError:
        return None, None, "La API de Groq tardó demasiado en responder. Probá de nuevo."
    except groq.APIConnectionError:
        return None, None, "No se pudo conectar con la API de Groq. Revisá tu conexión e intentá de nuevo."
    except groq.APIStatusError as e:
        return None, None, f"La API de Groq devolvió un error ({e.status_code}). Intentá de nuevo más tarde."
    except groq.APIError as e:
        return None, None, f"Ocurrió un error inesperado al llamar a la API de Groq: {e}"

    return respuesta, time.time() - inicio, None


def parsear_sugerencias(respuesta):
    """Parsea el JSON de la respuesta. Devuelve (datos, sugerencias, contenido_invalido)."""
    contenido = respuesta.choices[0].message.content
    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError:
        return None, None, contenido
    return datos, datos.get("sugerencias", []), None


def calcular_costo_texto(modelo, respuesta):
    precio = PRECIO_TEXTO.get(modelo)
    if precio is None:
        return None
    return (
        respuesta.usage.prompt_tokens * precio["entrada"]
        + respuesta.usage.completion_tokens * precio["salida"]
    ) / 1_000_000


def calcular_costo_imagen(usage):
    if usage is None:
        return None
    detalles = getattr(usage, "input_tokens_details", None)
    texto_in = getattr(detalles, "text_tokens", usage.input_tokens) if detalles else usage.input_tokens
    imagen_in = getattr(detalles, "image_tokens", 0) if detalles else 0
    return (
        texto_in * PRECIO_IMAGEN["texto_entrada"]
        + imagen_in * PRECIO_IMAGEN["imagen_entrada"]
        + usage.output_tokens * PRECIO_IMAGEN["salida"]
    ) / 1_000_000


def _manejar_error_openai(e):
    if isinstance(e, openai.AuthenticationError):
        return "La API key de OpenAI no es válida. Revisala en la barra lateral."
    if isinstance(e, openai.RateLimitError):
        return "Se alcanzó el límite de uso de la API de OpenAI. Probá de nuevo en unos minutos."
    if isinstance(e, openai.APITimeoutError):
        return "La API de OpenAI tardó demasiado en responder. Probá de nuevo."
    if isinstance(e, openai.APIConnectionError):
        return "No se pudo conectar con la API de OpenAI. Revisá tu conexión e intentá de nuevo."
    if isinstance(e, openai.APIStatusError):
        return f"La API de OpenAI devolvió un error ({e.status_code}). Intentá de nuevo más tarde."
    return f"Ocurrió un error inesperado al generar la imagen: {e}"


def generar_imagen_zero_shot(client, concepto_visual):
    """Genera un ícono desde cero, solo con una descripción de texto.

    Devuelve (imagen_bytes, tiempo, costo, error).
    """
    prompt = f"{ESTILO_BASE} Ícono que represente: {concepto_visual}."
    inicio = time.time()
    try:
        resultado = client.images.generate(
            model=MODELO_IMAGEN, prompt=prompt, size=TAMANO_IMAGEN, quality=CALIDAD_IMAGEN
        )
    except openai.OpenAIError as e:
        return None, None, None, _manejar_error_openai(e)

    tiempo = time.time() - inicio
    imagen_bytes = base64.b64decode(resultado.data[0].b64_json)
    costo = calcular_costo_imagen(getattr(resultado, "usage", None))
    return imagen_bytes, tiempo, costo, None


def generar_imagen_one_shot(client, concepto_visual, imagen_referencia):
    """Genera un ícono nuevo imitando el estilo de una imagen de referencia.

    Devuelve (imagen_bytes, tiempo, costo, error).
    """
    prompt = (
        "Generá un nuevo ícono que mantenga exactamente el mismo estilo "
        "visual, la misma paleta de colores y la misma composición que la "
        f"imagen de referencia, pero que represente en cambio: "
        f"{concepto_visual}. Sin texto en la imagen."
    )
    referencia = io.BytesIO(imagen_referencia)
    referencia.name = "referencia.png"

    inicio = time.time()
    try:
        resultado = client.images.edit(
            model=MODELO_IMAGEN,
            image=referencia,
            prompt=prompt,
            size=TAMANO_IMAGEN,
            quality=CALIDAD_IMAGEN,
        )
    except openai.OpenAIError as e:
        return None, None, None, _manejar_error_openai(e)

    tiempo = time.time() - inicio
    imagen_bytes = base64.b64decode(resultado.data[0].b64_json)
    costo = calcular_costo_imagen(getattr(resultado, "usage", None))
    return imagen_bytes, tiempo, costo, None


def obtener_imagen_referencia(client):
    """Genera la imagen semilla del one-shot una sola vez por sesión.

    Se cachea en st.session_state para no volver a pagarla en cada
    sugerencia ni en cada re-render de la página.
    """
    if "novum_imagen_referencia" not in st.session_state:
        imagen_bytes, _, costo, error = generar_imagen_zero_shot(client, CONCEPTO_REFERENCIA)
        if error:
            return None, None, error
        st.session_state["novum_imagen_referencia"] = imagen_bytes
        st.session_state["novum_costo_referencia"] = costo

    return (
        st.session_state["novum_imagen_referencia"],
        st.session_state.get("novum_costo_referencia"),
        None,
    )


def render_metricas_texto(tiempo_respuesta, tokens_entrada, tokens_salida, costo):
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("⏱️ Tiempo", f"{tiempo_respuesta:.2f} s")
    col2.metric("📥 Tokens entrada", tokens_entrada)
    col3.metric("📤 Tokens salida", tokens_salida)
    col4.metric("💰 Costo texto", f"US$ {costo:.5f}" if costo is not None else "—")


def generar_iconos_para_sugerencias(sugerencias, cliente_imagen, one_shot):
    """Genera el ícono de cada sugerencia UNA sola vez y lo adjunta al dict.

    Se llama solo en el momento del análisis (no en cada re-render), porque
    Streamlit vuelve a ejecutar todo el script ante cualquier interacción
    (por ejemplo, tocar "Enviar" o "Descartar"): sin este cacheo, cada click
    volvería a facturar la generación de todas las imágenes de nuevo.

    Devuelve (sugerencias_con_icono, costo_total_imagenes).
    """
    costo_total = 0.0
    imagen_referencia = None
    if one_shot:
        imagen_referencia, costo_ref, error_ref = obtener_imagen_referencia(cliente_imagen)
        if error_ref:
            st.warning(f"No se pudo generar la imagen de referencia: {error_ref}")
        elif costo_ref is not None and "novum_costo_referencia_sumado" not in st.session_state:
            costo_total += costo_ref
            st.session_state["novum_costo_referencia_sumado"] = True

    sugerencias_con_icono = []
    for s in sugerencias:
        s = dict(s)
        concepto = s.get("concepto_visual", s.get("categoria", "otro"))
        with st.spinner("Generando ícono..."):
            if one_shot and imagen_referencia is not None:
                img, tiempo_img, costo_img, error_img = generar_imagen_one_shot(
                    cliente_imagen, concepto, imagen_referencia
                )
            else:
                img, tiempo_img, costo_img, error_img = generar_imagen_zero_shot(
                    cliente_imagen, concepto
                )
        s["icono_bytes"] = img
        s["icono_tiempo"] = tiempo_img
        s["icono_costo"] = costo_img
        s["icono_error"] = error_img
        if costo_img is not None:
            costo_total += costo_img
        sugerencias_con_icono.append(s)

    return sugerencias_con_icono, costo_total


def render_sugerencias(sugerencias, generar_iconos):
    """Muestra las sugerencias ya analizadas. No llama a ninguna API: los
    íconos, si corresponde, ya vienen generados de antemano."""
    if not sugerencias:
        st.info("No se detectó ninguna sugerencia concreta en el comentario.")
        return

    st.subheader(f"Sugerencias detectadas ({len(sugerencias)})")
    for i, s in enumerate(sugerencias):
        prioridad = s.get("prioridad", "media")
        categoria = s.get("categoria", "otro")
        area = s.get("area_responsable", "otro")
        color = PRIORIDAD_BADGE_COLOR.get(prioridad, "gray")
        icono_categoria = CATEGORIA_ICONO.get(categoria, "✨")
        icono_area = AREA_ICONO.get(area, "✨")

        with st.container(border=True, key=f"novum_sugerencia_{i}"):
            col_texto, col_imagen = st.columns([3, 1])
            with col_texto:
                st.markdown(
                    f":{color}-badge[Prioridad {prioridad}] "
                    f":gray-badge[{icono_categoria} {categoria.replace('_', ' ')}]"
                )
                st.markdown(f"**{s.get('descripcion', '')}**")
                st.caption(f"💡 Beneficio esperado: {s.get('beneficio_esperado', '')}")
                st.caption(f"{icono_area} Área responsable: {area.replace('_', ' ')}")

            with col_imagen:
                if generar_iconos:
                    if s.get("icono_error"):
                        st.warning(s["icono_error"])
                    elif s.get("icono_bytes") is not None:
                        st.image(s["icono_bytes"], use_container_width=True)
                        if s.get("icono_costo") is not None:
                            st.caption(f"💰 US$ {s['icono_costo']:.5f} · ⏱️ {s['icono_tiempo']:.1f}s")


def _texto_areas_involucradas(sugerencias):
    """Arma la frase 'el equipo de X' / 'los equipos de X, Y y Z'."""
    areas = []
    for s in sugerencias:
        nombre = AREA_NOMBRE.get(s.get("area_responsable"), "el área correspondiente")
        if nombre not in areas:
            areas.append(nombre)

    if not areas:
        return "el equipo correspondiente"
    if len(areas) == 1:
        return f"el equipo de {areas[0]}"
    return "los equipos de " + ", ".join(areas[:-1]) + f" y {areas[-1]}"


def render_gracias():
    """Pantalla de agradecimiento tras enviar un comentario."""
    st.markdown(
        """
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
        @keyframes novum-vuelo {
            0%   { transform: translate(-50%, 60px) rotate(-10deg); opacity: 0; }
            25%  { opacity: 1; }
            100% { transform: translate(-50%, -140px) rotate(12deg); opacity: 0; }
        }
        .novum-avion {
            position: relative;
            left: 50%;
            width: fit-content;
            font-size: 3rem;
            animation: novum-vuelo 1.8s ease-out forwards;
        }
        .novum-gracias-titulo {
            font-family: 'Poppins', sans-serif;
            font-weight: 600;
            font-size: 1.5rem;
            color: #7A4A00;
            text-align: center;
            margin-bottom: 0.5rem;
        }
        .novum-gracias-texto {
            font-family: 'Poppins', sans-serif;
            font-weight: 400;
            font-size: 1rem;
            color: #1F2937;
            text-align: center;
            margin: 0.2rem 0;
        }
        </style>
        <div class="novum-avion">✈️</div>
        """,
        unsafe_allow_html=True,
    )
    st.balloons()

    texto_areas = _texto_areas_involucradas(st.session_state.get("novum_ultimas_sugerencias", []))

    with st.container(key="novum_gracias_texto"):
        st.markdown(
            f"""
            <p class="novum-gracias-titulo">¡Gracias por compartir tu experiencia! 🚀</p>
            <p class="novum-gracias-texto">Cada aporte suma a una mejor experiencia de trabajo para todos. ⭐</p>
            <p class="novum-gracias-texto">Tu aporte ya forma parte de NOVUM y será analizado por {texto_areas}.</p>
            """,
            unsafe_allow_html=True,
        )

    col_izq, col_centro, col_der = st.columns([1, 2, 1])
    with col_centro:
        if st.button("✍️ Escribir un nuevo comentario", type="primary", use_container_width=True):
            st.session_state["novum_vista"] = "formulario"
            st.session_state.pop("novum_ultimas_sugerencias", None)
            st.rerun()


def render_titulo_novum():
    """Encabezado de marca (🔮 NOVUM + eslogan), reutilizado en cada vista."""
    st.markdown(
        f"""
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet">
        <p style="font-family:'Poppins', sans-serif; font-weight:600;
                  font-size:2rem; color:{COLOR_TITULO}; margin-bottom:0;">
            🔮 NOVUM
        </p>
        <p style="font-family:'Poppins', sans-serif; font-size:0.95rem;
                  color:{COLOR_TITULO}; opacity:0.85; margin-top:0.1rem;">
            Transformamos lo que pasa en oportunidades de mejora.
        </p>
        """,
        unsafe_allow_html=True,
    )


def render_login():
    """Pantalla de ingreso.

    El login con legajo y DNI queda preparado para una futura etapa (donde
    se sume una base de datos para hacer seguimiento del estado de cada
    sugerencia: leída, aceptada, en proceso). Por ahora no hay backend que
    valide esos datos, así que el único camino habilitado es "anónimo".
    """
    render_titulo_novum()

    st.subheader("Ingresar")
    with st.form("form_login"):
        st.text_input("Legajo")
        st.text_input("DNI")
        intento_login = st.form_submit_button("Ingresar")

    if intento_login:
        st.info(
            "El ingreso con legajo y DNI todavía no está disponible en esta "
            "versión. Por ahora, usá 'Ingresar como anónimo' para continuar."
        )

    st.divider()
    if st.button("Ingresar como anónimo"):
        st.session_state["novum_autenticado"] = True
        st.session_state["novum_usuario"] = "anonimo"
        st.rerun()


def render_app():
    config = render_sidebar()

    if st.session_state.get("novum_vista") == "gracias":
        render_gracias()
        return

    render_titulo_novum()

    st.markdown(
        f"""
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet">
        <p style="font-family:'Poppins', sans-serif; font-weight:500;
                  font-size:1.05rem; color:{COLOR_TITULO}; margin-bottom:0.1rem;">
            Tu experiencia puede ayudarnos a mejorar. ¿Qué querés compartir hoy?
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Puede ser una idea, una observación, una dificultad, un riesgo o "
        "una oportunidad de mejora."
    )
    comentario = st.text_area(
        "Comentario",
        label_visibility="collapsed",
        height=150,
        placeholder=(
            "Ej: En horas pico se genera mucho tránsito en el mismo pasillo "
            "que están trabajando los chicos de limpieza."
        ),
    )

    if st.button("🔎 Analizar comentario", type="primary"):
        if not config["groq_key"]:
            st.error("Falta la API key de Groq. Cargala en la barra lateral.")
        elif config["generar_iconos"] and not config["openai_key"]:
            st.error("Falta la API key de OpenAI, o desactivá 'Generar íconos con IA'.")
        elif not comentario.strip():
            st.warning("Escribí un comentario antes de analizar.")
        else:
            with st.spinner("Analizando comentario..."):
                respuesta, tiempo_respuesta, error = analizar_comentario(
                    config["groq_key"], config["modelo_texto"], config["temperatura"], comentario
                )

            if error:
                st.error(error)
            else:
                datos, sugerencias, contenido_invalido = parsear_sugerencias(respuesta)
                if contenido_invalido is not None:
                    st.error("El modelo no devolvió un JSON válido. Probá de nuevo o cambiá el modelo.")
                    with st.expander("Ver respuesta cruda"):
                        st.code(contenido_invalido)
                else:
                    costo_texto = calcular_costo_texto(config["modelo_texto"], respuesta)
                    costo_imagenes = 0.0
                    if config["generar_iconos"] and sugerencias:
                        cliente_imagen = OpenAI(api_key=config["openai_key"], timeout=60.0)
                        sugerencias, costo_imagenes = generar_iconos_para_sugerencias(
                            sugerencias, cliente_imagen, config["one_shot"]
                        )

                    st.session_state["novum_resultado"] = {
                        "datos": datos,
                        "sugerencias": sugerencias,
                        "costo_texto": costo_texto,
                        "costo_imagenes": costo_imagenes,
                        "tiempo_respuesta": tiempo_respuesta,
                        "tokens_entrada": respuesta.usage.prompt_tokens,
                        "tokens_salida": respuesta.usage.completion_tokens,
                        "generar_iconos": config["generar_iconos"],
                    }
                    st.rerun()

    resultado = st.session_state.get("novum_resultado")
    if not resultado:
        return

    st.divider()
    render_metricas_texto(
        resultado["tiempo_respuesta"],
        resultado["tokens_entrada"],
        resultado["tokens_salida"],
        resultado["costo_texto"],
    )
    st.divider()

    render_sugerencias(resultado["sugerencias"], resultado["generar_iconos"])

    if resultado["generar_iconos"]:
        st.divider()
        costo_total = (resultado["costo_texto"] or 0) + resultado["costo_imagenes"]
        st.metric("💰 Costo total de este análisis", f"US$ {costo_total:.5f}")

    with st.expander("Ver JSON crudo"):
        st.json(resultado["datos"])

    st.divider()
    col_enviar, col_descartar = st.columns(2)
    with col_enviar:
        if st.button("📨 Enviar comentario", type="primary", use_container_width=True):
            st.session_state["novum_ultimas_sugerencias"] = resultado["sugerencias"]
            st.session_state["novum_vista"] = "gracias"
            st.session_state.pop("novum_resultado", None)
            st.rerun()
    with col_descartar:
        if st.button("🗑️ Descartar comentario", use_container_width=True):
            st.session_state.pop("novum_resultado", None)
            st.rerun()


def main():
    st.set_page_config(page_title="NOVUM", page_icon="🔮", layout="centered")
    render_fondo()

    if not st.session_state.get("novum_autenticado"):
        render_login()
        return

    with st.sidebar:
        st.caption(f"👤 Sesión: {st.session_state.get('novum_usuario', 'anonimo')}")
        if st.button("Salir"):
            st.session_state["novum_autenticado"] = False
            st.rerun()
        st.divider()

    render_app()


if __name__ == "__main__":
    main()
