# CS:GO Legacy — Custom Game Coordinator / Matchmaking Reverse-Engineering Notes

> 中文原文见 [`README.md`](README.md)（Chinese original）。本文件是英文版，内容同步。

What it actually took to make the **"Play Competitive"** button on **CS:GO Legacy**
(archived appid `4465480`) drop you into a real match.

This is not a turnkey product. It is a **case-closed write-up plus reusable tooling**:
how far it got, which paths worked, which paths were *refuted by evidence*, and the pile of
small tools built along the way.

This was my first reverse-engineering project done with AI assistance, so there are still
bugs in places — if you know this stuff better, please fix them.

## Background

The official Game Coordinator for CS:GO Legacy is long gone, so clicking "Competitive" does
nothing at all. This project wires up a working chain:

- **Client side** — inject `csgc.dll` into `csgo.exe` (funchook intercepts the Steam API) and
  patch the launcher
- **Coordinator side** — a custom GC written in JavaScript (listening on `127.0.0.1:3257`)
  plus a TCP forwarder
- **Game server** — Linux `srcds` (running in a VM, `LD_PRELOAD` appid patch)

## Status

| Stage | Status |
|---|---|
| Linux `srcds` boots, client connects directly | **working** |
| Custom GC handshakes with client, full matchmaking protocol | **working** |
| **Clicking "Play Competitive" drops you into a match** | **working** |
| Repeated matchmaking into servers within one game process | **working** |
| "Match is ready" popup (CS2 styling + sound + timing) | **working** |

Full chain after the button press:

```
Click "Play Competitive"
  → GC receives MatchmakingStart, sends 9104/9107
  → csgc picks up 9107 in RetrieveMessage (contains server_address)
  → party.js polls mmqueue=reserved, dispatches the official ServerReserved event
    (map name prefixed with '@')
  → official popup appears in "announcement/casual" form, auto-readies and closes after 1.9s
  → at 2.6s csgc stuffs "connect <ip>:<port>" into the engine command buffer
    (execute flag = 2)
  → engine main thread executes it → connected
```

## ★ Full match flow: working (2026-09-29)

```
Click "Play Competitive" → auto-ready → auto-connect
  → server loads lobby_mapveto (the veto lobby map) → lobby warmup window
  → pick/ban maps (client-side UI, fully operable) → pick starting side
  → the Map veto pick controller entity on the server changelevels to the picked map
  → normal match
```

Verified end-to-end: BP selected `de_ancient`; server log showed
`Map veto pick controller: pick = de_ancient` → `initiating level transition to de_ancient`
→ `*** Map Load: de_ancient`, followed by normal team assignment, match start, and a full
round played out.

### Scope (important — read before filing issues)

| Dimension | Scope |
|---|---|
| **Server** | **Linux `srcds` only.** The level-change patch (`tools/srvfix.c`) hardcodes offsets into `engine.so` (32-bit ELF); Windows is not applicable |
| **Client build** | Build **1575** (`ClientVersion 1575` / `PatchVersion 1.38.8.1` / 2023-10-12) — the **final legacy CS:GO client** |
| **Mode** | ★ **Only the Prime queue is implemented. Competitive/casual and other modes are not** |
| Hardcoded offsets | Located against build **1575** (CS:GO no longer updates, so the build is frozen; other branches/regional builds still need re-locating) |

### What had to change

**1. srcds launch parameters** (fully annotated in [`tools/start-srcds.sh`](tools/start-srcds.sh))

| Parameter | Why |
|---|---|
| `+sv_lan 0` | Real Steam identity (needs a GSLT). Cost: a non-zero reservation cookie, worked around by srvfix |
| `+game_type 0 +game_mode 1` | competitive. **Must be explicit** — under the default casual, the veto lobby map is not in its `mapgroupsMP`, so mapgroup association fails (`mapgroup` empty in `status`) and the in-map lobby logic never activates |
| `+map lobby_mapveto` | **The starting map must be the veto lobby map.** Note: which map the server loads is **not** determined by the GC's 9106 `map` field — it is this `+map` |
| `-nowatchdog` | Otherwise, after players connect and the map finishes loading: `Watchdog timer exceeded, aborting!` (exit code 134) |

**2. `csgo_srvfix.so`** ([`tools/srvfix.c`](tools/srvfix.c)) — reservation cookie bypass ·
level-change detour · **make the stub page executable** (mmap'd pages are NX; jumping into
one always crashes) · NOP out `Cbuf_Execute` on non-main threads · blank the invalid
mode name `reserved`

**3. Coordinator side** ([`tools/gc-local-changes.patch`](tools/gc-local-changes.patch))

- 9106 was missing `account_ids`: that block referenced two variables that do not exist and
  threw a `ReferenceError` every single time, so it had **never executed** → the server
  rejected every connection with `reserved(yes), clients(no)`
