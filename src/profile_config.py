"""Profile-aware configuration helpers for Cozy Kids Launcher."""

import copy
import json
import os
import re
import uuid


DEFAULT_PROFILE_ID = "default"
MAX_PROFILES = 20
PROFILE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
PROFILE_FIELDS = (
    "name",
    "avatar",
    "title",
    "theme",
    "customColors",
    "customBackground",
    "themeMotionEnabled",
    "themeTimeOfDayEnabled",
    "soundFeedbackEnabled",
    "speechFeedbackEnabled",
    "celebrationEnabled",
    "accessibilityLargeText",
    "accessibilityHighContrast",
    "accessibilityReducedMotion",
    "accessibilityKeyboardFocus",
    "layoutMode",
    "currentPage",
    "timerMinutes",
    "timerWarningMinutes",
    "tiles",
    "tilesSeen",
    "favorites",
    "appLimits",
    "weeklySchedule",
    "appAvailability",
    "categoryLimits",
    "choiceScreenEnabled",
    "birthMonth",
    "gender",
    "telemetryId",
)


def migrate_legacy_profile(data):
    """Move the former single-child settings into a default profile."""
    result = copy.deepcopy(data)
    profile = {
        "id": DEFAULT_PROFILE_ID,
        "name": "Kiddo",
        "avatar": "🌈",
        "favorites": [],
        "appLimits": {},
        "weeklySchedule": {"enabled": False, "days": {}},
        "appAvailability": {},
    }
    for field in PROFILE_FIELDS:
        if field in result:
            profile[field] = result.pop(field)
    profile.setdefault("tiles", [])
    result["activeProfileId"] = DEFAULT_PROFILE_ID
    result["profiles"] = [profile]
    return result


def profile_summaries(data):
    """Return the non-sensitive fields needed by a future profile picker."""
    return [
        {
            "id": profile["id"],
            "name": profile["name"],
            "avatar": profile.get("avatar", ""),
        }
        for profile in data.get("profiles", [])
    ]


def active_profile(data):
    profile_id = data.get("activeProfileId")
    for profile in data.get("profiles", []):
        if profile.get("id") == profile_id:
            return profile
    raise ValueError("activeProfileId does not reference an existing profile")


def active_config(data):
    """Project stored multi-profile data into the legacy-compatible runtime view."""
    result = copy.deepcopy(data)
    profile = copy.deepcopy(active_profile(result))
    result.pop("profiles", None)
    result.update({key: value for key, value in profile.items() if key != "id"})
    result["profiles"] = profile_summaries(data)
    return result


def merge_active_config(data, runtime_config):
    """Merge a validated flat runtime config into only the active profile."""
    result = copy.deepcopy(data)
    target = active_profile(result)
    for field in PROFILE_FIELDS:
        if field in runtime_config:
            target[field] = copy.deepcopy(runtime_config[field])

    ignored = {"profiles", "pinConfigured", *PROFILE_FIELDS}
    for key, value in runtime_config.items():
        if key not in ignored and key != "activeProfileId":
            result[key] = copy.deepcopy(value)
    return result


AVATAR_POR_GENERO = {"menino": "👦", "menina": "👧"}


