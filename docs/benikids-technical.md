# Benikids: details and technical notes

🇧🇷 [Português](benikids-tecnico.md) · 🇺🇸 **English** · ⬅ [README](../README.en.md)

Everything that doesn't fit in the README: each feature in detail, fine-tuning on Linux, how it
works inside, how to publish an update and the fixes for old hardware.

## For the kids

### Three categories, each with its own time
- **"Learn / Hobbies / Play" home screen**: big cards with a progress bar and "18 min left".
  - The list shows only the chosen category, with **⬅ Back** (or Esc).
  - When time runs out, the card turns grey with 🔒 "More tomorrow!".
- Green/yellow/red **meters** in the launcher. During a game, a discreet bar shows the time left. It is semi-transparent, can be dragged to another corner and has the ❌ to close.
- On **websites** there is also a **‹ Back** button in the bottom-left corner.
- In the **last 10 seconds**, a big countdown warns ("Your game time is running out! 8…") and suggests what is still possible ("You can still Learn (18 min)").
- With **required learning** turned on:
  - the Play and Hobbies cards explain it kindly: "15 min today — yesterday's learning was missing 📚";
  - the Learn card shows what's left to get full Play time tomorrow ("Today's goal done! ⭐").

### What's in each category
| 📚 Learn | 🎨 Hobbies | 🎮 Play |
|---|---|---|
| Khan Academy (automatic login) | Drawing (**Kleki**, drawings saved in Pictures/Drawings) | Luanti (Minecraft-like) |
| **PhET** with a screen to pick the subject (Physics, Math, Chemistry, Earth & Space, Biology), already at primary school level | **Autodraw** | SuperTux, SuperTuxKart, Frogatto |
| **Escola Games** with no ads and no menu of non-educational games | **Coloring** (just the drawings, no ads for other games) | **Super Nintendo and PlayStation** (list with covers, keyboard/mouse/gamepad) |
| Scratch (TurboWarp), **Pista Turbo** (a ready-made Scratch racing game to play and modify), Blockly Games | **Teach Your Monster** (automatic login) and **Kiddo Games** (73 small games, no ads) | **itch.io** browser games in real full screen |
| Typing (Klavaro), Planetarium (Stellarium) | GCompris, Pingus, Hex-a-hop, Klotski, Music Lab | ad-free dress-up/make-up/doll games |

Parents can move any app to another category in Parents → Screen time.

### Look
- **6 new themes** with original SVG art (no brand characters or logos):
  - **Spider Hero** (comics), **Building Blocks** and **Ninja Dojo**;
  - **Ice Kingdom**, **Magic House** and **Enchanted Castle**, with large rounded letters for early readers.
- **Everything in Brazilian Portuguese**, on the kids' screens and in the parents' area.

---

## For parents

### ⏳ Screen time (Parents → Screen time)
- **Daily limit per category and for the whole day**, e.g. 30 min of Learn + 30 min of Play.
- **Hobbies share time with Play**: drawing for 10 min leaves 20 for games. They can also have their own time.
- **Different time for each weekday**: a Mon–Sun table with today highlighted.
- **Each app's category** picked from a list, and a **"Reset today's time"** button.
- Allowed hours per day and per app (from the original project).

### 📚 Required learning (same panel)
- **Goal**: do at least *X*% of the day's Learn time (default 50%: with 30 min of Learn, the goal is 15).
- **Consequence**: if yesterday's goal was missed, today Play (and Hobbies, which share its time) gets *Y*% (default 50%).
- **Proportional mode** (optional): a child who learned a little loses less.
- **Fair to the child**:
  - days the laptop wasn't used don't count;
  - Learn time and the daily total never shrink;
  - the launcher itself closes the game at the reduced limit.
- Parents see the reason, e.g. "Today: Play reduced to 15 min (from 30) because yesterday Learn was 0/30 min".
- Off by default, turned on per profile.

### 🔑 Automatic site logins (Parents → Children)
- An **"Automatic site logins"** panel with e-mail/username and password **per child**.
  - Today: Khan Academy and Teach Your Monster (family account, "Home" tab).
- When the site opens, the launcher fills in the login and clicks "Sign in". If the session is still open, it types nothing.
- **The password stays on this computer only**, in a file separate from the configuration and readable only by the user. Once saved, it is never shown on screen again.
- **Each child has their own site browser** (separate cookies and logins): Bea's Khan doesn't open with Beni's account.
- To add another site, describe its login page in `src/site_logins.py`.

### 🛡️ Internet and content
- **CleanBrowsing Family DNS** on any Wi‑Fi:
  - blocks adult sites, proxies and VPNs;
  - enforces Google/Bing SafeSearch and YouTube Restricted Mode.