- ★ **9107's `preMatchData.draft` changed from an empty array to an object**: in the proto it
  is a `CDataGCCStrike15_v2_TournamentMatchDraft` object. Passing `[]` is a type mismatch, and
  protobufjs **silently drops it** → the client never receives a draft →
  `MatchDraftAPI.GetDraft()` never equals `'ingame'` → **the pick/ban UI never appears**.
  (The same trap had already been fixed once on the server side in 9105; the client-side 9107
  was missed.)

### Three counter-intuitive points (all learned the hard way)

- The veto lobby map is decided by the **`+map` launch parameter**, not by the map field the
  GC sends down
- In-match pick/ban is a **client-side** feature (`MatchDraftAPI` lives in `client.dll`; no
  draft strings exist anywhere in the server module). But the **level change is server-side** —
  the `Map veto pick controller` entity changelevels on its own, with no GC involvement
- That 5-minute "warmup" comes from `mp_warmuptime 300` in `gamemode_competitive.cfg`. You can
  override it with `csgo/cfg/gamemode_competitive_server.cfg` (the file does not exist by
  default but is still exec'd, and it runs *after* the mode cfg, so it wins)

### Not done yet

- Automated pick/ban (completing veto without touching the UI)
- The "confirming match" state does not clear after a successful match

---

## The real blocker: the server's reservation cookie

In the server's `engine.so` (32-bit, `Addr == Off`), the check starting at `0x1d0776`:

```asm
mov 0x2ec(%esi),%eax        ; the server's own reservation cookie
xor  ...                    ; compared against the cookie in the client's connect packet
je  1d2790                  ; equal → let them in
or  %ebx,%ecx
je  1d2790                  ; ★ server cookie == 0 → also let them in
                            ; otherwise → kick (#Valve_Reject_Reserved_For_Lobby)
```

An `sv_lan 0` srcds obtains a **non-zero** reservation cookie from Valve, while the client
carries the GC-issued `Hello :)` (`0x293A206F6C6C6548`). They never match → the connection is
silently refused.

**Solution: run srcds with `sv_lan 1`** — without a Steam login there is no cookie, it stays 0,
and the permissive branch is taken.

> The log line `-> Reservation cookie 0:  reason reserved(yes), clients(no), reservationexpires(0.00)`
> — that **`0` is a hardcoded constant**, and the line is **only printed when the server cookie
> is non-zero**. It is in fact *evidence that the cookie is non-zero.* Early on this sent us off
> editing the GC's `GC_COOKIE` — the exact wrong direction.

### Another trap: connect, get kicked, reconnect forever

Under `sv_lan 0`, the connection handler contains a whole block for "server already reserved →
start the match immediately" that runs `nextlevel <map>` + `map <map> reserved` +
`Cbuf_Execute` → **every connection reloads the level**, kicking the client, which auto-reconnects
→ reloads again → infinite loop. It does not trigger under `sv_lan 1`. To go back to `sv_lan 0`
you need `tools/srvfix.c` (LD_PRELOAD, NOPs that map command at runtime).

## The step that makes the connection actually happen

**The core is `Cbuf_AddText(engine.dll+0x1DB910)`, and the execute flag must be `2`.**

The engine's command execution path has an `FCVAR_CLIENTCMD_CAN_EXECUTE` check that only lets
through commands "typed by the player themselves". The decision is based on a source flag:

| Entry path | Flag value | Result |
|---|---|---|
| Player console → direct execution | `2` | allowed |
| `IVEngineClient::ClientCmd` → Cbuf | `0/1` (booleanized by `setne`) | **rejected** |
| **Drive `Cbuf_AddText` directly with flag 2** | `2` | **allowed** |

`ClientCmd` cannot be used because it collapses the flag into a boolean (the `setne cl` in the
disassembly). Bypassing it and calling `Cbuf_AddText` directly from a small assembly stub
(`ecx` = buffer index, `edx` = string, flag pushed on the stack, caller cleans up) gets the
correct value through.

This has a bonus: the command is executed by the **engine main thread**, exactly the same path
as a player typing it, so it is inherently safe.

## Two things that definitively do not work (both crash-tested)

| Approach | Result |
|---|---|
| Calling the `connect` command body (`engine.dll+0xDA6A0`) from csgc's own thread | That function touches UI; V8 immediately throws `Fatal: HandleScope::CreateHandle0`. Even when caught by `__try` it leaves corruption behind and crashes later during map load |
| Hooking Panorama's event dispatch (`panorama.dll+0x417F0`) | Disrupts the event pump (thousands of pending events pile up in one frame), then `eip` jumps to an unmapped address and crashes |

## Crash source: lobby callbacks

The crash stack pointed inside `SteamAPI_RunCallbacks`, with `eip` outside any module. Root
cause was leftover code from csgc's early "trick the engine into a lobby" approach:

- `RequestLobbyOnce()` called `CreateLobby` proactively; its `LobbyCreated` callback blew up
  inside `SteamAPI_RunCallbacks`
- `InstallMatchmakingVtableHooks()` forwarded `ISteamMatchmaking`'s vtable to steamclient with
  mismatched arguments (those hook slots were inferred from SDK headers, never validated
  against the real vtable)

Both are disabled now (`return`ed out). That whole approach had already been proven useless —
the engine never calls `ISteamMatchmaking`; connections now go through `Cbuf`.

## The accept popup (done)

> The early conclusion "this popup cannot be closed" was **wrong**, corrected here:
> `<PopupCustomLayout>` lacks the `PopupPanel` class, but
> `$.DispatchEvent("PanoramaComponent_Lobby_ReadyUpForMatch", false, 0, 0)` closes it fine.
> The real trap was **poking its child panels from JS at runtime**, which corrupted UI state
> (first all keybinds stopped working, then a crash).

Final approach (all resources in `code.pbin` are plain-text zip — directly editable):

- **Display** — `party.js` polls `LobbyAPI.GetSessionSettings().game.mmqueue`; when it flips to
  `reserved`, dispatch the official `ServerReserved` event with a **`@` prefixed to the map
  name** — that is the switch for the official "announcement-style auto-ready" mode
  (`map.charAt(0) === '@'` in `popup_accept_match.js`). This buys three things at once:
  - the popup takes the CS2-like form (title + mode·map only), the official `auto` style
  - `m_hasPressedAccept` is set true → the countdown uses the quiet `waitquiet`
    (**this is why casual mode has no beep**)
  - after 1.9s the official `_OnNqmmAutoReadyUp` runs on its own: plays
    `mm_success_lets_roll`, calls `LobbyAPI.SetLocalPlayerReady('deferred')`, closes the popup
    via the official path
- **Sound** — the engine normally plays the "match ready" sound when it throws `ServerReserved`.
  Since we throw the event ourselves, we must play `popup_accept_match_found`
  (`game_ready_02.wav`) ourselves
- **Slimming the panel** — added inline `visibility:collapse` to `id-map-draft-phase-teams`
  (fake lineup) and `accept-match__slots-count` (the 0/10 counter row). **Hide only, never
  delete the nodes** — the popup's JS calls `RemoveAndDeleteChildren()` /
  `SetDialogVariableInt()` / `RemoveClass()` against those ids, and missing nodes throw and
  corrupt the UI (`tools/patch_popup.py`)
- **Size** — both places must change together (`tools/patch_popup_css.py` + `tools/patch_popup.py`)
  - `.accept-match__map` height 300px → 150px
  - **the outer box must be pinned inline**: add
    `style="min-width: 620px; height: 278px;"` to `<Panel class="accept-match__bg">`
  > Trap: changing only the map height has **no effect** — that layer's CSS is
  > `height: fit-children`, and the background is a video (`videos/gobutton.webm`), so the
  > panel height does not follow content in practice (stuck at 480). You must pin the outer
  > size with an inline style to compress it to casual's ~270px.

> An official bug for the record: `mm_success_lets_roll.wav` **plays twice** in the official
> CS2/CS:GO client (`_OnNqmmAutoReadyUp` and another path each play it once). Our implementation
> plays it once — to reproduce official behaviour, add another
> `popup_accept_match_confirmed` in `party.js`'s `_closePopup()`.

## Layout

```
tools/
  appidfix.c              LD_PRELOAD patch: bypass the engine's rejection of the archived appid
  fix_stack.py            in-place PE header edit (stack reserve size / LARGE_ADDRESS_AWARE)
  run_cdb_attach.bat      attach cdb to a Steam-launched game (attach only, never launch)
  start-srcds.sh          script to start srcds inside the VM
  add_backtrace.py        add call-stack capture to a hook
  rebuild_gc.py           rebuild GC-side handlers
  readd_validate.py       restore Server2GCClientValidate

  # static analysis (32-bit PE, located by RVA — ASLR-independent)
  disasm.py               disassemble an RVA range with capstone, annotate jump targets
  xref.py                 cross-references: dword pointers (vtables/IAT) + rel32 call/jmp across .text
  rdstr.py                dump strings at an RVA / search strings and report RVAs
  pbin_tool.py            code.pbin read/write (ls / get / put, preserves the 16-byte header and zip comment)

  # VPK
  vpk_get.py              extract a single file from a pak01 VPK (read-only)
  vpk_extract.py          bulk-extract a VPK by filter (default sound/, ~24k entries, ~3.8 GB)
  pbin_ls.py              list the JS inside panorama's code.pbin (plain-text zip)

  # server-side runtime patches (LD_PRELOAD into srcds, modifies engine.so)
  srvfix.c                only needed under sv_lan 0: NOPs the map command in "reserved start"
  srvre.py                ELF32 section/string locator (the server's engine.so is 32-bit ELF;
                          note Addr == Off, so file offset is the vaddr)

  # client resource/source patch generators (always read back to verify after pbin_tool.py put)
  make_party.py           generates party.js: trigger, close, sound, timing all live here
  patch_popup.py          slims popup_accept_match.xml (hides fake lineup/counter, keeps every id)
  patch_popup_css.py      compresses popup height (.accept-match__map 300px -> 150px)
  patch_rearm.py          edits csgc source: clear the one-shot connect flag on 9101
  patch_delay.py          edits csgc source: connect delay 8s -> 5s -> 2.6s
```

> Editing C++ under `csgc-src` **must be done with byte-level replacement** (the files are GBK;
> MSVC reads them as codepage 936). Do not use an editor that decodes and re-encodes. After
> building, copy `dist/csgc/csgc.dll` to `<game dir>/csgc/csgc.dll`.

> The game paths in these scripts are hardcoded; when moving machines, edit the `PATH` / `GAME`
> constants at the top.

## Techniques worth remembering

- **cdb must *attach*, never launch the game.** Starting `csgo.exe` directly from the debugger
  makes Steam think it did not launch it, the client enters an insecure state, and the
  matchmaking button is disabled.
- **Let `OutputDebugString` exceptions through**: `sxd 40010006; sxd 4001000a`, otherwise the
  log is drowned.
- **Never `timeout`-kill an attached cdb** — the debugged game dies with it.
- **Watch source encodings**: the C++ side is GBK (MSVC reads 936), the GC's JS is UTF-8. Do not
  mix them.
- **Preserve `code.pbin` structure**: 16-byte `PAN\x02` header + a standard zip (all 726 entries
  `compress=0` stored) + a trailing zip comment. Always read back and verify, and confirm the
  XML/JS parses — one missing `>` breaks the whole resource.
- **Finding Panorama sound names**: sound events are defined in `scripts/game_sounds_ui_panorama.txt`
  inside the VPK, and `PlaySoundEffect` takes the *event* name (with a `UIPanorama.` prefix),
  not the filename. E.g. `UIPanorama.popup_accept_match_found` → `UI/panorama/game_ready_02.wav`.

## Related projects

Parts of this project referenced or used these upstream / sibling projects:

- **[mikkokko/csgo_gc](https://github.com/mikkokko/csgo_gc)** — also a custom GC for CS:GO legacy,
  using funchook to intercept the Steam API and replace the launcher. **It is the authoritative
  reference for messages like `9164`** (the reservation cookie used throughout this project,
  `0x293A206F6C6C6548`, comes from its `gc_const_csgo.h:6 GameServerCookieId`, matching the
  `"Hello :)"` literal). Note: **it does not implement matchmaking** — in `gc_shared.cpp`,
  9101/9103/9107 exist only as a name table with no handlers, so there was no existing reference
  for this layer and it had to be reversed from scratch.
- **[aka3257/CSGO-GC-Replacement](https://github.com/aka3257/CSGO-GC-Replacement)** and
  **[aka3257/csgc](https://github.com/aka3257/csgc)** — the origin of the external JS GC and the
  client injection framework (`csgc.dll`) used here.
- **[eonexdev/csgo-sv-fix-engine](https://github.com/eonexdev/csgo-sv-fix-engine)** — reference
  implementation for the archived-appid rejection (ships a prebuilt `.so`); we ended up writing
  our own `tools/appidfix.c`.

## Contributors

**DeepSeek** — reverse-engineering analysis and debugging (cdb breakpoints, disassembly,
GC-side patches)

## Note

Intended solely for **compatibility research on self-hosted servers / offline environments**.
All testing was done on non-VAC-secure self-hosted servers. Do not use this on official servers.

## LICENSE

GNU GPL 3.0 — full text in [`LICENSE`](LICENSE).

This project is a derivative work, not an original implementation:

- [`gc/Server_v3.js`](gc/Server_v3.js) is modified from `Server_v3.js` in
  **[aka3257/CSGO-GC-Replacement](https://github.com/aka3257/CSGO-GC-Replacement)**
  (author aka3257, GPL 3.0) — the GC-side changes are archived in
  [`tools/gc-local-changes.patch`](tools/gc-local-changes.patch)
- The client injection framework `csgc.dll` comes from
  **[aka3257/csgc](https://github.com/aka3257/csgc)** (also GPL 3.0)
- The static-analysis, VPK/Panorama and server-patch tooling under `tools/` is original
  to this project

The repository as a whole is therefore distributed under GPL 3.0. Using it in a
closed-source context requires an exception from the upstream author first.
