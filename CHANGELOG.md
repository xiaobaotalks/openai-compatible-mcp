# Changelog

All notable changes to `openai-compatible-mcp` are documented here. Versions
follow [Semantic Versioning](https://semver.org/).

## [0.2.21] - 2026-06-17

### Fixed (Codex config rewrite)
- **Provider rename**: `openai_compatible_mcp` → `openai_compatible`. Codex
  CLI 0.140+ reserves the `openai` prefix for built-in providers, so any
  custom provider whose name starts with `openai` triggers the error
  *"model_providers contains reserved built-in provider IDs: `openai`"*.
- **Stop writing `[mcp_servers.X]` by default**: When the wizard is used with
  Codex CLI (or any client that can talk to a running HTTP endpoint directly),
  launching a second `openai-compatible-mcp` sub-process via MCP causes a
  30-second `startup_timeout_sec` stall. Direct API mode (Codex → local proxy
  at `127.0.0.1:7878/v1`) avoids this entirely. The wizard still writes
  `[mcp_servers.X]` for Claude Desktop / Cursor / Claude Code (stdio MCP).
- **Use `api_key = "sk-..."` directly** instead of `experimental_bearer_token`.
  Codex 0.140+ still accepts both, but the latter is deprecated.

### Fixed (config cleanup)
- **Fixed model-line deduplication bug**: prior versions used `re.subn(...)`
  to *replace* all `model = "..."` lines with the new value — but if the file
  already had two `model =` lines, this turned them into two identical
  *new* lines, leaving duplicates. v0.2.21 first **strips all** `model =` /
  `model_provider =` lines, then **inserts exactly one** of each.
- **New `_strip_any_section(text, regex)` helper**: removes every section
  matching a regex, including all child sub-sections. Used to clear *any*
  `[model_providers.X]` and `[mcp_servers.X]` blocks regardless of name, so
  a re-Apply of the wizard never leaves duplicate sections behind.

## [0.2.20] - 2026-06-17

### Fixed
- `from . import __version__` raised `ImportError: attempted relative import
  with no known parent package` when the wizard was launched as a top-level
  script (e.g. `python wizard.py` in dev repos, or some IDE run-configs).
  Now the version import tries `.` first, then absolute, then hard-coded
  fallback — never NameError.

## [0.2.19] - 2026-06-17

### Fixed
- Wizard crashed immediately on startup with
  `NameError: name 're' is not defined` because v0.2.18's
  `_strip_invisible_chars` used a module-level `re` but `import re` was still
  inside the function it replaced. Now `import re` is at module top.
- **Port fallback**: if 8989 is busy (e.g. old wizard didn't shut down), the
  new wizard tries 8990..8998 and opens the browser to the chosen port.

## [0.2.18] - 2026-06-17

### Fixed
- **Real root cause of `Error loading config.toml: line 2:1: invalid
  unquoted key`**: a single ZWNBSP (U+FEFF) embedded as a regular character
  on line 2 of the user's `~/.codex/config.toml`. v0.2.16/17 only stripped a
  UTF-8 BOM at byte 0 of the file, not invisible characters in the middle of
  the text. v0.2.18 strips **all** of: C0/C1 control chars, soft hyphen,
  ZWSP/ZWNJ/ZWJ, LRM/RLM, LSEP/PSEP/NNBJ, math invisibles, ZWNBSP, specials,
  language tags.

## [0.2.17] - 2026-06-17

### Fixed
- **Three-layer BOM defense**: strip on read, strip on merge, strip on write.
  Any one of them missing would let a UTF-8 BOM slip through and break
  TOML parsing in Codex.
- **Written-by marker**: the wizard now prefixes every written config with
  `# written by openai-compatible-mcp vX.Y.Z (utf-8, no BOM)` so a user can
  open the file and immediately see which wizard version produced it.
- **Version number injected into wizard HTML title**, so opening
  <http://127.0.0.1:8989> shows e.g. `openai-compatible-mcp v0.2.17 · ...`
  in the browser tab — a sanity check that you're not running an old
  cached wizard.

## [0.2.16] - 2026-06-16

### Fixed
- Wizard no longer fails with `invalid unquoted key` when the existing
  `~/.codex/config.toml` starts with a UTF-8 BOM. PowerShell's
  `Set-Content -Encoding UTF8` adds a BOM, and the wizard was passing it
  through to `_atomic_write_text`, which the Codex TOML parser rejected.

## [0.2.15] - 2026-06-16

### Fixed
- Wizard's `_strip_toml_section` was removing only the main `[mcp_servers.X]`
  block, leaving child sections like `[mcp_servers.X.env]` orphaned. On the
  next re-Apply these would be re-added *on top of* the existing ones,
  producing `duplicate key "OPENAI_COMPATIBLE_MCP_API_KEY"` errors. The
  stripper now also removes every `[mcp_servers.X.*]` child.

## [0.2.14] - 2026-06-15

### Fixed
- Codex 0.140+ deprecates `wire_api = "chat"` and silently falls back to
  a non-streaming mode that loses tool calls. Wizard now writes
  `wire_api = "responses"` (which our local proxy `D:\AItext\codex\proxy`
  already supports via its `/v1/responses` route).

## [0.2.13] - 2026-06-14

### Added
- Initial Codex CLI support. Wizard now writes `~/.codex/config.toml`
  (in addition to Claude Desktop / Cursor) and **merges** with any existing
  sections rather than overwriting the file.

## [0.2.12] and earlier

Pre-Codex wizard releases. The wizard configured Claude Desktop and Cursor
only. See git history for details.
