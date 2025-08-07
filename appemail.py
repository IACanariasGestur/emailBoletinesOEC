# -*- coding: utf-8 -*-

import streamlit as st
from datetime import datetime, timedelta, date
import pytz
import locale
import unicodedata
import pandas as pd
import feedparser
import requests
from dateutil import parser as date_parser
import fitz  # PyMuPDF
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ----------- CONFIGURACIÓN DE EMAIL -----------

REMITENTE = "canariasgestur@gmail.com"
CLAVE_APP = "tvru npfu kmov xngk"

# ----------- FUNCIONES AUXILIARES -----------

try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')
    except:
        pass

def formatear_fecha_es(fecha):
    meses = {
        "January": "ENERO", "February": "FEBRERO", "March": "MARZO", "April": "ABRIL",
        "May": "MAYO", "June": "JUNIO", "July": "JULIO", "August": "AGOSTO",
        "September": "SEPTIEMBRE", "October": "OCTUBRE", "November": "NOVIEMBRE", "December": "DICIEMBRE"
    }
    fecha_en = fecha.strftime("%-d de %B de %Y")
    for en, es in meses.items():
        if en in fecha_en:
            return fecha_en.replace(en, es).upper()
    return fecha_en.upper()

def normalizar(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', texto)
        if not unicodedata.combining(c)
    ).lower()

def extraer_bloques_sumario(lineas):
    patron = re.compile(r'^\d{6}\s+.+')
    bloques = []
    bloque_actual = ""
    for linea in lineas:
        linea = linea.strip()
        if patron.match(linea):
            if bloque_actual:
                bloques.append(bloque_actual.strip())
            bloque_actual = linea
        else:
            if bloque_actual:
                bloque_actual += " " + linea
    if bloque_actual:
        bloques.append(bloque_actual.strip())
    return bloques

def calcular_numero_boc(fecha_objetivo, base_fecha=date(2025, 1, 2), base_numero=1):
    if fecha_objetivo < base_fecha:
        raise ValueError("Fecha anterior a la base.")
    actual = base_fecha
    numero_boc = base_numero
    while actual < fecha_objetivo:
        if actual.weekday() < 5:
            numero_boc += 1
        actual += timedelta(days=1)
    if fecha_objetivo.weekday() >= 5:
        while fecha_objetivo.weekday() >= 5:
            fecha_objetivo -= timedelta(days=1)
        return calcular_numero_boc(fecha_objetivo, base_fecha, base_numero)
    return numero_boc

def calcular_fecha_desde_numero_boc(numero_objetivo, base_fecha=date(2025, 1, 2), base_numero=1):
    actual = base_fecha
    numero_actual = base_numero
    while numero_actual < numero_objetivo:
        if actual.weekday() < 5:
            numero_actual += 1
        actual += timedelta(days=1)
    return actual

def generar_html_resumen(documentos):
    emojis = {
        "BOE": "🟥",
        "BOC": "⬜",
        "BOP LP": "🟡",
        "BOP SCTF": "🔵"
    }
    html = "<h2>📋 Resumen de anuncios encontrados</h2><ul>"
    for doc in documentos:
        emoji = emojis.get(doc['boletin'], "📄")
        resumen = doc.get('resumen', '')
        if doc['boletin'] == 'BOE':
            resumen = re.sub(r'\s*-?\s*Referencia:.*?(?=<|$)', '', resumen)
            resumen = re.sub(r'\s*-?\s*KBytes:.*?(?=<|$)', '', resumen)
            resumen = re.sub(r'\s*-?\s*P[áa]ginas:.*?(?=<|$)', '', resumen)
        html += f"""
            <li>
                <strong>{emoji} {doc['boletin']}</strong> - {doc['fecha']}<br>
                <a href="{doc['url']}" target="_blank">{doc['titulo']}</a><br>
                <em>{resumen.strip()}</em>
            </li><br>
        """
    html += "</ul>"
    return html

