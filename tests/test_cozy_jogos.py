"""Lista de SNES/PS1 no Windows: pastas, capas e o núcleo, sem baixar da rede."""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cozy_jogos  # noqa: E402


class CozyJogosTests(unittest.TestCase):
    def test_lists_roms_and_hides_the_bin_of_a_cue(self):
        with tempfile.TemporaryDirectory() as raiz:
            snes = Path(raiz, "SNES")
            snes.mkdir()
            (snes / "Super Mario World (USA).sfc").write_bytes(b"rom")
            (snes / "BIOS").mkdir()
            (snes / "BIOS" / "nada.sfc").write_bytes(b"x")
            ps1 = Path(raiz, "PS1")
            ps1.mkdir()
            (ps1 / "Jogo.bin").write_bytes(b"bin")
            (ps1 / "Jogo.cue").write_text('FILE "Jogo.bin" BINARY\n', encoding="utf-8")
            (ps1 / "Solto.iso").write_bytes(b"iso")
            jogos = cozy_jogos.listar_jogos("snes", raiz)
            self.assertEqual(jogos, [("Super Mario World", str(snes / "Super Mario World (USA).sfc"))])
            nomes = [nome for nome, _ in cozy_jogos.listar_jogos("ps1", raiz)]
            self.assertEqual(nomes, ["Jogo", "Solto"])

    def _resposta(self, blob):
        class Resp:
            def __init__(self, dados):
                self.dados, self.i = dados, 0

            def read(self, n):
                parte = self.dados[self.i:self.i + n]
                self.i += n
                return parte

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp(blob)

    def _info(self, pacote, dll, extrator=b"7zr"):
        return {
            "versao": "1.22.2",
            "url": "https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/RetroArch_cores.7z",
            "sha256": hashlib.sha256(pacote).hexdigest(),
            "extrator": {
                "url": "https://github.com/ip7z/7zip/releases/download/24.09/7zr.exe",
                "arquivo": "7zr.exe",
                "sha256": hashlib.sha256(extrator).hexdigest(),
            },
            "snes": {"arquivo": "snes9x_libretro.dll", "sha256": hashlib.sha256(dll).hexdigest()},
            "ps1": {"arquivo": "pcsx_rearmed_libretro.dll", "sha256": "ab" * 32},
        }

    def test_pacote_com_hash_errado_nao_instala_e_loga(self):
        pacote, dll = b"pacote-oficial", b"MZ" + b"snes"
        info = self._info(pacote, dll)
        info["sha256"] = "0" * 64
        logs = []
        with tempfile.TemporaryDirectory() as pasta:
            caminho = cozy_jogos.baixar_core(
                "snes", pasta, abrir=lambda url: self._resposta(pacote),
                log=logs.append, info=info)
            self.assertEqual(caminho, "")
            self.assertFalse(list(Path(pasta).glob("*.dll")))
            self.assertTrue(any("hash não confere (pacote)" in linha for linha in logs))

    def test_instala_a_dll_so_quando_o_hash_dela_bate(self):
        pacote, dll, extrator = b"pacote-oficial", b"MZ" + b"snes" * 50, b"7zr-bin"
        info = self._info(pacote, dll, extrator)
        blobs = {info["url"]: pacote, info["extrator"]["url"]: extrator}
        logs = []

        def extrair(arquivo, saida, nomes, sete):
            self.assertEqual(Path(sete).read_bytes(), extrator)
            for nome in nomes:
                conteudo = dll if nome == "snes9x_libretro.dll" else b"dll-errada"
                Path(saida, nome).write_bytes(conteudo)
            return True

        with tempfile.TemporaryDirectory() as pasta:
            caminho = cozy_jogos.baixar_core(
                "snes", pasta, abrir=lambda url: self._resposta(blobs[url]),
                extrair=extrair, log=logs.append, info=info)
            self.assertEqual(Path(caminho).read_bytes(), dll)
            self.assertFalse((Path(pasta) / "pcsx_rearmed_libretro.dll").exists())
            self.assertTrue((Path(pasta) / "RetroArch_cores.7z").is_file())
            self.assertTrue(any("hash não confere (pcsx_rearmed_libretro.dll)" in linha for linha in logs))
            self.assertTrue(any("instalei snes9x_libretro.dll (1.22.2)" in linha for linha in logs))
            de_novo = cozy_jogos.baixar_core(
                "snes", pasta, abrir=lambda url: (_ for _ in ()).throw(AssertionError(url)),
                log=logs.append, info=info)
            self.assertEqual(de_novo, caminho)

    def test_nome_de_nucleo_nao_pode_ser_caminho(self):
        self.assertEqual(cozy_jogos.nucleo_de("snes", {"snes": {"arquivo": "../x.dll", "sha256": "ab" * 32}}), ("", ""))

    def test_command_needs_the_core_file(self):
        with tempfile.TemporaryDirectory() as raiz:
            core = os.path.join(raiz, "snes9x_libretro.dll")
            self.assertIsNone(cozy_jogos.comando_jogo("snes", "jogo.sfc", "retroarch.exe", "cfg", core))
            Path(core).write_bytes(b"MZ")
            self.assertEqual(
                cozy_jogos.comando_jogo("snes", "jogo.sfc", "retroarch.exe", "cfg", core),
                ["retroarch.exe", "-f", "-c", "cfg", "-L", core, "jogo.sfc"],
            )

    def test_config_keeps_fullscreen_borderless_and_escape(self):
        texto = cozy_jogos.texto_retroarch("ps1", os.path.join("C:\\", "Jogos"), os.path.join("C:\\", "cfg"))
        self.assertIn('video_driver = "gl"', texto)
        self.assertNotIn("d3d11", texto)
        self.assertIn('video_windowed_fullscreen = "true"', texto)
        self.assertIn('input_auto_mouse_grab = "false"', texto)
        self.assertIn("Jogos/.saves/ps1", texto.replace("\\", "/"))
        self.assertIn("PS1/BIOS", texto.replace("\\", "/"))
        self.assertEqual(cozy_jogos.garantir_opcao("ja = \"1\"\n", "ja", "2"), "ja = \"1\"\n")
        self.assertEqual(cozy_jogos.garantir_opcao("", "pcsx_rearmed_bios", "auto"),
                         'pcsx_rearmed_bios = "auto"\n')


if __name__ == "__main__":
    unittest.main()
