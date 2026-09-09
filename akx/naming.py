"""
Limpieza y normalización de nombres de archivo: quitar ruido de YouTube
("Official Video", IDs, hashtags, emojis…) y reordenar "Canción | Artista"
a "Artista - Canción" cuando el ID3 confirma quién es el artista.

Todo acá es lógica pura (sin I/O) — candidata natural a tests unitarios.
"""
from __future__ import annotations

import re
import unicodedata as _ud
from pathlib import Path


# ---------- Limpieza de nombres ----------
# 0) Normalización de caracteres "raros" que YouTube usa cuando el título
#    original tendría caracteres prohibidos en nombres de archivo.
#    Por ejemplo, YouTube reemplaza | por ｜ (full-width), " por ＂, etc.
#    Antes de aplicar regex, los volvemos a sus formas estándar.
_FULLWIDTH_TRANSLATIONS = str.maketrans({
    '｜': '|',   # full-width pipe (U+FF5C) → pipe normal
    '＂': '"',   # full-width quotation mark (U+FF02)
    '＇': "'",   # full-width apostrophe
    '：': ':',   # full-width colon
    '／': '/',
    '＼': '\\',
    '＊': '*',
    '？': '?',
    '＜': '<',
    '＞': '>',
    '\u200B': '',  # zero-width space (a veces YouTube los incluye)
    '\u200C': '',  # zero-width non-joiner
    '\u200D': '',  # zero-width joiner (sin función estética para nombres)
})

# 1) ID de YouTube al final: " [dQw4w9WgXcQ]" o " (dQw4w9WgXcQ)"
_RE_YT_ID = re.compile(r"\s*[\[\(][A-Za-z0-9_-]{11}[\]\)]\s*$")

# 2) Términos de "ruido" que aparecen entre paréntesis o corchetes.
#    Pegados todos en un solo grupo grande para aplicar un solo regex eficientemente.
_NOISE_TERMS = (
    # Versión oficial
    r"official\s*(?:hd\s*)?(?:music\s*)?(?:video|audio|lyric(?:s)?\s*video|visualizer|version)",
    r"v[íi]deo\s*o?ficial(?:\s*hd)?",
    r"v[íi]deo\s*musical(?:\s*o?ficial)?",
    r"v[íi]deo\s*clip(?:\s*o?ficial)?",
    r"video\s*clip(?:\s*o?ficial)?",
    r"videoclip(?:\s*o?ficial)?",       # NUEVO: sin espacio
    r"videolyric(?:\s*o?ficial)?",      # NUEVO: VIDEOLYRIC OFICIAL
    r"video\s*lyric(?:\s*o?ficial)?",   # NUEVO
    r"clip\s*musical(?:\s*o?ficial)?",
    r"audio\s*o?ficial",
    r"clip\s*o?ficial",
    r"v[íi]deo(?:\s*con\s*letra(?:s)?)?",
    r"video(?:\s*with\s*lyrics)?",
    # Lyrics / letra
    r"lyric(?:s)?(?:\s*video)?",
    r"con\s*letra(?:s)?",
    r"letra(?:s)?(?:\s*o?ficial)?",
    r"with\s*lyrics(?:\s*on\s*screen)?",
    r"lyrics?\s*on\s*screen",
    r"sub(?:t[íi]tulado|titulada)(?:s)?(?:\s*(?:al\s*)?espa[nñ]ol|\s*ingl[eé]s)?",
    r"subtitled",
    # Calidad
    r"hd\s*(?:music\s*)?(?:video|audio)?",
    r"hq|4k|2k|8k|1080p?|720p?|480p?",
    r"in\s*hd",
    r"en\s*hd",
    # Genérico
    r"(?:music\s*)?video|(?:music\s*)?audio|m[uú]sica",
    # Versiones / mezclas
    r"radio\s*(?:edit|version|cut)",
    r"extended\s*(?:version|mix|cut)",
    r"album\s*version",
    r"single\s*version",
    r"original\s*(?:version|mix)",
    r"clean\s*version",
    r"explicit\s*version",
    r"piano\s*version",
    r"unplugged",
    r"remastered(?:\s*\d{4})?",
    r"\d{4}\s*remaster(?:ed)?",
    # Estilos virales
    r"slowed(?:\s*\+\s*reverb)?(?:\s*and\s*reverb)?",
    r"sped\s*up",
    r"nightcore(?:\s*version)?",
    r"reverb",
    # Karaoke / instrumental
    r"karaoke(?:\s*version)?",
    r"instrumental(?:\s*version)?",
    # Audio only
    r"audio\s*only",
    r"solo\s*audio",
    r"full\s*song",
    r"completa",
    # Topic auto-channel
    r"auto-?generated\s*by\s*youtube",
)
_RE_NOISE_PARENS = re.compile(
    r"\s*[\(\[]\s*(?:" + "|".join(_NOISE_TERMS) + r")\s*[\)\]]",
    re.IGNORECASE,
)

