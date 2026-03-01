# Roadmap: sideshell

## Current State (v1.0.0)

- ✅ 17 MCP tools for terminal automation
- ✅ iTerm2 backend (full API support)
- ✅ tmux backend (cross-platform)
- ✅ TUI control (arrow keys, F1-F12, navigation keys)
- ✅ Cursor position tracking
- ✅ Window positioning (iTerm2)
- ✅ Full documentation (README, API.md, CHANGELOG, CONTRIBUTING)

---

## Phase 1: TUI Control (Current Focus)

### 1.1 Completed
- [x] Arrow keys (up/down/left/right)
- [x] Function keys (F1-F12)
- [x] Navigation keys (home/end/pageup/pagedown)
- [x] Cursor position in read_terminal
- [x] Window positioning (set_window_frame, get_window_frame)
- [x] Arrange windows (tiled/horizontal/vertical)
- [x] Broadcast input to multiple sessions

### 1.2 In Progress
- [ ] Mouse control (click at x,y coordinates)
- [ ] Simplified window commands:
  - `arrange` - tile all windows
  - `optimize` - resize window to fit content
  - `windowed` - convert tabs to windows
  - `tabbed` - merge windows into tabs
  - `fullscreen` - toggle fullscreen

### 1.3 Planned
- [ ] Triggers - react to terminal output patterns (regex → action)
- [ ] Annotations - add notes to terminal text for debugging

---

## Phase 2: Advanced Features

### 2.1 Triggers (High Value for AI)
React to patterns in terminal output:
```
Pattern: "error|Error|ERROR"  →  Action: highlight, notify AI
Pattern: "Password:"          →  Action: pause, ask user
Pattern: "y/n"                →  Action: read context, decide
```

### 2.2 Annotations
Add notes to terminal output:
- Mark important lines during debugging
- AI can annotate errors with explanations
- Navigate between annotations
- Export annotated sessions

### 2.3 Shell Integration
- Detect prompts automatically
- Track command exit codes
- Command timing/duration
- Working directory tracking

---

## Phase 3: Multi-Backend Support

### 3.1 Backend Status
| Backend | Status | Platform |
|---------|--------|----------|
| iTerm2 | ✅ Full | macOS |
| tmux | ✅ Full | Cross-platform |
| WezTerm | 🔲 Planned | Cross-platform |
| Kitty | 🔲 Planned | Cross-platform |
| Windows Terminal | ⚠️ Use tmux | Windows |

### 3.2 Backend-Specific Features
| Feature | iTerm2 | tmux | WezTerm | Kitty |
|---------|--------|------|---------|-------|
| Window positioning | ✅ | ❌ | 🔲 | ❌ |
| Triggers | 🔲 | ❌ | ❌ | ❌ |
| Annotations | 🔲 | ❌ | ❌ | ❌ |
| Broadcast input | ✅ | ✅ | 🔲 | 🔲 |
| Color presets | ✅ | ⚠️ | 🔲 | 🔲 |

---

## Phase 4: AI Integration

### 4.1 Smart Features
- [ ] Auto-context: send relevant terminal output to AI
- [ ] Error detection and explanation
- [ ] Command suggestions based on errors
- [ ] Project-aware session management

### 4.2 Safety
- [ ] Command allowlist/denylist
- [ ] Dangerous command warnings
- [ ] Audit logging
- [ ] Rate limiting

---

## Version Milestones

| Version | Focus | Features |
|---------|-------|----------|
| 1.0.0 | Initial release | 17 tools, iTerm2 + tmux |
| 1.1.0 | TUI control | Mouse, simplified window commands |
| 1.2.0 | Triggers | Pattern → action automation |
| 1.3.0 | WezTerm | Third backend |
| 2.0.0 | AI features | Smart suggestions, auto-context |

---

## Known Limitations

1. **Window positioning** - iTerm2 only (tmux is terminal-agnostic)
2. **Triggers** - iTerm2 only (native feature)
3. **Windows Terminal** - Recommend using tmux backend
4. **Focus detection** - Can be flaky with rapid window switches

---

## Contributing

Looking for contributors in:
1. **WezTerm backend** - Cross-platform window control
2. **Kitty backend** - kitten-based integration
3. **Mouse control** - SGR mouse protocol implementation
4. **Documentation** - Tutorials, videos
