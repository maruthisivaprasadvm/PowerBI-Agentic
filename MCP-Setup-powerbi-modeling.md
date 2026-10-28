# Start the `powerbi-modeling` MCP Server in VS Code

Complete instructions to **install (if missing), configure, and activate** Microsoft's
**Power BI Modeling MCP server** in VS Code so the BPA agent can read your `.pbix` model.

> **TL;DR — one click:** run [`setup/setup.bat`](setup/setup.bat) (double-click) or
> `powershell -ExecutionPolicy Bypass -File setup/Install-PowerBIModelingMCP.ps1`.
> It checks prerequisites, installs the server **if it isn't already installed**, and prints
> the activation steps. The manual steps below are the same thing, by hand.

Source project: <https://github.com/microsoft/powerbi-modeling-mcp>

---

## 0. Prerequisites (checked by the script)

| Requirement | Check | If missing |
|---|---|---|
| **Windows** | — | Required (Power BI Desktop is Windows-only). |
| **Power BI Desktop** | opens `.pbix` | Install from Microsoft Store / download. |
| **Node.js 22+** | `node --version` | `winget install OpenJS.NodeJS.LTS` |
| **VS Code** | `code --version` | Install VS Code + add `code` to PATH. |

The setup script will **not** silently install Node.js — it tells you if it's missing (per the
chosen setup scope). Everything else it handles.

---

## 1. Install the MCP server (only if not already installed)

The script uses **auto-detect**: it prefers the official VS Code extension and falls back to the
zero-install npx registration.

### Method A — VS Code extension (preferred)
Extension id: **`analysis-services.powerbi-modeling-mcp`** (marketplace: *Power BI Authoring MCP*).

```bat
:: check if already installed
code --list-extensions | findstr /i "analysis-services.powerbi-modeling-mcp"

:: install latest if missing
code --install-extension analysis-services.powerbi-modeling-mcp --force
```

### Method B — npx fallback (zero install, always latest)
Already wired into this project via [`.mcp.json`](.mcp.json):

```json
{
  "mcpServers": {
    "powerbi-modeling-mcp": {
      "type": "stdio",
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@microsoft/powerbi-modeling-mcp@latest",
               "--start", "--accepteula", "--readonly"]
    }
  }
}
```

`npx -y … @latest` downloads the newest published server on first run — nothing to pre-install.

### Method C — manual VSIX (offline)
Download `…/publishers/analysis-services/vsextensions/powerbi-modeling-mcp/<version>/vspackage`,
rename to `.zip`, extract, and point your MCP client at the extracted `powerbi-modeling-mcp.exe`.
(The script can do A/B automatically; C is a last resort.)

---

## 2. Server flags used (read-only by default)

| Flag | Meaning |
|---|---|
| `--start` | Start the MCP server (required). |
| `--accepteula` | Accept the EULA unattended (also settable via `PBI_MODELING_MCP_ACCEPT_EULA=true`). |
| `--readonly` | **Default here** — inspection only, no writes. |
| `--readwrite` | Enable writes (each write still prompts). Drop `--readonly` to use. |
| `--authmode` | `interactive` (default) or `serviceprincipal`. |
| `--compatibility` | `PowerBI` (default) or `Full` for Analysis Services. |

---

## 3. Activate it

1. **Open your model** in Power BI Desktop (e.g. `powerbi/AI Summaries.pbix`) and keep it open.
2. **Reload VS Code** (`Ctrl+Shift+P` → *Developer: Reload Window*) so the new MCP server /
   extension is picked up. *Newly added MCP servers are not live in an already-running session.*
3. **Confirm the tools are available** — ask the agent:
   > *"List the available powerbi-modeling MCP tools."*
   You should see tools for listing tables / columns / measures / relationships and running DAX.
4. **Connect to the model** (name must match the Power BI Desktop title bar):
   > `Connect to 'AI Summaries' in Power BI Desktop`

You're ready — run the BPA agent (see [`README.md`](README.md) and
[`powerbi/Power BI Agentic Instructions.md`](powerbi/Power%20BI%20Agentic%20Instructions.md)).

---

## 4. Troubleshooting

| Symptom | Fix |
|---|---|
| Tools don't appear | Reload VS Code window; confirm Power BI Desktop is open with the model. |
| `npx` not found | Install Node.js 22+ and reopen the terminal. |
| `code` not recognized | In VS Code: *Shell Command: Install 'code' command in PATH*. |
| EULA blocks start | Ensure `--accepteula` (already in `.mcp.json`) or set `PBI_MODELING_MCP_ACCEPT_EULA=true`. |
| Connects but can't read | Make sure the title-bar model name exactly matches the name in your prompt. |
| Want the agent to fix issues | Remove `--readonly` from `.mcp.json` (re-enables writes, with confirmations). |