# 3) Ruido al FINAL del título precedido por separador (| - · /):
#    "Cancion | Video Oficial HD" → "Cancion"
#    Permite también un | suelto al final ("Cancion | VIDEO OFICIAL |")
_RE_TRAILING_PIPE_NOISE = re.compile(
    r"\s+(?:[\|\-·/]|I)\s+(?i:"
    + "|".join(_NOISE_TERMS) +
    r")(?:\s+(?:hd|hq|4k|2k|1080p?|720p?))*\s*\|?\s*$",
    re.IGNORECASE,
)

# 4) Emojis y símbolos especiales al final (❤️🎵🔥✨ etc.)
_RE_TRAILING_EMOJIS = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF"
    r"\u2600-\u27BF\uFE0F]+\s*$"
)

# 5) Hashtags al final: " #musica #pop"
_RE_TRAILING_HASHTAGS = re.compile(r"(?:\s+#\w+)+\s*$")

# 6) "prod. by ARTISTA", "(prod. by X)", "[Prod. X]", "(Prod. por X)"
_RE_PROD_BY = re.compile(
    r"\s*[\(\[\{]?\s*prod(?:uced)?(?:\.|\s)\s*(?:by|por)?\s*[^()\[\]\{\}]*[\)\]\}]?\s*$",
    re.IGNORECASE,
)

# 7) Separadores residuales al inicio y final
_RE_TRAILING_SEP = re.compile(r"[\s\-\|·,;]+$")
_RE_LEADING_SEP  = re.compile(r"^[\s\-\|·,;]+")

# Conservamos a propósito (no se borran):
#   feat. / ft. / featuring     → autor secundario importante
#   (Live), (Acoustic), (Acústico), (Remix) → variantes que el usuario querría distinguir
#   (Explicit)                  → marca de contenido
# Estas no entran en _NOISE_TERMS.


