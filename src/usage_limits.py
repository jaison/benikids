"""Limites diários de uso por categoria (ex.: Jogos 30 min + Aprender 30 min).

Uma categoria pode dividir o limite de outra ("pool": "jogos"): o Passatempo,
por exemplo, gasta dos mesmos 30 min dos Jogos.

O tempo só conta enquanto um app/site lançado pelo launcher está aberto.
Em Aprender (categoria "educativo"), segundos sem teclado, mouse, toque ou
controle não entram: a criança não ganha tempo de jogo só deixando a atividade
aberta e parada. O uso acumula por dia (data local; zera à meia-noite) e por
perfil, e fica persistido em ~/.local/state/cozy-kids-launcher/usage-today.json
para sobreviver a reinícios do servidor. O mesmo arquivo guarda um histórico curto
("history": segundos por categoria dos últimos HISTORY_DAYS dias), usado pela
regra de aprendizado: se ontem a criança não cumpriu a meta de Aprender, hoje
o limite de Jogar fica reduzido (ver learning_rule_status).
"""

import copy
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta


# O histórico é um campo extra opcional: continua na versão 1, e uma versão
# antiga do launcher simplesmente o ignora.
USAGE_VERSION = 1
HISTORY_DAYS = 14
CATEGORY_ID_PATTERN = re.compile(r"[a-z0-9_-]{1,32}")
MAX_CATEGORIES = 12
MAX_LIMIT_MINUTES = 24 * 60
SAVE_INTERVAL_SECONDS = 5.0
# Margem antes de o servidor fechar o app sozinho, caso o overlay não o faça.
ENFORCE_GRACE_SECONDS = 3
# Em Aprender, passado este tempo sem teclado, mouse, toque ou controle, a
# contagem pausa. Dá para ler ou pensar um pouco sem perder o tempo.
OCIOSO_APRENDER_SEGUNDOS = 90
MENSAGEM_VOLTA_APRENDER = "uso: aprender voltou a contar"
MENSAGEM_SEM_DETECCAO = (
    "uso: aprender sem detecção de ociosidade, o tempo conta sempre"
)

# Categorias conhecidas. Outras podem ser criadas no config.json com
# label/emoji próprios em categoryLimits.categories.
BUILTIN_CATEGORIES = {
    "jogos": {"label": "Jogos", "emoji": "🎮"},
    "educativo": {"label": "Aprender", "emoji": "📚"},
    "passatempo": {"label": "Passatempo", "emoji": "🎨"},
}

DEFAULT_CATEGORY_LIMITS = {
    "enabled": True,
    "totalMinutes": 60,
    "categories": {
        "jogos": {"minutes": 30},
        "educativo": {"minutes": 30},
        "passatempo": {"minutes": None, "pool": "jogos"},
    },
}

_EDUCATIVO_IDS = {
    "scratch", "pista-turbo", "blockly", "klavaro", "codeorg", "khan",
    "phet", "stellarium", "browser", "tuxmath",
}
_PASSATEMPO_IDS = {
    "paint", "autodraw", "colorir", "games", "gcompris", "musiclab", "klotski", "hexahop", "pingus",
}
_JOGOS_IDS = {
    "luanti", "supertux", "supertuxkart", "snes", "ps1", "frogatto",
    "music", "youtube-kids", "netflix-kids", "disney-plus", "prime-kids",
    "pbs-kids", "zdf-tivi", "kika",
}


def default_category_for_tile(tile):
    """Categoria sugerida para um tile sem categoria ("" = sem categoria).

    Aceita o dict do tile ou só o id. Jogos de navegador abertos pelo
    wrapper navegador-jogos/cozy-jogos contam como "jogos".
    """
    tile_id = tile.get("id", "") if isinstance(tile, dict) else str(tile)
    command = tile.get("cmd", []) if isinstance(tile, dict) else []
    first = os.path.basename(command[0]) if command and isinstance(command[0], str) else ""
    if tile_id in _EDUCATIVO_IDS:
        return "educativo"
    if tile_id in _PASSATEMPO_IDS:
        return "passatempo"
    if (
        tile_id in _JOGOS_IDS
        or tile_id.startswith("rb-")
        or first in ("navegador-jogos", "cozy-jogos")
    ):
        return "jogos"
    return ""


def effective_tile_category(tile):
    """Categoria gravada no tile; sem o campo, usa a sugestão padrão."""
    if "category" in tile:
        return tile.get("category") or ""
    return default_category_for_tile(tile)


# ---------------------------------------------------------------- validação

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _minutes(value, field, allow_none=True):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_LIMIT_MINUTES:
        raise ValueError(f"{field} must be between 0 and {MAX_LIMIT_MINUTES} minutes")
    return value


def validate_tile_category(value, field):
    if value == "":
        return ""
    if not isinstance(value, str) or not CATEGORY_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a short lowercase category id")
    return value