- Browsers can't bypass the filter, because DNS‑over‑HTTPS is turned off.
- **uBlock Origin** on sites, tuned so Escola Games' games open without ads.
- **Sites cleaned up with custom CSS**:
  - Escola Games without the "Games" menu;
  - Coloring without the top bar, banners and social links;
  - Autodraw without "Share" and external links.

  Forbidden pages are also blocked by Firefox policy.
- Downloads go straight to `~/Imagens/Desenhos`, without Firefox's download panel, which would open the file manager.

### 🎮 Gamepads (Parents → System → Gamepads)
- Works with **generic USB gamepads**, cheap unbranded ones included. A **wizard** asks for each button (d-pad, ✕, ◯, Start, Select…) and saves the mapping.
- With it, the gamepad:
  - **navigates the menu** (d-pad = arrows, ✕ = open, ◯ = back);
  - works in **SDL games** (SuperTux, SuperTuxKart…), **Super Nintendo** (RetroArch), **PlayStation** (PCSX-R) and **browser games** (a Chromium extension exposes it in the standard layout);
  - closes the running game and returns to the menu by holding **Start + Select for 2 s**.
- Games that work with a gamepad get a 🎮 badge in the menu.
- On Windows, games handle the gamepad themselves, but the menu can't be navigated with it yet.

### Other
- **itch.io collections**: each child has a public collection. A game added to the collection becomes an icon (with its cover), and a removed game disappears. Sync runs at login and every 30 min, so parents test first and only then release a game.
- In Parents → Appearance → **Home screen**, you turn the Learn/Hobbies/Play question on or off per profile.

### 🔄 Automatic updates (Linux)
- Every hour the laptop checks this repository on GitHub for a **new Release** and downloads it by itself. Commits to `main` do **not** reach the kids; only Releases do.
- **When it installs**:
  - **at boot**, before the menu shows up (default);
  - **overnight (2am–5am)**, if the laptop is always on and nobody is using it;
  - **right away**, if the Release notes contain **`[forcar]`**. It waits until no app is open; the menu closes with the notice "🔧 Updating the computer… back in a minute!" and reopens by itself.
- An update brings code, new apps (apt/Flathub), sites, Firefox and DNS rules and **catalog changes** (adding/removing games). What parents configured (limits, themes, PIN, logins) is left alone.
- If the installation fails, it **rolls back** to the previous version by itself and doesn't retry that version.
- Parents → System → **Updates** shows the installed version, the last check and whether a downloaded version is waiting.

---

## Fine-tuning on Linux

After installing, before handing it to the child:
- **Parents → System: create the parents' PIN.** Without a PIN, anyone can open the panel, leave kids mode, reset time or see the e-mail of saved accounts.
- Adjust names, themes and limits in Parents. The initial configuration has two example profiles, with apps already sorted into Learn/Hobbies/Play.
- If you like, turn on **required learning** (Parents → Screen time) and save the **site logins** (Parents → Children).
- Luanti: open it once and install the **Mineclonia** game (Content → Browse).
- Put your SNES/PS1 games in `~/Jogos/SNES` and `~/Jogos/PS1`. The PS1 BIOS goes in `~/Jogos/PS1/BIOS` (see `~/Jogos/LEIA-ME.txt`).
- Replace the itch.io collections in `~/.config/cozy-kids-launcher/itch-colecoes.json`. The file maps the **profile id** to the collection's public URL.

Running `./instalar.sh` again updates the files and **does not erase** the configuration, saved
logins or games. Use `./instalar.sh --sem-apps` to leave apt/flatpak alone.

---

## How it works (technical summary)

```
login → ~/.config/autostart → cozy-iniciar
          ├─ cozy-itch-sync      (itch.io collections → "itch-*" tiles in config.json)
          └─ cozy-kids-launcher  (Python server on 127.0.0.1:38431 + native menu beni-menu;
                 │                    with no usable GPU, Firefox in kiosk mode)
                 ├─ Parents → Firefox with only the parents' area (closes on return)
                 ├─ usage_limits.py   (time per category, weekday, required learning)
                 └─ tapping an icon → process_supervisor.py + overlay.py (❌, time, ‹ Back)
                        ├─ local apps: shortcuts in ~/.local/bin (supertux, gcompris, …)
                        ├─ sites: Firefox in kiosk mode, one profile per child
                        │     (uBlock, site CSS; site_logins.py logs in through Marionette)
                        └─ browser games: navegador-jogos → Chromium in kiosk mode
                               → cozy-jogo.html (scales the game) + carregando.py (loading screen)
```

