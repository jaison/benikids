#!/usr/bin/env python3
"""Gera a configuração inicial do Windows a partir da do Beni (beni/config/config.json).

Ficam os perfis, temas, limites e horários, e só os tiles que funcionam em qualquer
sistema (sites, filmes e música). Os apps do Linux (flatpak, emuladores...) saem; no
Windows os pais adicionam os programas pela área dos pais.

Uso: config-padrao.py <saida.json>
"""

import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "src"))

from config_validation import validate_stored_config  # noqa: E402


def portavel(tile):
    cmd = tile.get("cmd") or []
    return len(cmd) == 1 and isinstance(cmd[0], str) and cmd[0].startswith("special:")


def main(saida):
    with open(os.path.join(RAIZ, "beni", "config", "config.json"), encoding="utf-8") as f:
        texto = f.read().replace("{{HOME}}", "~")
    cfg = json.loads(texto)
    cfg["pinHash"] = ""
    cfg["browser"] = ""  # o primeiro que existir: Edge, Chrome, Firefox, Brave
    for perfil in cfg.get("profiles", []):
        perfil["tiles"] = [t for t in perfil.get("tiles", []) if portavel(t)]
        ids = {t["id"] for t in perfil["tiles"]}
        perfil["favorites"] = [i for i in perfil.get("favorites", []) if i in ids]
        for chave in ("appLimits", "appAvailability"):
            perfil[chave] = {k: v for k, v in (perfil.get(chave) or {}).items() if k in ids}
        perfil["currentPage"] = 0
    cfg = validate_stored_config(cfg, existing_pin_hash="", allow_pin_hash=True)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for perfil in cfg["profiles"]:
        print(f"  {perfil['name']}: {len(perfil['tiles'])} tiles")


if __name__ == "__main__":
    main(sys.argv[1])