def _validate_weekdays(value, categories, field):
    """{mon..sun: {totalMinutes?, categories?: {id: minutes}}}.

    Campo ausente no dia = usa o valor padrão; null = sem limite nesse dia.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    clean = {}
    for day, entry in value.items():
        if day not in WEEKDAYS:
            raise ValueError(f"{field} contains an invalid weekday")
        if not isinstance(entry, dict) or set(entry).difference(("totalMinutes", "categories")):
            raise ValueError(f"{field}.{day} must be an object")
        item = {}
        if "totalMinutes" in entry:
            item["totalMinutes"] = _minutes(entry["totalMinutes"], f"{field}.{day}.totalMinutes")
        cats = entry.get("categories", {})
        if not isinstance(cats, dict):
            raise ValueError(f"{field}.{day}.categories must be an object")
        day_cats = {}
        for category_id, minutes in cats.items():
            if category_id not in categories:
                continue  # categoria removida: ignora
            if isinstance(minutes, dict):
                minutes = minutes.get("minutes")
            day_cats[category_id] = _minutes(minutes, f"{field}.{day}.categories.{category_id}")
        if day_cats:
            item["categories"] = day_cats
        clean[day] = item
    return clean


def weekday_key(now=None):
    moment = datetime.fromtimestamp(time.time() if now is None else now).astimezone()
    return WEEKDAYS[moment.weekday()]


def limits_for_day(limits, day):
    """Limites que valem no dia (aplica categoryLimits.weekdays[day] sobre o padrão)."""
    limits = limits or {}
    override = (limits.get("weekdays") or {}).get(day)
    if not override:
        return limits
    result = copy.deepcopy(limits)
    if "totalMinutes" in override:
        result["totalMinutes"] = override["totalMinutes"]
    for category_id, minutes in (override.get("categories") or {}).items():
        if category_id in result.get("categories", {}):
            result["categories"][category_id]["minutes"] = minutes
    return result


# Regra de aprendizado: a categoria que é a "meta" e o pool que é reduzido.
LEARNING_CATEGORY = "educativo"
PLAY_POOL = "jogos"
LEARNING_RULE_DEFAULTS = {
    "enabled": False,
    "goalPercent": 50,
    "reducedPercent": 50,
    "mode": "fixed",
}
LEARNING_RULE_MODES = ("fixed", "proportional")


def _percent(value, field, minimum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= 100:
        raise ValueError(f"{field} must be an integer between {minimum} and 100")
    return value


def validate_learning_rule(value, field="categoryLimits.learningRule"):
    """Normaliza {enabled, goalPercent 1-100, reducedPercent 0-100, mode fixed|proportional}."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    if set(value).difference(LEARNING_RULE_DEFAULTS):
        raise ValueError(f"{field} contains unsupported fields")
    rule = {**LEARNING_RULE_DEFAULTS, **value}
    if not isinstance(rule["enabled"], bool):
        raise ValueError(f"{field}.enabled must be a boolean")
    rule["goalPercent"] = _percent(rule["goalPercent"], f"{field}.goalPercent", 1)
    rule["reducedPercent"] = _percent(rule["reducedPercent"], f"{field}.reducedPercent", 0)
    if rule["mode"] not in LEARNING_RULE_MODES:
        raise ValueError(f"{field}.mode must be fixed or proportional")
    return rule