def obtener_documentos(hoy, tz_madrid, keywords_normalizadas, exclude_keywords_normalizadas):
    rss_url = 'https://www.boe.es/rss/boe.php'
    feed = feedparser.parse(rss_url)
    documentos = []
    comunidades_excluir = [normalizar(x) for x in [
        "andalucía", "aragón", "asturias", "cantabria", "castilla-la mancha", "castilla y león",
        "cataluña", "catalunya", "ceuta", "comunidad de madrid", "comunidad foral de navarra",
        "comunidad valenciana", "comunitat valenciana", "extremadura", "galicia", "islas baleares",
        "la rioja", "melilla", "murcia", "navarra", "país vasco", "euskadi", "rioja", "Illes Balears",
    ]]
    for entry in feed.entries:
        try:
            fecha_pub = date_parser.parse(entry.published).astimezone(tz_madrid).date()
        except:
            continue
        texto = normalizar(entry.title + " " + entry.get("description", ""))
        descripcion = normalizar(entry.get("description", ""))
        if (
            fecha_pub == hoy and
            any(k in texto for k in keywords_normalizadas) and
            not any(x in texto for x in exclude_keywords_normalizadas) and
            not any(c in descripcion for c in comunidades_excluir)
        ):
            documentos.append({
                "boletin": "BOE",
                "titulo": entry.title,
                "url": entry.link,
                "fecha": fecha_pub.strftime('%Y-%m-%d'),
                "resumen": f"Sección: {entry.get('description', '')}"
            })
    return documentos

def obtener_documentos_boc_pdf(hoy_canarias, anio_actual, keywords_normalizadas, exclude_keywords_normalizadas, tz_canarias):
    documentos = []
    for offset in [0]:
        fecha_prueba = hoy_canarias + timedelta(days=offset)
        try:
            numero = calcular_numero_boc(fecha_prueba)
            url_pdf = f"https://sede.gobiernodecanarias.org/boc/boc-s-{anio_actual}-{numero}.pdf"
            res = requests.get(url_pdf, timeout=10)
            res.raise_for_status()
            if not res.content.startswith(b"%PDF"):
                continue
            doc = fitz.open(stream=res.content, filetype="pdf")
            fecha_real = calcular_fecha_desde_numero_boc(numero)
            bloques = [
                b[4].strip().replace("\n", " ")
                for p in doc
                for b in p.get_text("blocks")
                if len(b[4].strip()) >= 30
            ]
            for texto in bloques:
                texto_norm = normalizar(texto)
                if any(kw in texto_norm for kw in keywords_normalizadas) and not any(ex in texto_norm for ex in exclude_keywords_normalizadas):
                    documentos.append({
                        "boletin": "BOC",
                        "titulo": " ".join(texto.split()[:200]).upper(),
                        "url": url_pdf,
                        "fecha": fecha_real.strftime('%Y-%m-%d'),
                        "resumen": "(Extraído de PDF)",
                        "contenido": texto
                    })
        except Exception as e:
            continue
    return documentos

def obtener_documentos_bop_generico(nombre_bop, url_funcion, max_paginas, hoy_canarias, keywords_normalizadas, exclude_keywords_normalizadas):
    documentos = []
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.bopsantacruzdetenerife.es/",
        "Accept": "application/pdf"
    }
    for i in range(8):
        fecha = hoy_canarias + timedelta(days=i)
        url_pdf = url_funcion(fecha)
        try:
            res = session.get(url_pdf, headers=headers, timeout=10)
            res.raise_for_status()
            if not res.content.startswith(b"%PDF"):
                continue
            doc = fitz.open(stream=res.content, filetype="pdf")
            texto = "\n".join([doc[i].get_text() for i in range(min(max_paginas, len(doc)))])
            bloques = extraer_bloques_sumario(texto.splitlines())
            for texto in bloques:
                if "....." in texto:
                    texto = texto.split(".....")[0].strip()
                texto_norm = normalizar(texto)
                if (
                    any(kw in texto_norm for kw in keywords_normalizadas)
                    and not any(ex in texto_norm for ex in exclude_keywords_normalizadas)
                ):
                    documentos.append({
                        "boletin": nombre_bop,
                        "titulo": texto.upper(),
                        "url": url_pdf,
                        "fecha": fecha.strftime('%Y-%m-%d'),
                        "resumen": f"(Sumario {nombre_bop})"
                    })
            if documentos:
                break
        except Exception as e:
            continue
    return documentos

