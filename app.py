# app.py
#
# NOVUM — punto de entrada de la app Streamlit.
# "Transformamos lo que pasa en oportunidades de mejora."
#
# Toma comentarios informales de empleados y los convierte en sugerencias de
# mejora estructuradas (texto-a-texto) más un ícono de apoyo generado por IA
# (texto-a-imagen) para cada sugerencia detectada.
#
# Estructura a implementar (Etapa 3, después de cerrar los prompts en la
# Etapa 2):
#
# 1. Config de página (st.set_page_config) + título "NOVUM" + eslogan
# 2. Sidebar:
#    - API key de Groq (texto-a-texto) y de OpenAI (texto-a-imagen),
#      cada una con fallback silencioso a st.secrets (nunca precargada en
#      el campo visible, para no exponerla en el HTML de una app pública)
#    - Selector de modelo de texto / parámetros
# 3. Textarea principal: comentario informal del empleado
# 4. Botón "Analizar comentario":
#    - Llamada a Groq (texto-a-texto) con el prompt definido en la Etapa 2
#      (zero-shot u one-shot, según lo que resulte mejor) + JSON Schema
#      estricto, incluyendo un campo de concepto visual por sugerencia
#    - Para cada sugerencia: llamada a OpenAI (texto-a-imagen,
#      gpt-image-1-mini) usando ese concepto visual, para generar un ícono
#      de apoyo simple y consistente en estilo
#    - Manejo de errores de ambas APIs
#    - Métricas: tiempo, tokens, costo estimado por análisis
#    - Render de cada sugerencia con su ícono