| Where | What |
|---|---|
| `src/` | launcher code (original + changes) → `~/.local/share/cozy-kids-launcher` |
| `src/beni_windows.py`, `src/plataforma_windows.py` | on Windows: starts the server and the menu, and does the job of bash/`xdotool` (process tree, a Job Object to close the whole app, window focus) |
| `src/catalogo/windows.json`, `src/instalar_apps.py` | the Windows app catalog and installing it through `winget` |
| `scripts/windows/` | installer and initial configuration of the Windows package (assembled by GitHub Actions in `menu-nativo.yml`) |
| `cliente/` | **native menu** (`beni-menu`, Rust + gpui-fast): the kids' screen without a browser. See [cliente/LEIA-ME.md](../cliente/LEIA-ME.md) |
| `src/usage_limits.py`, `src/frontend/usage-limits.*` | screen time per category, weekday and required learning |
| `src/site_logins.py`, `src/frontend/site-logins.*` | automatic site logins (passwords in `~/.config/cozy-kids-launcher/site-logins.json`) |
| `src/frontend/escolha.*` | the Learn/Hobbies/Play screen |
| `src/sites/phet.html` | PhET subject picker |
| `src/frontend/cozy-temas.css`, `themes/*.svg`, `themes/fonts/` | new themes |
| `src/frontend/locales/pt.json` | translation |
| `beni/bin/` | app shortcuts, `cozy-itch-sync`, `navegador-jogos`, `cozy-iniciar` … → `~/.local/bin` |
| `beni/firefox/` | uBlock Origin, site CSS and Firefox policies (`/etc/firefox/policies`) |
| `beni/sistema/` | the system part (`instalar-sistema.sh`: packages, Firefox, filtering DNS) and the automatic updater (`beni-atualizar` + systemd services) |
| `beni/ferramentas/migrar-config.py`, `beni/config/migracoes.json` | catalog changes applied once on each laptop |
| `beni/lib/cozy-fixes/` | `nograb.c` (built at install time) and `carregando.py` |
| `beni/cozy-jogos/jogos.py` | SNES/PS1 game list |
| `beni/chromium/cozy-jogo.html` | frame that scales browser games |
| `beni/config/` | initial configuration (profiles, apps, categories, limits) and itch.io collections |
| `beni/emuladores/` | RetroArch, PCSX-R and Luanti settings for weak hardware |
| `beni/systemd/` | itch.io sync timer |
| `beni/ferramentas/` | scripts that generate the theme SVGs |

The code still uses the original's internal names (`cozy-kids-launcher`, port 38431, folders in
`~/.local/share/cozy-kids-launcher`). That keeps it easy to compare with the original project and
bring fixes over.

### Tests
`python3 -m unittest discover -s tests` runs **388 tests**, the original project's tests and the new ones: limits
per category and weekday, categories sharing time, required learning, automatic logins, the updater,
catalog changes, first-run setup, the Windows catalog and the native menu integration. The native menu
has its own Rust tests (`cd cliente && cargo test --release`). Three of the original's tests were
adjusted to the new behavior: already translated text and the `limitBlocked` field.

---

## Publishing an update (for the maintainer)

1. Make the changes in the repository and test on a laptop with `./instalar.sh`.
2. **New or removed games/sites/apps** must go in **two places**:
   - `beni/config/config.json`, which is what a **new** laptop gets;
   - a **migration** in `beni/config/migracoes.json`, which laptops **already handed out** apply, once each. Example:
     ```json
     {"id": "2026-11-01-jogo-x", "descricao": "Jogo X no Passatempo",
      "operacoes": [
        {"op": "adicionar_tile", "perfis": "todos", "depois_de": "kiddogames",
         "tile": {"id": "jogox", "label": "Jogo X", "emoji": "🧩",
                  "cmd": ["special:external-browser:https://exemplo.org/"],
                  "visible": true, "category": "passatempo"}},
        {"op": "remover_tile", "id": "site-antigo"},
        {"op": "atualizar_tile", "id": "phet", "campos": {"visible": false}},
        {"op": "definir", "perfis": ["default"], "caminho": "categoryLimits.totalMinutes",
         "valor": 60, "so_se_ausente": true}
      ]}
     ```
     `perfis` takes `"todos"` (all) or a list of ids (`default` = Beni, `child-2501513b5fcb` = Bea).
     A migration `id` must never repeat.
   - New packages go in `beni/sistema/pacotes-apt.txt` / `pacotes-flatpak.txt`.
3. Bump the number in **`VERSION`** (e.g. `1.1.0`), commit and push.
4. Create the Release with a **tag equal to the version**:
   ```bash
   gh release create v1.1.0 --title "1.1.0" --notes "Jogo X no Passatempo"
   # urgent (an always-on laptop installs it right away, without waiting for a reboot):
   gh release create v1.1.1 --title "1.1.1" --notes "Correção do login [forcar]"
   ```
   The tag must match `VERSION`, or the laptop rejects the package. Drafts and pre-releases are ignored.
   When the Release is published, GitHub Actions builds the native menu (`menu-nativo.yml`, ~15 min) and attaches
   `beni-menu-linux-x86_64` + `.sha256`. Laptops wait up to 90 min for that binary before installing.