def obtener_documentos_bop_lp(hoy_canarias, keywords_normalizadas, exclude_keywords_normalizadas):
    documentos = []
    for i in range(5):
        fecha = hoy_canarias + timedelta(days=i)
        d = str(fecha.day)
        m = f"{fecha.month:02d}"
        a = str(fecha.year)[-2:]
        carpeta = f"{d}-{m}-{a}"
        url_pdf = f"https://www.boplaspalmas.net/boletines/{fecha.year}/{carpeta}/{carpeta}.pdf"
        try:
            res = requests.get(url_pdf, timeout=10)
            res.raise_for_status()
            doc = fitz.open(stream=res.content, filetype="pdf")
            texto = "\n".join([
                re.sub(r'\s+', ' ', doc[j].get_text().strip())
                for j in range(min(3, len(doc)))
            ])
            bloques = re.split(r'\n{2,}|(?=\d{6}\s)', texto)
            for bloque in bloques:
                bloque = bloque.strip()
                if len(bloque) >= 30:
                    texto_normalizado = normalizar(bloque)
                    if (
                        any(re.search(rf"\b{re.escape(kw)}\b", texto_normalizado) for kw in keywords_normalizadas)
                        and not any(ex in texto_normalizado for ex in exclude_keywords_normalizadas)
                    ):
                        documentos.append({
                            "boletin": "BOP LP",
                            "titulo": re.split(r"\.{5,}", bloque)[0].strip()[:200].upper(),
                            "url": url_pdf,
                            "fecha": fecha.strftime('%Y-%m-%d'),
                            "resumen": "(Detectado en texto libre)",
                            "contenido": bloque
                        })
            if documentos:
                break
        except Exception as e:
            continue
    return documentos

def obtener_documentos_bop_sctf(hoy_canarias, keywords_normalizadas, exclude_keywords_normalizadas):
    def url_generator(fecha):
        return f"https://www.bopsantacruzdetenerife.es/boletines/{fecha.strftime('%Y/%-d-%-m-%y')}/{fecha.strftime('%-d-%-m-%y')}.pdf"
    return obtener_documentos_bop_generico("BOP SCTF", url_generator, 4, hoy_canarias, keywords_normalizadas, exclude_keywords_normalizadas)

# ----------- ENVÍO DE EMAIL -----------

def enviar_email_resumen(documentos, remitente, clave_app, destinatarios, cuerpo_html, fecha_formateada_larga):
    asunto = f"📰 Resumen boletines {fecha_formateada_larga}"
    mensaje = MIMEMultipart("alternative")
    mensaje["Subject"] = asunto
    mensaje["From"] = remitente
    mensaje["To"] = ", ".join(destinatarios)
    parte_html = MIMEText(cuerpo_html, "html", "utf-8")
    mensaje.attach(parte_html)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
            servidor.login(remitente, clave_app)
            servidor.sendmail(remitente, destinatarios, mensaje.as_string())
        return True, "✅ Correo enviado con éxito."
    except Exception as e:
        return False, f"❌ Error al enviar el correo: {e}"

# ----------- STREAMLIT APP -----------

st.set_page_config(page_title="Newsletter boletines/OEC", layout="wide")

st.title("🗄️ ANUNCIOS EN BOLETINES OFICIALES")
st.info("Busca legislación y anuncios relevantes en BOE, BOC, BOP Las Palmas y BOP SC de Tenerife.\n\n"
        "Puedes ajustar destinatarios y palabras clave antes de buscar.")

# ====== PARÁMETROS Y ESTADO ======