def caminho_do_modelo():
    """Catálogo padrão: ao lado do servidor (instalado) ou no repositório."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    for caminho in (
        os.path.join(aqui, "config-modelo.json"),
        os.path.join(aqui, "..", "beni", "config", "config.json"),
    ):
        if os.path.isfile(caminho):
            return caminho
    return None


def perfil_modelo():
    """Primeiro perfil do catálogo padrão — o mesmo da configuração inicial.

    Não é o perfil ativo: aquele já pode ter jogos escondidos ou o gênero
    de outra criança.
    """
    caminho = caminho_do_modelo()
    if not caminho:
        raise ValueError("Não achei o catálogo padrão")
    with open(caminho, encoding="utf-8") as handle:
        texto = handle.read().replace("{{HOME}}", os.path.expanduser("~"))
    cfg = json.loads(texto)
    perfis = [p for p in (cfg.get("profiles") or []) if isinstance(p, dict)]
    if not perfis:
        raise ValueError("Não achei o catálogo padrão")
    return copy.deepcopy(perfis[0])


def _tile_portavel(tile):
    """Site ou jogo de navegador do Linux, no formato do Windows. O resto sai."""
    import jogos_genero

    cmd = tile.get("cmd") or []
    if len(cmd) == 1 and isinstance(cmd[0], str) and cmd[0].startswith("special:"):
        return copy.deepcopy(tile)
    novo = jogos_genero.traduzir_navegador_jogos(cmd)
    if not novo:
        return None
    tile = copy.deepcopy(tile)
    tile["cmd"] = novo
    return tile


def tiles_da_plataforma(modelo, plataforma):
    """Tiles de um perfil criado na configuração inicial, neste sistema.

    Linux: os do perfil-modelo. Windows: os que funcionam em qualquer sistema
    mais o catálogo (catalogo/windows.json), como scripts/windows/config-padrao.py.
    """
    tiles = copy.deepcopy(modelo.get("tiles") or [])
    if plataforma != "windows":
        return tiles
    portateis = [tile for tile in (_tile_portavel(tile) for tile in tiles) if tile]
    ids = {tile.get("id") for tile in portateis}
    import catalogo_windows

    for tile in catalogo_windows.tiles():
        if tile["id"] not in ids:
            portateis.append(copy.deepcopy(tile))
    return portateis


def add_profile(data, name, avatar="", profile_id=None, gender=None, plataforma=None):
    """Perfil novo com o padrão do gênero, igual a um da configuração inicial.

    Não copia tiles nem gênero do perfil ativo. O tempo de sessão e os
    limites por categoria vêm do perfil-modelo (os da primeira criança),
    não do irmão que está na tela: o limite de um pode ter sido apertado
    de propósito. Limite por app, horário e favorito começam como no modelo.
    """
    if gender not in AVATAR_POR_GENERO:
        raise ValueError("Escolha menino ou menina")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Digite o nome")
    nome = " ".join(name.split())[:40]
    if plataforma is None:
        plataforma = "windows" if os.name == "nt" else "linux"
    if plataforma not in ("linux", "windows"):
        raise ValueError("plataforma inválida")

    result = copy.deepcopy(data)
    profiles = result.setdefault("profiles", [])
    if len(profiles) >= MAX_PROFILES:
        raise ValueError(f"A maximum of {MAX_PROFILES} profiles is supported")

    new_id = profile_id or f"child-{uuid.uuid4().hex[:12]}"
    if not isinstance(new_id, str) or not PROFILE_ID_PATTERN.fullmatch(new_id):
        raise ValueError("Profile id contains invalid characters")
    if any(profile.get("id") == new_id for profile in profiles):
        raise ValueError("Profile id already exists")

    modelo = perfil_modelo()
    profile = copy.deepcopy(modelo)
    if not isinstance(avatar, str):
        avatar = ""
    avatar = avatar.strip()[:16]
    profile.update(
        id=new_id,
        name=nome,
        avatar=avatar or AVATAR_POR_GENERO[gender],
        title=f"Oi, {nome}!",
        theme="benikids",
        currentPage=0,
        gender=gender,
        tiles=tiles_da_plataforma(modelo, plataforma),
    )
    profile.pop("telemetryId", None)
    profile.pop("birthMonth", None)
    profile.pop("tilesSeen", None)
    ids = {tile.get("id") for tile in profile["tiles"] if isinstance(tile, dict)}
    if isinstance(profile.get("favorites"), list):
        profile["favorites"] = [i for i in profile["favorites"] if i in ids]
    for chave in ("appLimits", "appAvailability"):
        bruto = profile.get(chave)
        if isinstance(bruto, dict):
            profile[chave] = {k: v for k, v in bruto.items() if k in ids}
    import jogos_genero

    jogos_genero.aplicar_genero_inicial(profile, plataforma)
    profiles.append(profile)
    return result, new_id


def select_profile(data, profile_id):
    result = copy.deepcopy(data)
    if not any(profile.get("id") == profile_id for profile in result.get("profiles", [])):
        raise ValueError("Unknown profile")
    result["activeProfileId"] = profile_id
    return result


def remove_profile(data, profile_id):
    result = copy.deepcopy(data)
    profiles = result.get("profiles", [])
    if profile_id == result.get("activeProfileId"):
        raise ValueError("The active profile cannot be deleted")
    if len(profiles) <= 1:
        raise ValueError("The last profile cannot be deleted")
    remaining = [profile for profile in profiles if profile.get("id") != profile_id]
    if len(remaining) == len(profiles):
        raise ValueError("Unknown profile")
    result["profiles"] = remaining
    return result
