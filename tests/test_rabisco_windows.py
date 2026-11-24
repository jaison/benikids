"""Jogos navegador-jogos chegam uma vez ao Windows já instalado.

Oculto ou renomeado pelos pais não volta atrás. A segunda execução não mexe.
O config do Linux não é reescrito.
"""

import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

import rabisco_windows as rabisco  # noqa: E402
from config_validation import validate_stored_config  # noqa: E402


def jogo(ident, url="https://boom.rabisco.net/", **extra):
    item = {
        "id": ident,
        "label": ident,
        "emoji": "🎮",
        "cmd": ["special:external-browser:" + url],
        "visible": True,
        "category": "jogos",
    }
    item.update(extra)
    return item


def config(perfis, **extra):
    cfg = {
        "configVersion": 2,
        "activeProfileId": perfis[0]["id"],
        "profiles": perfis,
    }
    cfg.update(extra)
    return cfg


def perfil(ident, genero, tiles):
    item = {"id": ident, "name": ident, "tiles": list(tiles)}
    if genero:
        item["gender"] = genero
    return item


class RabiscoWindowsTest(unittest.TestCase):
    def test_arquivo_embarcado_bate_com_o_linux(self):
        linux = rabisco.extrair_dos_arquivos()
        self.assertEqual(rabisco.carregar(), linux)
        self.assertTrue(linux)
        ids = [t["id"] for t in linux]
        self.assertEqual(ids, list(dict.fromkeys(ids)))
        self.assertIn("rb-boom", ids)
        self.assertIn("bea-dollmaker", ids)
        for tile in linux:
            cmd = tile["cmd"][0]
            self.assertTrue(cmd.startswith("special:external-browser:"), tile["id"])
            self.assertNotIn("navegador-jogos", cmd)
            if "itch.zone" in cmd:
                self.assertIn("benikids-jogo:#", cmd, tile["id"])
                self.assertEqual(tile.get("gender"), "menina", tile["id"])
            else:
                self.assertNotIn("benikids-jogo:", cmd, tile["id"])
                self.assertNotIn("gender", tile, tile["id"])
            self.assertEqual(tile["category"], "jogos")

    def test_base_e_subconjunto_do_que_ja_esta_no_pacote(self):
        # Não compare com igualdade: um jogo novo fica só no tiles.json, fora da tupla,
        # e é isso que faz o Windows já instalado recebê-lo uma vez.
        ids = {t["id"] for t in rabisco.carregar()}
        self.assertTrue(set(rabisco.RABISCO_JA_ENTREGUES) <= ids)
        self.assertEqual(rabisco.RABISCO_JA_ENTREGUES, ())

    def test_pc_configurado_recebe_uma_vez_na_categoria_e_no_genero(self):
        lista = [
            jogo("rb-boom"),
            jogo("rb-arena", "https://arena.rabisco.net/", visible=False),
            jogo(
                "bea-dollmaker",
                "benikids-jogo:#w=960&h=540&u=https%3A%2F%2Fhtml-classic.itch.zone%2Fx",
                gender="menina",
            ),
        ]
        cfg = config([
            perfil("menino", "menino", [{"id": "paint", "label": "Desenhar", "cmd": ["paint"]}]),
            perfil("menina", "menina", []),
            perfil("sem", None, []),
        ])
        novo, mudou = rabisco.sincronizar(cfg, lista, ja_entregues=())
        self.assertTrue(mudou)
        self.assertEqual(
            [t["id"] for t in novo["profiles"][0]["tiles"]],
            ["paint", "rb-boom", "rb-arena"],
        )
        self.assertEqual(
            [t["id"] for t in novo["profiles"][1]["tiles"]],
            ["rb-boom", "rb-arena", "bea-dollmaker"],
        )
        self.assertEqual([t["id"] for t in novo["profiles"][2]["tiles"]], ["rb-boom", "rb-arena"])
        arena = novo["profiles"][0]["tiles"][-1]
        self.assertFalse(arena["visible"])
        self.assertEqual(arena["category"], "jogos")
        boneca = novo["profiles"][1]["tiles"][-1]
        self.assertNotIn("gender", boneca)
        self.assertIn("benikids-jogo:#", boneca["cmd"][0])
        self.assertEqual(novo["rabiscoSeen"], ["bea-dollmaker", "rb-arena", "rb-boom"])
        validate_stored_config(novo, existing_pin_hash="", allow_pin_hash=True)
        de_novo, mudou = rabisco.sincronizar(novo, lista, ja_entregues=())
        self.assertFalse(mudou)
        self.assertIs(de_novo, novo)

    def test_oculto_e_renomeado_pelos_pais_continua_e_nao_duplica(self):
        oculto = {
            "id": "rb-boom",
            "label": "Nome dos pais",
            "emoji": "💣",
            "cmd": ["special:external-browser:https://boom.rabisco.net/"],
            "visible": False,
            "category": "passatempo",
        }
        lista = [jogo("rb-boom"), jogo("rb-fight", "https://fight.rabisco.net/")]
        cfg = config([perfil("menino", "menino", [dict(oculto)])])
        novo, mudou = rabisco.sincronizar(cfg, lista, ja_entregues=())
        self.assertTrue(mudou)
        self.assertEqual(novo["profiles"][0]["tiles"][0], oculto)
        self.assertEqual([t["id"] for t in novo["profiles"][0]["tiles"]], ["rb-boom", "rb-fight"])
        novo["profiles"][0]["tiles"] = [oculto]
        parado, mudou = rabisco.sincronizar(novo, lista, ja_entregues=())
        self.assertFalse(mudou)
        self.assertEqual(parado["profiles"][0]["tiles"], [oculto])

    def test_apagado_antes_desta_funcao_nao_volta(self):
        antigo = jogo("rb-boom")
        cfg, mudou = rabisco.sincronizar(
            config([perfil("a", "menino", [])]), [antigo], ja_entregues=("rb-boom",),
        )
        self.assertTrue(mudou)  # grava rabiscoSeen, sem recolocar o tile
        self.assertEqual(cfg["profiles"][0]["tiles"], [])
        self.assertEqual(cfg["rabiscoSeen"], ["rb-boom"])

    def test_app_do_linux_nao_entra(self):
        extraidos = rabisco.extrair(
            {"profiles": [{"gender": "menino", "tiles": [
                {"id": "neverball", "label": "Bola", "cmd": ["neverball"], "visible": True},
                {"id": "rb-boom", "label": "Boom", "emoji": "💣", "cmd": [
                    "navegador-jogos", "https://boom.rabisco.net/",
                ], "visible": True, "category": "jogos"},
                {"id": "rb-itch-pelado", "label": "Pelado", "cmd": [
                    "navegador-jogos", "https://html-classic.itch.zone/html/1/index.html",
                ], "visible": True, "category": "jogos"},
            ]}]},
            {"migracoes": []},
        )
        self.assertEqual([t["id"] for t in extraidos], ["rb-boom"])

    def test_migracao_de_um_genero_so_entra_nele(self):
        tile = {
            "id": "rb-novo", "label": "Novo", "emoji": "🎮",
            "cmd": ["navegador-jogos", "https://novo.rabisco.net/"],
            "visible": True, "category": "jogos",
        }
        extraidos = rabisco.extrair(
            {"profiles": [
                {"id": "ela", "gender": "menina", "tiles": []},
                {"id": "ele", "gender": "menino", "tiles": []},
            ]},
            {"migracoes": [{"operacoes": [
                {"op": "adicionar_tile", "perfis": ["ela"], "tile": tile},
                {"op": "adicionar_tile", "tile": {"id": "app", "cmd": ["neverball"]}},
            ]}]},
        )
        self.assertEqual(extraidos[0]["id"], "rb-novo")
        self.assertEqual(extraidos[0]["gender"], "menina")
        self.assertEqual(
            extraidos[0]["cmd"],
            ["special:external-browser:https://novo.rabisco.net/"],
        )

    def test_linux_nao_muda(self):
        cfg_path = RAIZ / "beni" / "config" / "config.json"
        mig_path = RAIZ / "beni" / "config" / "migracoes.json"
        antes = (cfg_path.read_bytes(), mig_path.read_bytes())
        linux = rabisco.extrair_dos_arquivos()
        self.assertEqual((cfg_path.read_bytes(), mig_path.read_bytes()), antes)
        bruto = json.loads(cfg_path.read_text(encoding="utf-8"))
        perfis = json.dumps(bruto["profiles"], ensure_ascii=False)
        novo, mudou = rabisco.sincronizar(bruto, linux)
        self.assertTrue(mudou)  # só anota rabiscoSeen; os tiles do Linux ficam
        self.assertEqual(json.dumps(novo["profiles"], ensure_ascii=False), perfis)
        for perfil in novo["profiles"]:
            for tile in perfil["tiles"]:
                cmd = tile.get("cmd") or []
                if cmd and cmd[0] == "navegador-jogos":
                    self.assertNotIn("special:", "".join(cmd))
        self.assertEqual(novo["rabiscoSeen"], sorted(t["id"] for t in linux))
        outra, mudou = rabisco.sincronizar(novo, linux)
        self.assertFalse(mudou)
        self.assertIs(outra, novo)

    def test_servidor_so_sincroniza_no_windows(self):
        texto = (RAIZ / "src" / "server.py").read_text(encoding="utf-8")
        inicio = texto.index("apps novos do catálogo")
        fim = texto.index("telemetria_service", inicio)
        bloco = texto[inicio:fim]
        self.assertIn("rabisco_windows.sincronizar", bloco)
        guarda = texto.rfind("if os.name", 0, inicio)
        self.assertIn('os.name == "nt"', texto[guarda:inicio])


if __name__ == "__main__":
    unittest.main()