default_keywords = [
    "Fondos Next Generation", "Ayudas", "Subvención", "Subvenciones",
    "Extracto", "Energía", "Biodiversidad", "Economía circular", "Cambio climático",
    "Life", "FEDER", "IDAE", "Plan de Recuperación, Transformación y Resiliencia",
    "Instalación fotovoltaica", "sector náutico", "descarbonización", "eléctrico",
    "vehículo",
]

default_exclude_keywords = ["empleo", "volcán"]

if "keywords" not in st.session_state:
    st.session_state.keywords = default_keywords.copy()

if "exclude_keywords" not in st.session_state:
    st.session_state.exclude_keywords = default_exclude_keywords.copy()

if "destinatarios" not in st.session_state:
    st.session_state.destinatarios = ["srodriguez@oficinasenergia.es", "mhenriquez@oficinasenergia.es", "aherrera@oficinasverdes.es"]

# ----------- SECCIÓN DE PALABRAS CLAVE -----------

st.subheader("🔑 Palabras clave para filtrar anuncios")
st.caption("Puedes añadir nuevas palabras clave o eliminar las existentes.")

cols = st.columns([2, 1])

with cols[0]:
    new_keyword = st.text_input("Añadir nueva palabra clave", "")
    if st.button("Añadir palabra clave"):
        if new_keyword and new_keyword not in st.session_state.keywords:
            st.session_state.keywords.append(new_keyword)
            st.success(f"Palabra clave '{new_keyword}' añadida.")
        elif not new_keyword:
            st.warning("Introduce un texto para añadir.")
        else:
            st.warning("Esa palabra clave ya está en la lista.")

with cols[1]:
    kw_to_remove = st.selectbox("Eliminar palabra clave", options=[""] + st.session_state.keywords)
    if st.button("Eliminar seleccionada"):
        if kw_to_remove and kw_to_remove in st.session_state.keywords:
            st.session_state.keywords.remove(kw_to_remove)
            st.info(f"Palabra clave '{kw_to_remove}' eliminada.")

st.write("**Palabras clave activas:**")
st.write(", ".join(st.session_state.keywords))

# ----------- SECCIÓN DE PALABRAS A EXCLUIR -----------

st.subheader("🚫 Palabras clave para EXCLUIR anuncios")
st.caption("Los anuncios que contengan alguna de estas palabras serán ignorados.")

cols_ex = st.columns([2, 1])

with cols_ex[0]:
    new_exclude = st.text_input("Añadir nueva palabra a excluir", "")
    if st.button("Añadir palabra a excluir"):
        if new_exclude and new_exclude not in st.session_state.exclude_keywords:
            st.session_state.exclude_keywords.append(new_exclude)
            st.success(f"Palabra '{new_exclude}' añadida a exclusiones.")
        elif not new_exclude:
            st.warning("Introduce un texto para añadir.")
        else:
            st.warning("Esa palabra ya está en la lista de exclusiones.")

with cols_ex[1]:
    ex_to_remove = st.selectbox("Eliminar palabra de exclusión", options=[""] + st.session_state.exclude_keywords)
    if st.button("Eliminar palabra excluida"):
        if ex_to_remove and ex_to_remove in st.session_state.exclude_keywords:
            st.session_state.exclude_keywords.remove(ex_to_remove)
            st.info(f"Palabra '{ex_to_remove}' eliminada de exclusiones.")

st.write("**Palabras clave excluidas activas:**")
st.write(", ".join(st.session_state.exclude_keywords))

# ----------- SECCIÓN DE DESTINATARIOS -----------

st.subheader("📧 Destinatarios del email resumen")
st.caption("Puedes añadir o quitar destinatarios. (El primero es el predeterminado)")

