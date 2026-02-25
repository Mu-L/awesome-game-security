---
name: anti-cheat-systems
description: Guide for understanding anti-cheat systems and bypass techniques. Use this skill when researching game protection systems (EAC, BattlEye, Vanguard), anti-cheat architecture, detection methods, or bypass strategies.
---

# Anti-Cheat Systems & Analysis

## Overview

This skill covers anti-cheat systems used in games, their detection mechanisms, and research techniques. Understanding anti-cheat helps both defenders (game developers) and security researchers.

## Major Anti-Cheat Systems

### Easy Anti-Cheat (EAC)
- Kernel-mode driver protection
- Process integrity verification
- Memory scanning
- Used by: Fortnite, Apex Legends, Rust

### BattlEye
- Kernel driver with ring-0 access
- Screenshot capture capability
- Network traffic analysis
- Used by: PUBG, Rainbow Six Siege, DayZ

### Vanguard (Riot Games)
- Always-on kernel driver
- Boot-time initialization
- Hypervisor detection
- Used by: Valorant, League of Legends

### Valve Anti-Cheat (VAC)
- User-mode detection
- Signature-based scanning
- Delayed ban waves
- Used by: CS2, Dota 2, TF2

### Other Systems
- **PunkBuster**: Legacy FPS anti-cheat
- **FairFight**: Server-side statistical analysis
- **nProtect GameGuard**: Korean anti-cheat solution
- **XIGNCODE3**: Mobile game protection
- **ACE (Tencent)**: Chinese market protection

## Detection Mechanisms

### Memory Detection
```
- Signature scanning for known cheats
- Code integrity verification
- Injected module detection
- Memory modification monitoring
```

### Process Detection
```
- Handle enumeration
- Thread context inspection
- Debug register monitoring
- Stack trace analysis
```

### Kernel-Level Detection
```
- Driver verification
- Callback registration monitoring
- System call hooking detection
- PatchGuard integration
```

### Behavioral Analysis
```
- Input pattern analysis
- Movement anomaly detection
- Statistical improbability flagging
- Network packet inspection
```

## Anti-Cheat Architecture

### User-Mode Components
- Process scanner
- Module verifier
- Overlay detector
- Screenshot capture

### Kernel-Mode Components
- Driver loader
- Memory protection
- System callback registration
- Hypervisor detection

### Server-Side Components
- Statistical analysis
- Replay verification
- Report processing
- Ban management

## Research Techniques

### Static Analysis
1. Dump and analyze AC drivers
2. Reverse engineer detection routines
3. Identify signature patterns
4. Map callback registrations

### Dynamic Analysis
1. Monitor system calls
2. Track driver communications
3. Analyze network traffic
4. Debug with hypervisor tools

## Bypass Categories

### Memory Access
- Physical memory read/write
- DMA-based access
- Hypervisor memory virtualization
- Driver-based access

### Code Execution
- Manual mapping
- Thread hijacking
- APC injection
- Kernel callbacks

### Detection Evasion
- Signature mutation
- Timing attack mitigation
- Stack spoofing
- Module hiding

## Security Features Interaction

### Windows Security
- Driver Signature Enforcement (DSE)
- PatchGuard/Kernel Patch Protection
- Hypervisor Code Integrity (HVCI)
- Secure Boot

### Virtualization
- VT-x/AMD-V detection
- Hypervisor presence checks
- VM escape detection
- Timing-based detection

## Ethical Considerations

### Research Guidelines
- Focus on understanding, not exploitation
- Report vulnerabilities responsibly
- Respect Terms of Service implications
- Consider impact on gaming communities

### Legal Aspects
- DMCA considerations
- CFAA implications
- Regional regulations
- ToS enforcement

## Resources Organization

### Detection Research
```markdown
- Anti-cheat driver analysis
- Detection routine documentation
- Callback enumeration tools
```

### Bypass Research
```markdown
- Memory access techniques
- Injection methods
- Evasion strategies
```

### Tools
```markdown
- Custom debuggers
- Driver loaders
- Analysis frameworks
```

---

## Data Source

**Important**: This skill provides conceptual guidance and overview information. For detailed information use the following sources:

### 1. Project Overview & Resource Index

Fetch the main README for the full curated list of repositories, tools, and descriptions:

```
https://raw.githubusercontent.com/gmh5225/awesome-game-security/refs/heads/main/README.md
```

The main README contains thousands of curated links organized by category. When users ask for specific tools, projects, or implementations, retrieve and reference the appropriate sections from this source.

### 2. Repository Code Details (Archive)

For detailed repository information (file structure, source code, implementation details), the project maintains a local archive. If a repository has been archived, **always prefer fetching from the archive** over cloning or browsing GitHub directly.

**Archive URL format:**
```
https://raw.githubusercontent.com/gmh5225/awesome-game-security/refs/heads/main/archive/{owner}/{repo}.txt
```

**Examples:**
```
https://raw.githubusercontent.com/gmh5225/awesome-game-security/refs/heads/main/archive/ufrisk/pcileech.txt
https://raw.githubusercontent.com/gmh5225/awesome-game-security/refs/heads/main/archive/000-aki-000/GameDebugMenu.txt
```

**How to use:**
1. Identify the GitHub repository the user is asking about (owner and repo name from the URL).
2. Construct the archive URL: replace `{owner}` with the GitHub username/org and `{repo}` with the repository name (no `.git` suffix).
3. Fetch the archive file — it contains a full code snapshot with file trees and source code generated by `code2prompt`.
4. If the fetch returns a 404, the repository has not been archived yet; fall back to the README or direct GitHub browsing.

### 3. Repository Descriptions

For a concise English summary of what a repository does, the project maintains auto-generated description files.

**Description URL format:**
```
https://raw.githubusercontent.com/gmh5225/awesome-game-security/refs/heads/main/description/{owner}/{repo}/description_en.txt
```

**Examples:**
```
https://raw.githubusercontent.com/gmh5225/awesome-game-security/refs/heads/main/description/00christian00/UnityDecompiled/description_en.txt
https://raw.githubusercontent.com/gmh5225/awesome-game-security/refs/heads/main/description/ufrisk/pcileech/description_en.txt
```

**How to use:**
1. Identify the GitHub repository the user is asking about (owner and repo name from the URL).
2. Construct the description URL: replace `{owner}` with the GitHub username/org and `{repo}` with the repository name.
3. Fetch the description file — it contains a short, human-readable summary of the repository's purpose and contents.
4. If the fetch returns a 404, the description has not been generated yet; fall back to the README entry or the archive.

**Priority order when answering questions about a specific repository:**
1. Description (quick summary) — fetch first for concise context
2. Archive (full code snapshot) — fetch when deeper implementation details are needed
3. README entry — fallback when neither description nor archive is available