def validate_category_limits(value, field="categoryLimits"):
    """Normaliza {enabled,totalMinutes,categories:{id:{minutes,label?,emoji?}},weekdays?,learningRule?}."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    unknown = set(value).difference(("enabled", "totalMinutes", "categories", "weekdays", "learningRule"))
    if unknown:
        raise ValueError(f"{field} contains unsupported fields")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"{field}.enabled must be a boolean")
    total = _minutes(value.get("totalMinutes"), f"{field}.totalMinutes")
    categories = value.get("categories", {})
    if not isinstance(categories, dict) or len(categories) > MAX_CATEGORIES:
        raise ValueError(f"{field}.categories must be a small object")
    clean = {}
    for category_id, entry in categories.items():
        if not isinstance(category_id, str) or not CATEGORY_ID_PATTERN.fullmatch(category_id):
            raise ValueError(f"{field}.categories contains an invalid id")
        if isinstance(entry, int) and not isinstance(entry, bool):
            entry = {"minutes": entry}
        if not isinstance(entry, dict):
            raise ValueError(f"{field}.categories.{category_id} must be an object")
        extra = set(entry).difference(("minutes", "label", "emoji", "pool"))
        if extra:
            raise ValueError(f"{field}.categories.{category_id} has unsupported fields")
        item = {"minutes": _minutes(entry.get("minutes"), f"{field}.categories.{category_id}.minutes")}
        for key, maximum in (("label", 40), ("emoji", 16)):
            if key in entry:
                text = entry[key]
                if not isinstance(text, str) or len(text) > maximum:
                    raise ValueError(f"{field}.categories.{category_id}.{key} is invalid")
                item[key] = text
        if entry.get("pool") not in (None, "", category_id):
            pool = entry["pool"]
            if not isinstance(pool, str) or not CATEGORY_ID_PATTERN.fullmatch(pool):
                raise ValueError(f"{field}.categories.{category_id}.pool is invalid")
            item["pool"] = pool
        clean[category_id] = item
    # o pool tem que apontar para uma categoria que existe e que não divide com outra
    for category_id, item in clean.items():
        pool = item.get("pool")
        if pool and (pool not in clean or clean[pool].get("pool")):
            del item["pool"]
    result = {"enabled": enabled, "totalMinutes": total, "categories": clean}
    if value.get("weekdays"):
        result["weekdays"] = _validate_weekdays(value["weekdays"], clean, f"{field}.weekdays")
    if "learningRule" in value:
        result["learningRule"] = validate_learning_rule(value["learningRule"], f"{field}.learningRule")
    return result


# ------------------------------------------------------------- persistência

def today_key(now=None):
    moment = datetime.fromtimestamp(time.time() if now is None else now).astimezone()
    return moment.strftime("%Y-%m-%d")


def _empty_usage(day, history=None):
    return {"usageVersion": USAGE_VERSION, "date": day, "profiles": {}, "history": history or {}}


def previous_day_key(now=None):
    moment = datetime.fromtimestamp(time.time() if now is None else now).astimezone()
    return (moment.date() - timedelta(days=1)).isoformat()


def _clean_entry(entry):
    """{totalSeconds, categories:{id: s}} saneado, ou None se inválido."""
    if not isinstance(entry, dict):
        return None
    total = entry.get("totalSeconds", 0)
    cats = entry.get("categories", {})
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not isinstance(cats, dict):
        return None
    limpo = {
        "totalSeconds": max(0.0, float(total)),
        "categories": {
            str(k): max(0.0, float(v))
            for k, v in cats.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        },
    }
    # Benikids: segundos por app (tile), para o relatório de uso
    tiles = entry.get("tiles")
    if isinstance(tiles, dict):
        limpo["tiles"] = {
            str(k)[:80]: max(0.0, float(v))
            for k, v in tiles.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
    return limpo


def _valid_day(value):
    try:
        return isinstance(value, str) and datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value
    except ValueError:
        return False


def _prune_history(history, today):
    """Mantém só os últimos HISTORY_DAYS dias antes de hoje; descarta vazios."""
    oldest = (datetime.strptime(today, "%Y-%m-%d").date() - timedelta(days=HISTORY_DAYS)).isoformat()
    clean = {}
    for profile_id, days in history.items():
        kept = {day: entry for day, entry in days.items() if oldest <= day < today}
        if kept:
            clean[profile_id] = dict(sorted(kept.items()))
    return clean


def archive_day(history, day, profiles, today):
    """Move o uso de `day` (dict profile_id -> entrada) para o histórico."""
    if _valid_day(day) and day < today:
        for profile_id, entry in profiles.items():
            if entry.get("totalSeconds", 0) > 0:
                arquivado = {
                    "totalSeconds": round(entry["totalSeconds"], 1),
                    "categories": {k: round(v, 1) for k, v in entry.get("categories", {}).items()},
                }
                if entry.get("tiles"):
                    arquivado["tiles"] = {k: round(v, 1) for k, v in entry["tiles"].items()}
                history.setdefault(profile_id, {})[day] = arquivado
    return _prune_history(history, today)


def load_usage(path, now=None):
    day = today_key(now)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty_usage(day)
    if (
        not isinstance(data, dict)
        or data.get("usageVersion") != USAGE_VERSION
        or not isinstance(data.get("profiles"), dict)
    ):
        return _empty_usage(day)
    profiles = {}
    for profile_id, entry in data["profiles"].items():
        clean = _clean_entry(entry) if isinstance(profile_id, str) else None
        if clean is not None:
            profiles[profile_id] = clean
    history = {}
    raw_history = data.get("history")
    if isinstance(raw_history, dict):
        for profile_id, days in raw_history.items():
            if not isinstance(profile_id, str) or not isinstance(days, dict):
                continue
            for history_day, entry in days.items():
                clean = _clean_entry(entry) if _valid_day(history_day) else None
                if clean is not None:
                    history.setdefault(profile_id, {})[history_day] = clean
    if data.get("date") != day:
        # Arquivo de outro dia (servidor parado na meia-noite): vira histórico.
        return _empty_usage(day, archive_day(history, data.get("date"), profiles, day))
    return {"usageVersion": USAGE_VERSION, "date": day, "profiles": profiles,
            "history": _prune_history(history, day)}


def save_usage(path, data):
    directory = os.path.dirname(os.fspath(path)) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="usage-", suffix=".json", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------ cálculo

def category_pool(limits, category_id):
    """Categoria dona do limite: a própria ou a indicada em "pool"."""
    categories = (limits or {}).get("categories", {})
    pool = (categories.get(category_id) or {}).get("pool")
    return pool if pool in categories else category_id


def category_definitions(limits):
    """Lista ordenada de categorias configuradas, com nome, emoji e pool.

    "minutes" é o limite que vale para a categoria (o do pool, se dividir).
    """
    result = []
    categories = (limits or {}).get("categories", {})
    for category_id, entry in categories.items():
        builtin = BUILTIN_CATEGORIES.get(category_id, {})
        pool = category_pool(limits, category_id)
        result.append({
            "id": category_id,
            "label": entry.get("label") or builtin.get("label") or category_id.capitalize(),
            "emoji": entry.get("emoji") or builtin.get("emoji") or "⭐",
            "minutes": (categories.get(pool) or {}).get("minutes"),
            "pool": pool,
        })
    return result


def pooled_seconds(limits, usage_categories, pool):
    """Segundos usados por todas as categorias que dividem o limite `pool`."""
    return sum(
        seconds for category_id, seconds in (usage_categories or {}).items()
        if category_pool(limits, category_id) == pool
    )


def tile_category(profile, tile_id):
    for tile in profile.get("tiles", []):
        if tile.get("id") == tile_id:
            return effective_tile_category(tile)
    return ""


def _remaining(limit_minutes, used_seconds):
    if limit_minutes is None:
        return None
    return int(limit_minutes * 60 - used_seconds)


def _goal_seconds(limits, goal_percent):
    """Meta de Aprender (s) com os limites de um dia; None = Aprender sem limite."""
    minutes = ((limits.get("categories") or {}).get(LEARNING_CATEGORY) or {}).get("minutes")
    if minutes is None:
        return None
    return int(minutes * 60 * goal_percent / 100)


def apply_learning_rule(base_limits, history=None, today_usage=None, now=None):
    """Limites de hoje (com override do dia da semana) e a regra de aprendizado.

    Se ontem a criança usou o notebook mas fez menos de goalPercent% do limite
    de Aprender de ontem, o limite do pool "jogos" de hoje (já com o override
    do dia) cai para reducedPercent% (modo "fixed") ou para um valor entre
    reducedPercent% e 100% proporcional ao que aprendeu ("proportional").
    O total do dia não muda. Retorna (limites, info para o payload).
    """
    base_limits = base_limits or {}
    limits = limits_for_day(base_limits, weekday_key(now))
    rule = base_limits.get("learningRule") or {}
    rule = {**LEARNING_RULE_DEFAULTS, **rule}
    categories = limits.get("categories") or {}
    # "jogos" precisa ser dono do próprio limite (Passatempo divide com ele)
    play_entry = categories.get(PLAY_POOL) or {}
    base_minutes = None if play_entry.get("pool") else play_entry.get("minutes")
    yesterday = previous_day_key(now)
    yesterday_entry = (history or {}).get(yesterday) or {}
    yesterday_cats = yesterday_entry.get("categories") or {}
    # Meta de ontem: config atual com o override do dia da semana de ontem.
    yesterday_limits = limits_for_day(base_limits, WEEKDAYS[datetime.strptime(yesterday, "%Y-%m-%d").weekday()])
    learned = pooled_seconds(yesterday_limits, yesterday_cats, LEARNING_CATEGORY)
    goal = _goal_seconds(yesterday_limits, rule["goalPercent"])
    today_goal = _goal_seconds(limits, rule["goalPercent"])
    today_learned = pooled_seconds(limits, (today_usage or {}).get("categories") or {}, LEARNING_CATEGORY)
    enabled = bool(limits.get("enabled")) and bool(rule["enabled"])
    info = {
        "enabled": enabled,
        "active": False,
        "reason": "off",
        "mode": rule["mode"],
        "goalPercent": rule["goalPercent"],
        "reducedPercent": rule["reducedPercent"],
        "percent": 100,
        "category": PLAY_POOL,
        "learningCategory": LEARNING_CATEGORY,
        "yesterday": yesterday,
        "yesterdayUsedSeconds": int(yesterday_entry.get("totalSeconds", 0) or 0),
        "yesterdayLearnedSeconds": int(learned),
        "goalSeconds": goal,
        # limite de Aprender de ontem (para o texto "ontem Aprender foi 0/30 min")
        "yesterdayLearningMinutes": (
            (yesterday_limits.get("categories") or {}).get(LEARNING_CATEGORY) or {}
        ).get("minutes"),
        "baseMinutes": base_minutes,
        "minutes": base_minutes,
        "today": {
            "goalSeconds": today_goal,
            "learnedSeconds": int(today_learned),
            "met": today_goal is not None and today_learned >= today_goal - 1,
        },
    }
    if not enabled:
        return limits, info
    if goal is None:
        info["reason"] = "no_goal"  # Aprender sem limite ontem: não há meta
    elif info["yesterdayUsedSeconds"] <= 0:
        info["reason"] = "no_usage"  # notebook desligado / criança não usou
    elif learned >= goal - 1:
        info["reason"] = "goal_met"
    elif base_minutes is None:
        info["reason"] = "no_play_limit"  # Jogar sem limite hoje: nada a reduzir
    else:
        percent = rule["reducedPercent"]
        if rule["mode"] == "proportional" and goal > 0:
            percent = int(percent + (100 - percent) * min(1.0, learned / goal))
        reduced = int(base_minutes * percent / 100)
        info.update({"reason": "goal_missed", "percent": percent, "minutes": reduced,
                     "active": reduced < base_minutes})
        if reduced < base_minutes:
            limits = copy.deepcopy(limits)
            limits["categories"][PLAY_POOL]["minutes"] = reduced
    return limits, info


def compute_status(profile, usage_entry, active=None, now=None, history=None):
    """Retorna o payload público de uso para um perfil (limites do dia de hoje).

    history: {"AAAA-MM-DD": entrada de uso} do perfil, para a regra de aprendizado.
    """
    day = weekday_key(now)
    base_limits = profile.get("categoryLimits") or {}
    usage_entry = usage_entry or {"totalSeconds": 0.0, "categories": {}}
    limits, learning = apply_learning_rule(base_limits, history, usage_entry, now)
    enabled = bool(limits.get("enabled"))
    used_total = usage_entry.get("totalSeconds", 0.0)
    total_limit = limits.get("totalMinutes") if enabled else None
    total_remaining = _remaining(total_limit, used_total)
    total_exhausted = enabled and total_remaining is not None and total_remaining <= 0

    categories = []
    exhausted_ids = set()
    for definition in category_definitions(limits):
        used = usage_entry.get("categories", {}).get(definition["id"], 0.0)
        pool_used = pooled_seconds(limits, usage_entry.get("categories", {}), definition["pool"])
        own_remaining = _remaining(definition["minutes"], pool_used) if enabled else None
        effective = own_remaining
        if total_remaining is not None:
            effective = total_remaining if effective is None else min(effective, total_remaining)
        exhausted = enabled and effective is not None and effective <= 0
        if exhausted:
            exhausted_ids.add(definition["id"])
        if learning["active"] and definition["pool"] == PLAY_POOL:
            definition["baseMinutes"] = learning["baseMinutes"]
            definition["learningReduced"] = True
        categories.append({
            **definition,
            "usedSeconds": int(used),
            "poolUsedSeconds": int(pool_used),
            "remainingSeconds": None if own_remaining is None else max(0, own_remaining),
            "availableSeconds": None if effective is None else max(0, effective),
            "exhausted": exhausted,
        })

    blocked = []
    reasons = {}
    if enabled:
        for tile in profile.get("tiles", []):
            tile_id = tile.get("id")
            if not tile_id:
                continue
            if total_exhausted:
                blocked.append(tile_id)
                reasons[tile_id] = "daily_limit"
            elif effective_tile_category(tile) in exhausted_ids:
                blocked.append(tile_id)
                reasons[tile_id] = "category_limit"

    active_payload = None
    if active:
        category_id = active.get("category", "")
        cat = next((c for c in categories if c["id"] == category_id), None)
        own = cat["remainingSeconds"] if cat else None
        remaining = None
        limited_by = ""
        if enabled:
            if own is not None and (total_remaining is None or own <= total_remaining):
                remaining, limited_by = own, "category"
            elif total_remaining is not None:
                remaining, limited_by = max(0, total_remaining), "total"
        alternatives = []
        if enabled and limited_by == "category":
            own_pool = cat["pool"] if cat else category_id
            for other in categories:
                if other["id"] == category_id or other["exhausted"] or other["pool"] == own_pool:
                    continue
                alternatives.append({
                    "id": other["id"],
                    "label": other["label"],
                    "emoji": other["emoji"],
                    "availableSeconds": other["availableSeconds"],
                })
        active_payload = {
            "tileId": active.get("tileId", ""),
            "category": category_id,
            "categoryLabel": cat["label"] if cat else "",
            "categoryEmoji": cat["emoji"] if cat else "⏳",
            "limitSeconds": (
                (cat["minutes"] * 60 if cat and cat["minutes"] is not None else None)
                if limited_by == "category"
                else (total_limit * 60 if total_limit is not None else None)
            ),
            "remainingSeconds": remaining,
            "limitedBy": limited_by,
            "alternatives": alternatives,
        }

    return {
        "enabled": enabled,
        "weekday": day,
        "weekdayLimits": bool(base_limits.get("weekdays")),
        "totalMinutes": total_limit,
        "totalUsedSeconds": int(used_total),
        "totalRemainingSeconds": None if total_remaining is None else max(0, total_remaining),
        "totalExhausted": total_exhausted,
        "categories": categories,
        "blockedTileIds": blocked,
        "blockedReasons": reasons,
        # Categoria efetiva de cada tile (inclui a regra padrão para tiles
        # sem o campo "category"); usada pela tela de escolha Aprender/Jogar.
        "tileCategories": {
            tile.get("id"): effective_tile_category(tile)
            for tile in profile.get("tiles", [])
            if tile.get("id")
        },
        "active": active_payload,
        "learningRule": learning,
    }


def mensagem_pausa_aprender(segundos=OCIOSO_APRENDER_SEGUNDOS):
    return f"uso: aprender pausado (sem teclado/mouse há {int(segundos)} s)"


def ociosidade_efetiva(teclado, controle):
    """Segundos sem entrada que valem para pausar o Aprender.

    teclado None: não deu para medir (não pausar, para não punir a criança).
    controle None: este sistema não viu controle; vale só teclado, mouse e toque.
    """
    if teclado is None:
        return None
    if controle is None:
        return float(teclado)
    return min(float(teclado), float(controle))


def segundos_sem_teclado():
    """Segundos desde o último teclado, mouse ou toque.

    None se este computador não deixa medir (Mac de desenvolvimento, Wayland
    sem a extensão, biblioteca ausente). Aí o Aprender conta sempre.
    """
    if os.name == "nt":
        try:
            import plataforma_windows
            return float(plataforma_windows.segundos_sem_uso())
        except Exception:  # noqa: BLE001 — falhou a medição: não pausa
            return None
    if not sys.platform.startswith("linux"):
        return None
    return _segundos_linux()


class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("til_or_since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("event_mask", ctypes.c_ulong),
    ]


# "xss" | "xprintidle" | "nenhum" | None (ainda não tentou)
_linux_modo = None
_xss_libs = None


def _xss_carregar():
    """(libX11, libXss) ou None. XDefaultRootWindow é macro: usa as duas funções."""
    global _xss_libs
    if _xss_libs is False:
        return None
    if _xss_libs:
        return _xss_libs
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        xss = ctypes.CDLL("libXss.so.1")
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x11.XDefaultScreen.restype = ctypes.c_int
        x11.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XRootWindow.restype = ctypes.c_ulong
        xss.XScreenSaverQueryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XScreenSaverInfo),
        ]
        xss.XScreenSaverQueryInfo.restype = ctypes.c_int
    except (AttributeError, OSError):
        _xss_libs = False
        return None
    _xss_libs = (x11, xss)
    return _xss_libs


def _xss_segundos():
    libs = _xss_carregar()
    if not libs:
        return None
    x11, xss = libs
    tela = x11.XOpenDisplay(None)
    if not tela:
        return None
    try:
        info = _XScreenSaverInfo()
        raiz = x11.XRootWindow(tela, x11.XDefaultScreen(tela))
        if not xss.XScreenSaverQueryInfo(tela, raiz, ctypes.byref(info)):
            return None
        return info.idle / 1000.0
    except Exception:  # noqa: BLE001 — uma falha não pode derrubar o contador
        return None
    finally:
        try:
            x11.XCloseDisplay(tela)
        except Exception:  # noqa: BLE001
            pass


def _xprintidle_segundos():
    caminho = shutil.which("xprintidle")
    if not caminho:
        return None
    try:
        saida = subprocess.check_output(
            [caminho], timeout=1.5, text=True, stderr=subprocess.DEVNULL,
        )
        return int(saida.strip()) / 1000.0
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _segundos_linux():
    """XScreenSaverQueryInfo; se a biblioteca não existe, o comando xprintidle.

    Se nenhum funcionar, devolve None para sempre (não tenta de novo a cada
    segundo). Uma falha depois de já ter medido conta aquele instante, em vez
    de desligar a pausa para o resto da sessão.
    """
    global _linux_modo
    if _linux_modo == "nenhum":
        return None
    if _linux_modo == "xprintidle":
        valor = _xprintidle_segundos()
        return 0.0 if valor is None else valor
    if _linux_modo == "xss":
        valor = _xss_segundos()
        return 0.0 if valor is None else valor
    valor = _xss_segundos()
    if valor is not None:
        _linux_modo = "xss"
        return valor
    valor = _xprintidle_segundos()
    if valor is not None:
        _linux_modo = "xprintidle"
        return valor
    _linux_modo = "nenhum"
    return None


def medir_ociosidade(controle=None):
    """Função para o UsageTracker: segundos sem entrada, no máximo 1 vez por segundo.

    controle(): segundos sem uso do controle, ou None se não houve / não há leitura.
    """
    cache = {"em": 0.0, "valor": None}
    trava = threading.Lock()

    def medir():
        agora = time.monotonic()
        with trava:
            if cache["em"] and agora - cache["em"] < 1.0:
                return cache["valor"]
        teclado = segundos_sem_teclado()
        extra = None
        if teclado is not None and controle is not None:
            try:
                extra = controle()
            except Exception:  # noqa: BLE001 — controle é extra, não pode pausar à toa
                extra = None
        valor = ociosidade_efetiva(teclado, extra)
        with trava:
            cache["em"] = agora
            cache["valor"] = valor
        return valor

    return medir


# ----------------------------------------------------------------- tracker

class UsageTracker:
    """Acumula segundos de uso do tile ativo e aplica os limites.

    load_profiles(): devolve (dict profile_id -> perfil armazenado).
    tile_alive(): True enquanto o processo do tile está aberto.
    stop_tile(): fecha o app aberto (mesmo efeito do ❌).
    """

    def __init__(self, path, load_profiles, tile_alive, stop_tile, clock=time.time,
                 ociosidade=None, log=None):
        self.path = os.fspath(path)
        self.load_profiles = load_profiles
        self.tile_alive = tile_alive
        self.stop_tile = stop_tile
        self.clock = clock
        # () -> segundos sem teclado/mouse/toque/controle, ou None se não deu para medir.
        # None (o argumento): testes e quem não liga a pausa; o Aprender conta como antes.
        self.ociosidade = ociosidade
        self.log = log
        self.lock = threading.RLock()
        self.usage = load_usage(self.path, self.clock())
        self.active = None
        self.last_tick = None
        self.last_save = 0.0
        self.dirty = False
        self.last_expiry = None
        self._thread = None
        self._stop = threading.Event()
        # roteiro 31: app "Não respondendo" não conta (o vigia da pílula pausa e retoma)
        self.pausado = False
        self.descontado = 0.0
        # Aprender aberto e sem entrada há OCIOSO_APRENDER_SEGUNDOS: aqueles segundos não entram
        self.aprender_parado = False
        self._ociosidade_indisponivel = False

    # -- ciclo de vida
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="usage-tracker", daemon=True)
            self._thread.start()

    def shutdown(self):
        self._stop.set()
        with self.lock:
            self._accrue()
            self._save(force=True)

    def _run(self):
        while not self._stop.wait(1.0):
            try:
                self.tick()
            except Exception:
                pass

    # -- tile ativo
    def set_active(self, profile_id, tile_id, category):
        with self.lock:
            self._accrue()
            self.active = {
                "profileId": profile_id,
                "tileId": tile_id,
                "category": category or "",
                "startedAt": self.clock(),
            }
            self.last_tick = self.clock()
            self.pausado = False  # app novo: conta desde já
            self.descontado = 0.0
            self._sincronizar_pausa_aprender()

    def adopt(self, profile_id, tile_id, category, tile_alive):
        """Retoma um tile que ainda está aberto (ex.: após reiniciar o servidor)."""
        with self.lock:
            if self.active is None and tile_alive():
                self.set_active(profile_id, tile_id, category)

    def pausar(self):
        """O app parou de responder: daqui em diante o tempo não conta."""
        with self.lock:
            self._accrue()
            if not self.pausado:
                self.pausado = True
                self.descontado = 0.0

    def retomar(self):
        """O app voltou (ou fechou): volta a contar. Devolve os segundos não contados."""
        with self.lock:
            self._accrue()
            segundos = self.descontado if self.pausado else 0.0
            self.pausado = False
            self.descontado = 0.0
            return segundos

    def parado_agora(self):
        with self.lock:
            self._accrue()
            return self.descontado if self.pausado else 0.0

    def clear_active(self):
        with self.lock:
            self._accrue()
            self.active = None
            self.last_tick = None
            self._sincronizar_pausa_aprender()
            self._save(force=True)

    # -- contagem
    def _roll_day(self):
        day = today_key(self.clock())
        if self.usage.get("date") != day:
            history = archive_day(
                self.usage.get("history") or {}, self.usage.get("date"), self.usage.get("profiles") or {}, day
            )
            self.usage = _empty_usage(day, history)
            self.last_expiry = None
            self.dirty = True

    def _history(self, profile_id):
        return (self.usage.get("history") or {}).get(profile_id) or {}

    def _entry(self, profile_id):
        return self.usage["profiles"].setdefault(
            profile_id, {"totalSeconds": 0.0, "categories": {}}
        )

    def _log(self, texto):
        if self.log is None:
            return
        try:
            self.log(texto)
        except Exception:  # noqa: BLE001 — o log não pode parar a contagem
            pass

    def _medir_ociosidade(self):
        """Segundos sem entrada. None = não deu para medir (conta sempre).

        Sem a função injetada, devolve 0: o Aprender conta, como antes desta regra.
        """
        if self.ociosidade is None:
            return 0.0
        if self._ociosidade_indisponivel:
            return None
        try:
            valor = self.ociosidade()
        except Exception:  # noqa: BLE001
            valor = None
        if valor is None:
            self._ociosidade_indisponivel = True
            self._log(MENSAGEM_SEM_DETECCAO)
            return None
        try:
            return float(valor)
        except (TypeError, ValueError):
            self._ociosidade_indisponivel = True
            self._log(MENSAGEM_SEM_DETECCAO)
            return None

    def _definir_pausa_aprender(self, parado):
        parado = bool(parado)
        if parado == self.aprender_parado:
            return
        self.aprender_parado = parado
        if parado:
            self._log(mensagem_pausa_aprender())
        elif self.active and self.active.get("category") == LEARNING_CATEGORY:
            self._log(MENSAGEM_VOLTA_APRENDER)

    def _sincronizar_pausa_aprender(self):
        """True se o Aprender está aberto e ocioso além do limite. As outras categorias não pausam."""
        ativo = self.active or {}
        if ativo.get("category") != LEARNING_CATEGORY:
            self._definir_pausa_aprender(False)
            return False
        segundos = self._medir_ociosidade()
        if segundos is None:
            self._definir_pausa_aprender(False)
            return False
        parado = segundos >= OCIOSO_APRENDER_SEGUNDOS
        self._definir_pausa_aprender(parado)
        return parado

    def _accrue(self):
        now = self.clock()
        self._roll_day()
        ocioso = self._sincronizar_pausa_aprender()
        if self.active and self.last_tick is not None:
            delta = now - self.last_tick
            if self.pausado and 0 < delta <= 10:
                self.descontado += delta
                delta = 0
            elif ocioso and 0 < delta <= 10:
                delta = 0
            # Ignora saltos (suspensão do notebook, relógio ajustado).
            if 0 < delta <= 10:
                entry = self._entry(self.active["profileId"])
                entry["totalSeconds"] += delta
                category = self.active.get("category")
                if category:
                    entry["categories"][category] = entry["categories"].get(category, 0.0) + delta
                tile_id = self.active.get("tileId")
                if tile_id:
                    tiles = entry.setdefault("tiles", {})
                    tiles[tile_id] = tiles.get(tile_id, 0.0) + delta
                self.dirty = True
        self.last_tick = now if self.active else None

    def _save(self, force=False):
        now = self.clock()
        if self.dirty and (force or now - self.last_save >= SAVE_INTERVAL_SECONDS):
            try:
                save_usage(self.path, self.usage)
                self.dirty = False
                self.last_save = now
            except OSError:
                pass

    def tick(self):
        stop_needed = False
        with self.lock:
            if self.active and not self.tile_alive():
                self._accrue()
                self.active = None
                self.last_tick = None
                self._sincronizar_pausa_aprender()
                self._save(force=True)
                return
            self._accrue()
            if self.active:
                profile = self.load_profiles().get(self.active["profileId"])
                if profile:
                    profile_id = self.active["profileId"]
                    status = compute_status(
                        profile, self.usage["profiles"].get(profile_id), self.active,
                        now=self.clock(), history=self._history(profile_id),
                    )
                    remaining = (status.get("active") or {}).get("remainingSeconds")
                    if remaining is not None and remaining <= 0:
                        self._remember_expiry(status)
                        self._save(force=True)
                        # Contamos a partir do instante em que zerou (o overlay
                        # fecha o app no 0; aqui é só a garantia).
                        used_over = self._overrun(profile)
                        if used_over >= ENFORCE_GRACE_SECONDS:
                            stop_needed = True
            self._save()
        if stop_needed:
            try:
                self.stop_tile()
            finally:
                self.clear_active()

    def _overrun(self, profile):
        """Segundos além do limite consumidos pelo app ativo."""
        entry = self.usage["profiles"].get(self.active["profileId"], {})
        limits, _ = apply_learning_rule(
            profile.get("categoryLimits"), self._history(self.active["profileId"]), entry, self.clock()
        )
        overs = []
        total = limits.get("totalMinutes")
        if total is not None:
            overs.append(entry.get("totalSeconds", 0) - total * 60)
        category = self.active.get("category")
        pool = category_pool(limits, category) if category else None
        cat_limit = (limits.get("categories", {}).get(pool) or {}).get("minutes") if pool else None
        if cat_limit is not None:
            overs.append(pooled_seconds(limits, entry.get("categories", {}), pool) - cat_limit * 60)
        return max(overs) if overs else 0

    def _remember_expiry(self, status):
        active = status.get("active") or {}
        if self.last_expiry and self.last_expiry.get("tileId") == active.get("tileId") \
                and self.clock() - self.last_expiry.get("at", 0) < 60:
            return
        self.last_expiry = {
            "at": int(self.clock()),
            "profileId": self.active["profileId"],
            "tileId": active.get("tileId", ""),
            "category": active.get("category", ""),
            "categoryLabel": active.get("categoryLabel", ""),
            "categoryEmoji": active.get("categoryEmoji", ""),
            "limitedBy": active.get("limitedBy", ""),
        }

    # -- consulta
    def status(self, profile_id, profile):
        with self.lock:
            self._accrue()
            active = self.active if self.active and self.active["profileId"] == profile_id else None
            payload = compute_status(
                profile, self.usage["profiles"].get(profile_id), active,
                now=self.clock(), history=self._history(profile_id),
            )
            payload["date"] = self.usage["date"]
            payload["profileId"] = profile_id
            payload["now"] = int(self.clock())
            pausado = bool(
                self.aprender_parado and active and active.get("category") == LEARNING_CATEGORY
            )
            payload["paused"] = pausado
            if isinstance(payload.get("active"), dict):
                payload["active"]["paused"] = pausado
            if self.last_expiry and self.last_expiry.get("profileId") == profile_id:
                payload["lastExpiry"] = copy.deepcopy(self.last_expiry)
            return payload

    def reset(self, profile_id=None):
        with self.lock:
            self._accrue()
            if profile_id:
                self.usage["profiles"].pop(profile_id, None)
            else:
                self.usage["profiles"] = {}
            self.last_expiry = None
            self.dirty = True
            self._save(force=True)