def clean_title(name: str) -> str:
    if not name:
        return name

    # 0) Normalizar caracteres full-width a sus equivalentes ASCII
    s = name.translate(_FULLWIDTH_TRANSLATIONS)

    # 1) Quitar ID de YouTube al final
    s = _RE_YT_ID.sub("", s)

    # 2) Hashtags y emojis al final
    s = _RE_TRAILING_HASHTAGS.sub("", s)
    s = _RE_TRAILING_EMOJIS.sub("", s)

    # 3) Aplicar regex de paréntesis varias veces (puede haber anidados/seguidos)
    for _ in range(6):
        prev = s
        s = _RE_NOISE_PARENS.sub("", s)
        if prev == s:
            break

    # 4) Ruido al final precedido por separador
    s = _RE_TRAILING_PIPE_NOISE.sub("", s)

    # 5) Prod. by / Prod. por
    s = _RE_PROD_BY.sub("", s)

    # 6) Quitar marcadores de calidad sueltos al final ("...HD", "... 4K", "... 1080p")
    s = re.sub(r"\s+(?:hd|hq|4k|2k|8k|1080p?|720p?|480p?)\s*\|?\s*$", "",
               s, flags=re.IGNORECASE)

    # 7) Limpieza final
    s = re.sub(r"\s+", " ", s).strip()
    s = _RE_TRAILING_SEP.sub("", s).strip()
    s = _RE_LEADING_SEP.sub("", s).strip()

    # Limpieza de paréntesis vacíos que pudieran quedar: "(  )", "[]"
    s = re.sub(r"\s*[\(\[]\s*[\)\]]\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _RE_TRAILING_SEP.sub("", s).strip()

    return s or name


def clean_filename(filename: str) -> str:
    p = Path(filename)
    return clean_title(p.stem) + p.suffix


# ---------- Limpieza con metadata de yt-dlp ----------
# Caracteres prohibidos en nombres de archivo Windows (los más restrictivos)
_RE_BAD_FN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')

def sanitize_filename_part(s: str) -> str:
    """Limpia un fragmento (artista o título) para usar como nombre de archivo."""
    if not s:
        return ""
    s = _RE_BAD_FN_CHARS.sub("", s)
    # Colapsa espacios y trim
    s = re.sub(r"\s+", " ", s).strip()
    # Quita puntos al final (Windows no los permite)
    s = s.rstrip(". ")
    return s


def build_name_from_metadata(info: dict) -> str | None:
    """
    Intenta construir 'Artista - Título' desde los campos que entrega yt-dlp.
    Devuelve None si no hay datos suficientemente buenos.

    yt-dlp completa estos campos cuando puede (especialmente en YouTube Music):
      - artist, track:        cuando el video tiene metadata musical
      - creator:              fallback para autor
      - title:                siempre presente
      - uploader:             nombre del canal (último recurso)
    """
    if not info:
        return None

    artist = (info.get("artist")
              or info.get("creator")
              or info.get("composer"))
    track  = info.get("track")
    title  = info.get("title")

    artist = sanitize_filename_part(artist or "")
    track  = sanitize_filename_part(track or "")
    title  = sanitize_filename_part(title or "")

    # Caso 1: tenemos artist + track explícitos (ideal — viene de YouTube Music)
    if artist and track:
        return f"{artist} - {track}"

    # Caso 2: tenemos artist y el título contiene al artist al inicio: usar tal cual
    # Caso 3: tenemos artist solo: usar artist + title limpio
    if artist and title:
        # Limpiar el título normal por si tiene "Official Video" etc.
        clean = clean_title(title)
        # Si el clean ya empieza con "Artist - ", devolverlo así
        if clean.lower().startswith(artist.lower() + " - ") or \
           clean.lower().startswith(artist.lower() + " – "):
            return clean
        # Si el título es exactamente el artista, evitar "Artista - Artista"
        if clean.lower() == artist.lower():
            return clean
        return f"{artist} - {clean}"

    # Caso 4: solo título. Limpiarlo con regex tradicional.
    if title:
        return clean_title(title)

    return None


# ---------- Reordenamiento "Título | Artista" → "Artista - Título" ----------
# Sufijos típicos de canales de YouTube que NO son parte del nombre artístico.
# CycloMusic → Cyclo, ZarcortGame → Zarcort, AdeleVEVO → Adele, etc.
_CHANNEL_SUFFIXES = (
    "vevo", "official", "officiel", "oficial", "music", "musica", "música",
    "topic", "tv", "channel", "canal", "game", "games", "gaming",
    "tube", "media", "records", "studio", "studios",
)


def _norm_for_compare(s: str) -> str:
    """Normaliza un nombre para comparación: sin acentos, lowercase, sin separadores."""
    if not s:
        return ""
    s = _ud.normalize("NFKD", s)
    s = "".join(c for c in s if not _ud.combining(c))
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_channel_suffix_norm(name: str) -> str:
    """Versión normalizada del nombre, con sufijo de canal removido."""
    n = _norm_for_compare(name)
    for suffix in _CHANNEL_SUFFIXES:
        if n.endswith(suffix) and len(n) > len(suffix) + 1:
            stripped = n[:-len(suffix)].strip()
            if stripped:
                return stripped
        if n.endswith(" " + suffix):
            return n[:-len(suffix)-1].strip()
    return n


def _clean_channel_name(artist_meta: str) -> str:
    """Quita sufijo de canal preservando capitalización: 'CycloMusic' → 'Cyclo'."""
    if not artist_meta:
        return ""
    lower = artist_meta.lower()
    for suffix in _CHANNEL_SUFFIXES:
        if lower.endswith(suffix) and len(artist_meta) > len(suffix) + 1:
            return artist_meta[:-len(suffix)].rstrip(" -_")
        if lower.endswith(" " + suffix):
            return artist_meta[:-len(suffix)-1].rstrip()
    return artist_meta


def _is_artist_match_strict(side: str, artist: str) -> bool:
    """
    True si `side` ES el artista (no que solo lo contenga). Ejemplos:
      side="Piter-G",          artist="Piter-G"           → True (exacto)
      side="Cyclo",            artist="CycloMusic"        → True (subcadena del artista limpio)
      side="Cyclo ft. Kronno", artist="CycloMusic"        → True (artist + conector ft.)
      side="ZARCORT Y TOWN",   artist="ZarcortGame"       → True ("y" es conector de colaboración)
      side="Zarcort, Piter-G", artist="ZarcortGame"       → True ("," es conector)
    """
    if not side or not artist:
        return False
    side_norm = _norm_for_compare(side)
    artist_norm = _norm_for_compare(artist)
    artist_clean = _strip_channel_suffix_norm(artist)
    if not side_norm or not artist_norm:
        return False

    # Match exacto (con o sin sufijo de canal)
    if side_norm == artist_norm or side_norm == artist_clean:
        return True

    # El side empieza con el artista Y luego viene un conector de colaboración.
    # Conectores aceptados:
    #   ft. / feat. / featuring / & / , / con / y / e / x / +
    # ("y" en español, "e" como variante ante palabras con I-, "x" en hip-hop)
    CONNECTORS = r"(ft\.?|feat\.?|featuring|&|,|con\b|y\b|e\b|x\b|\+)"
    for art_variant in (artist_norm, artist_clean):
        if not art_variant:
            continue
        if side_norm.startswith(art_variant):
            rest = side_norm[len(art_variant):].strip()
            if not rest:
                return True
            if re.match(rf"^{CONNECTORS}\s", rest):
                return True

    # El side es subcadena del artista (caso "Cyclo" en "CycloMusic" después
    # de quitar sufijo). Solo si el side tiene al menos 4 chars (evita
    # fragmentos demasiado cortos que matchearían cualquier cosa).
    if len(side_norm) >= 4 and side_norm in artist_clean:
        return True

    return False


def reorder_to_artist_first(stem: str, artist_meta: str | None) -> tuple[str, bool]:
    """
    Si el stem tiene formato 'Canción | Artista' o 'Canción - Artista' y el
    artista del ID3 confirma que el lado derecho ES el artista (y el izquierdo
    NO lo es), reordena a 'Artista - Canción'.

    Devuelve (nuevo_stem, fue_reordenado).
    Si no hay nada que reordenar, devuelve (stem_original, False).

    Reglas de seguridad:
    - Solo procesa stems con UN solo separador (' | ' o ' - ').
      Stems con 2+ separadores son ambiguos y no se tocan.
    - El lado derecho debe matchear ESTRICTAMENTE el artista (no solo contenerlo).
    - Si el lado izquierdo ya es el artista, no se reordena (ya está bien).
    """
    if not stem or not artist_meta:
        return stem, False

    # Normalizar separador `|`: a veces YouTube deja "RAP| Artista" o
    # "Cancion |Artista" sin espacio en uno de los lados. Le agregamos
    # los espacios faltantes para que el split funcione consistentemente.
    normalized = re.sub(r"(\S)\|(\s)", r"\1 |\2", stem)        # "RAP| X" → "RAP | X"
    normalized = re.sub(r"(\s)\|(\S)", r"\1| \2", normalized)  # "X |RAP" → "X | RAP"
    normalized = re.sub(r"(\S)\|(\S)", r"\1 | \2", normalized)  # "X|Y" → "X | Y"

    SEPARATORS = [" | ", " - "]
    for sep in SEPARATORS:
        # Solo nombres con exactamente 1 separador
        if normalized.count(sep) != 1:
            continue
        left, right = normalized.split(sep, 1)
        left = left.strip()
        right = right.strip()
        if not left or not right:
            continue

        left_is_artist  = _is_artist_match_strict(left, artist_meta)
        right_is_artist = _is_artist_match_strict(right, artist_meta)

        # Si el izquierdo ya es el artista, no reordenar (pero sí devolvemos
        # el normalized por si arregló el espacio del separador)
        if left_is_artist:
            return normalized, normalized != stem
        # Si el derecho es estrictamente el artista, reordenar
        if right_is_artist and not left_is_artist:
            # Usar el "right" tal cual lo escribió el usuario en el archivo
            # (preserva mayúsculas/minúsculas y caracteres especiales).
            return f"{right} - {left}", True

    # Si no hubo reorder pero sí normalización del separador, devolver eso
    return normalized, normalized != stem