with st.expander("Editar destinatarios"):
    new_email = st.text_input("Añadir destinatario", "")
    if st.button("Añadir destinatario"):
        if new_email and new_email not in st.session_state.destinatarios:
            st.session_state.destinatarios.append(new_email)
            st.success(f"Destinatario '{new_email}' añadido.")
        elif not new_email:
            st.warning("Introduce un email válido.")
        else:
            st.warning("Ese destinatario ya está en la lista.")
    email_to_remove = st.selectbox("Eliminar destinatario", options=[""] + st.session_state.destinatarios)
    if st.button("Eliminar destinatario"):
        if email_to_remove and email_to_remove in st.session_state.destinatarios:
            st.session_state.destinatarios.remove(email_to_remove)
            st.info(f"Destinatario '{email_to_remove}' eliminado.")

st.write("**Destinatarios actuales:**")
st.write(", ".join(st.session_state.destinatarios))

# ----------- FECHA Y ZONAS HORARIAS -----------

tz_madrid = pytz.timezone("Europe/Madrid")
tz_canarias = pytz.timezone("Atlantic/Canary")
hoy = datetime.now(tz_madrid).date()
hoy_canarias = datetime.now(tz_canarias).date()
anio_actual = hoy_canarias.year
fecha_formateada = hoy.strftime("%d/%m/%Y")
fecha_formateada_larga = formatear_fecha_es(hoy_canarias)

# ----------- BOTÓN DE BÚSQUEDA Y RESULTADOS -----------

st.markdown("---")
st.header("🔎 BUSCAR ANUNCIOS")

if st.button("Buscar boletines oficiales"):
    with st.spinner("Buscando y analizando boletines... esto puede tardar unos segundos ⏳"):
        keywords_normalizadas = [normalizar(kw) for kw in st.session_state.keywords]
        exclude_keywords_normalizadas = [normalizar(kw) for kw in st.session_state.exclude_keywords]

        docs_boe = obtener_documentos(hoy, tz_madrid, keywords_normalizadas, exclude_keywords_normalizadas)
        docs_boc = obtener_documentos_boc_pdf(hoy_canarias, anio_actual, keywords_normalizadas, exclude_keywords_normalizadas, tz_canarias)
        docs_bop_lp = obtener_documentos_bop_lp(hoy_canarias, keywords_normalizadas, exclude_keywords_normalizadas)
        docs_bop_sctf = obtener_documentos_bop_sctf(hoy_canarias, keywords_normalizadas, exclude_keywords_normalizadas)

        documentos = docs_boe + docs_boc + docs_bop_lp + docs_bop_sctf
        st.session_state.resultados = documentos

    if documentos:
        st.success(f"Encontradas {len(documentos)} coincidencia(s) para el {fecha_formateada}.")
        tabla = []
        for d in documentos:
            tab = {k: v for k, v in d.items() if k in ["boletin", "fecha", "titulo", "url", "resumen"]}
            tabla.append(tab)
        df = pd.DataFrame(tabla)
        st.dataframe(df, use_container_width=True)
    else:
        st.warning(f"No se encontraron publicaciones relevantes para el {fecha_formateada}.")
        st.session_state.resultados = []
else:
    if "resultados" in st.session_state and st.session_state.resultados:
        st.dataframe(
            pd.DataFrame([
                {k: v for k, v in d.items() if k in ["boletin", "fecha", "titulo", "url", "resumen"]}
                for d in st.session_state.resultados
            ]), use_container_width=True
        )

# ----------- ENVÍO DE EMAIL -----------

st.markdown("---")
st.header("✉️ ENVIAR POR EMAIL")

if "resultados" in st.session_state and st.session_state.resultados:
    if st.button("Enviar resumen"):
        cuerpo_html = generar_html_resumen(st.session_state.resultados)
        with st.spinner("Enviando email..."):
            ok, mensaje = enviar_email_resumen(
                st.session_state.resultados,
                REMITENTE,
                CLAVE_APP,
                st.session_state.destinatarios,
                cuerpo_html,
                fecha_formateada_larga
            )
            if ok:
                st.success(mensaje)
            else:
                st.error(mensaje)
else:
    st.info("Realiza primero una búsqueda de boletines para poder enviar el resumen por email.")

st.info("Desarrollado por JCastro / ©2025")