5. To follow along on a laptop: `beni-atualizar estado` and `/var/log/beni-atualizar.log`.

The repository address and the overnight window are in `/etc/beni-launcher/atualizar.conf`.

---

## Fixes for old laptops and "rebellious" games
| Problem | Fix |
|---|---|
| No app would open (the ❌ overlay failed) | `python3-tk` is now installed |
| GCompris wouldn't open (`gcompris` vs `gcompris-qt`) | `beni/bin/gcompris` shortcut |
| TuxMath, Pingus etc. **grabbed the mouse** and the ❌ didn't work | `nograb.so` (LD_PRELOAD) cancels SDL 1.2/SDL2's mouse grab |
| SuperTuxKart changed the resolution and **the screen stayed black** after closing | shortcuts always use the current screen resolution |
| Apps that open in a window (Scratch, Klavaro, Klotski) | `cozy-fullscreen` makes them full screen via `wmctrl` |
| After closing an app with the ❌, the next one opened **hidden behind the menu** | the launcher only stays "on top" for a moment |
| Ctrl+Alt+Del locked the screen, which came back black | shortcut and automatic locking turned off |
| The Linux panel showed up when games opened | XFCE panels hidden (they appear with the mouse at the edge) |
| A blinking vertical line in the launcher (Firefox's F7) | caret browsing turned off |
| Esc on a "time's up" message left kids mode | Esc now only closes the message |
| 3D browser games slow in Firefox | browser games open in Chromium with forced acceleration (≈2× the FPS on this hardware) |
| Escola Games' games stuck on "Loading…" with an ad blocker | uBlock only blocks Google's script (the game handles it failing) |
| NetworkManager 1.46's global DNS was ignored | the filtering DNS goes straight into `systemd-resolved` |
| The menu in Firefox took ~600 MB and up to 29% of a core while idle | **native menu** (`cliente/`): ~200 MB, ~1% idle, opens in ~1 s ([details, in Portuguese](../cliente/LEIA-ME.md)) |
| The launcher script used ~18% of a core all the time (it started `python3` twice a second), even with a game open | process checks in plain bash: 0.7% |
| The server used ~3% while idle (it re-read and validated the configuration on every request) | configuration and gamepad caches: 0.6% |

The detailed list, file by file, is in [beni/MUDANCAS.md](../beni/MUDANCAS.md) (in Portuguese).

---

## Where it was built and tested

**Linux:**

| | |
|---|---|
| Laptop | Samsung RV419/RV420 (≈2011) |
| CPU | Intel Celeron B800 1.5 GHz, 2 cores |
| Memory | 2.8 GB |
| Graphics | Intel HD Graphics 2000 (Sandy Bridge), OpenGL 3.3 (Mesa 25.0) |
| Screen | 1366×768 |
| Network | Atheros AR9285 (Wi-Fi only, **no Bluetooth**) |
| System | **Linux Mint 22.3 "Zena" XFCE** (Ubuntu 24.04 base), kernel 6.14, X11 session |
| Browsers | Firefox 146 (launcher and sites) · Chromium 155 from Flathub (browser games) |
| Python | 3.12 (standard library only) |

**Requirements:**
- Linux Mint XFCE or another Ubuntu 24.04 based distro with XFCE.
- An **X11** session (not Wayland).
- Internet during installation.
- A regular user account for the kids, with automatic login.

On Mint Cinnamon/MATE almost everything works, but the panel and lock tweaks are XFCE specific.

**Windows:** a Windows 10 laptop with an Intel Core i5, Intel HD 4000 + GeForce GTX 660M, 16 GB and
a 2560×1080 ultrawide screen, in a child account without administrator rights. The menu idles at
0% CPU and ~190 MB.

---

## Known limitations
- Browser games take 10 to 50 s to open on a Celeron. Heavy 3D games run under 10 FPS and were hidden.
- The PS1 emulator (PCSX-R) is old. RetroArch's `pcsx_rearmed` core would be better, but it isn't in Ubuntu's repositories.
- **Automatic logins**:
  - Only work with e-mail/username and password accounts (not "Sign in with Google").
  - If a site changes its login page, `src/site_logins.py` needs adjusting.
  - The password is protected only by file permissions, not encrypted. Protect the parents' area with a PIN.
- The filtering DNS may block a harmless site. To turn it off, see `beni/MUDANCAS.md`.
- `src/index.html` (and other files with text) already ship in pt-BR; they are no longer a `{{…}}` template. The original `scripts/install.sh` still works, but the recommended way is `instalar.sh`.
- Commercial ROMs are not provided. Use copies of your own discs/cartridges or homebrew games.
