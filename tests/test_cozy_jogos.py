"""Lista de SNES/PS1 no Windows: pastas, capas e o núcleo, sem baixar nada."""

import io
import os
import sys
import tempfile
import unittest
import zipfile
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

    def test_core_zip_must_be_the_expected_dll(self):
        dll = b"MZ" + b"x" * 30000
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as pacote:
            pacote.writestr("snes9x_libretro.dll", dll)
        self.assertEqual(cozy_jogos.extrair_dll(buf.getvalue(), "snes9x_libretro.dll"), dll)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as pacote:
            pacote.writestr("outra.dll", dll)
            pacote.writestr("snes9x_libretro.dll", dll)
        self.assertIsNone(cozy_jogos.extrair_dll(buf.getvalue(), "snes9x_libretro.dll"))
        self.assertIsNone(cozy_jogos.extrair_dll(b"MZ" + b"x" * 100, "snes9x_libretro.dll"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as pacote:
            pacote.writestr("snes9x_libretro.dll", b"MZ" + b"curta")
        self.assertIsNone(cozy_jogos.extrair_dll(buf.getvalue(), "snes9x_libretro.dll"))

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
        self.assertIn('video_windowed_fullscreen = "true"', texto)
        self.assertIn('input_auto_mouse_grab = "false"', texto)
        self.assertIn("Jogos/.saves/ps1", texto.replace("\\", "/"))
        self.assertIn("PS1/BIOS", texto.replace("\\", "/"))
        self.assertEqual(cozy_jogos.garantir_opcao("ja = \"1\"\n", "ja", "2"), "ja = \"1\"\n")
        self.assertEqual(cozy_jogos.garantir_opcao("", "pcsx_rearmed_bios", "auto"),
                         'pcsx_rearmed_bios = "auto"\n')


if __name__ == "__main__":
    unittest.main()
