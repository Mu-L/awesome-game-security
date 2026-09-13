# Iommu And Defense

## IOMMU Architecture

### Translation Flow
```
1. Device issues Memory TLP with target IOVA.
   TLP header carries 16-bit Requester ID (BDF).
2. TLP travels upstream through switches/bridges to root complex.
3. IOMMU intercepts, uses Requester ID to look up translation context.
4. IOMMU walks device's I/O page tables: IOVA → physical address.
5. Permission bits (Read, Write) checked against access type.
6. Success: TLP forwarded with translated physical address.
7. Failure: fault logged, device receives UR or CA completion.
```

### Intel VT-d Internals
```
Two-level table lookup:

BDF → Root Table (256 entries, 16B each, indexed by Bus)
    → Context Table (256 entries, 16B each, indexed by Dev:Func)
      → Second-Level Page Tables (3–5 levels)
        → Final 4 KB physical page

Context Entry fields:
- SLPTPTR: Second-Level Page Table Pointer
- Domain ID: 16-bit (multiple devices can share a domain)
- AW: Address Width (3/4/5-level = 39/48/57-bit IOVA)
- T: Translation Type (untranslated-only, translated-only, or both)
- P: Present
- FPD: Fault Processing Disable

Page table entries (PTE, EPT-like format):
[0]      R - Read permission
[1]      W - Write permission
[7]      PS - Page Size (1=leaf super-page, 0=next-level table)
[N-1:12] Physical address of next-level table or 4 KB page

Super-pages: level-2 leaf = 2 MB, level-3 leaf = 1 GB.

Scalable Mode (VT-d 3.0+):
Context Entry → PASID Directory → PASID Table → per-PASID
first-level page-table roots. Enables Shared Virtual Memory (SVM).
Check RTADDR_REG.TTM to determine which mode is in effect.
```

### AMD-Vi Internals
```
Single-level Device Table indexed directly by BDF:

BDF → Device Table Entry (32 bytes)
    → I/O Page Tables (1–6 levels)
      → Final page

DTE encodes:
- Page Table Root Pointer
- Mode (0–6, selects paging levels)
- Domain ID (16 bits)
- IR, IW — Default Read/Write permission
- GV — Guest Valid (nested translation)
- PASID-related fields

Page sizes: 4 KB, 2 MB, 1 GB.
```

### IOTLB and Invalidation
```
Translations cached in IOTLB (I/O Translation Lookaside Buffer).
When mappings change, IOTLB must be invalidated.

Two distinct caches when ATS is in use:
- IOMMU's own IOTLB
- Device-side TLB (DevTLB) caching prior translations

Full invalidation with ATS requires:
1. IOMMU invalidates own IOTLB
2. IOMMU sends ATS Invalidate Request Message to device
3. Device drops affected DevTLB entries, replies with Invalidate Completion

If step 2 or 3 is skipped, device retains stale translations
and can DMA to unmapped addresses.

VT-d invalidation granularities:
- Global: flush entire IOTLB
- Domain-Selective: flush all entries for a Domain ID
- Page-Selective: flush specific IOVA range in a domain

Strict vs lazy invalidation:
Lazy mode defers IOTLB invalidation, batching them for performance.
Opens a window where stale translations remain valid — a device
whose driver has unmapped a buffer can still DMA to the old IOVA.
```

### Fault Recording
```
VT-d: Fault Recording Registers — circular array capturing
  Requester ID, faulting IOVA, fault reason, TLP type.

AMD-Vi: Event Log Buffer — producer-consumer ring buffer of
  IO_PAGE_FAULT, INVALID_DEVICE_REQUEST, ATS-related events.

Both surface faults via interrupts and event-log entries.
On Windows, some IOMMU violations observable through WHEA/bug-check
paths and Driver Verifier DMA-violation telemetry.

Per-device fault rate is one of the most operationally useful
IOMMU-layer signals, but its baseline is platform-, device-, driver-, firmware-,
and workload-specific. Sustained faults show failed or invalid DMA requests;
driver bugs, resets, stale mappings, or hardware faults must be excluded before
attributing malicious out-of-domain access.

RMRR/IVMD:
ACPI DMAR table contains RMRR (Reserved Memory Region Reporting)
sub-tables declaring physical ranges devices need identity-mapped.
AMD-Vi has analogous IVMD (I/O Virtualization Memory Definition)
in the IVRS table. A defender should enumerate these and reject
configurations where suspect BDFs appear in RMRR scope or
RMRR ranges overlap game memory regions.
```

## IOMMU Topology and Isolation

### IOMMU Groups
```
Devices in the same IOMMU group may not be safely isolated from
one another. Group membership determined by:
- PCIe topology — devices behind a switch share a group
  unless the switch supports and enables ACS
- ACS state of upstream bridges
- Quirks for known-broken hardware

Linux: /sys/kernel/iommu_groups/N/devices/
Windows: equivalent constraints but no simple public group filesystem
```

### ACS (Access Control Services, Extended Cap ID 0x000D)
```
ACS is a PCIe capability that switches/root ports advertise
to declare they can enforce isolation between downstream ports.

ACS Capability register enable bits:
Bit  Feature                      Effect
0    Source Validation (SV)        Drop TLPs with wrong Requester ID
1    Translation Blocking (TB)    Block AT=10 (Translated) TLPs
2    P2P Request Redirect (RR)    Force P2P requests upstream for IOMMU
3    P2P Completion Redirect (CR) Force P2P completions upstream
4    Upstream Forwarding (UF)     Forward upstream regardless
5    P2P Egress Control (EC)      Allow/deny P2P routing per-port
6    Direct Translated P2P (DT)   Allow P2P with translated addresses

Critical for untrusted endpoints: SV, TB, RR, and CR.
A switch missing Source Validation lets a malicious device spoof
its Requester ID, defeating per-BDF IOMMU translation.
A switch missing P2P Request Redirect allows devices on the same
switch to DMA directly to each other without IOMMU involvement.
```

### Peer-to-Peer DMA
```
Devices on the same PCIe tree can send Memory TLPs directly to
each other's BAR ranges without involving system memory.
Without ACS redirection, peer traffic may remain below the root complex and
bypass the host IOMMU translation path. Routing behavior is topology- and
platform-specific, so confirm it with the actual root complex and switches.

Plausible P2P DMA targets for cheat:
- GPU framebuffer — rendered game state
- Network adapter ring buffers — game traffic
- USB controller queues — input device data

Mitigation: ACS Translation Blocking + P2P Request Redirect
on every intermediate bridge. Defender must walk topology and
confirm both bits are active.
```

### Interrupt Remapping
```
MSI/MSI-X interrupts are Memory Writes to 0xFEE00000–0xFEEFFFFF.
Without Interrupt Remapping (IR), any device with Bus Master enabled
can write to this range and trigger arbitrary interrupts — NMIs, SMIs,
or vectors targeting wrong CPU.

With IR enabled, IOMMU validates MSI/MSI-X writes and uses
remapping-table state to determine permitted destination.
IR is part of VT-d's broader DMA Remapping architecture.
Both VT-d and AMD-Vi have integrated equivalents.
Both should be mandatory in any anti-cheat threat model.
```

## ATS, PASID, and Address Translation Trust

### ATS (Address Translation Services, Extended Cap ID 0x000F)
```
ATS lets a device cache IOMMU translations locally:
1. Device issues Translation Request TLP (AT=01) with IOVA
2. IOMMU translates and responds with Translation Completion
   carrying physical address
3. Device caches translation in Device-side TLB (DevTLB)
4. Subsequent accesses issued with AT=10 (Translated) —
   IOMMU bypasses page-walk, trusting device's cached translation
5. On mapping changes, IOMMU sends Invalidation Request

Attack surface: malicious device claiming ATS can present
arbitrary AT=10 TLPs whose addresses were never approved
by the IOMMU. The IOMMU forwards them trusting the device's claim.
```

### PASID (Extended Cap ID 0x001B)
```
Extends ATS to per-process address spaces. 20-bit PASID carried
in a TLP Prefix. IOMMU uses (Requester ID, PASID) jointly
to select translation context.

PASID enables Shared Virtual Memory (SVM) — primarily found in
datacenter NICs, AI accelerators. Presence on a consumer card
is anomalous.
```

### ATS Trust Model and "ATS Untrusted" Mode
```
The fundamental trust assumption: device honestly reports
translations it has been granted. Unreasonable for external
Thunderbolt enclosures, FPGAs in M.2 slots, or untrusted
accelerator cards.

Modern OS/IOMMU stacks can treat endpoints as ATS-untrusted:
ATS is disabled, blocked by policy, or stripped.
Linux: pci=noats plus per-device quirks.
Windows: Kernel DMA Protection / DMAGuard matters, but don't
treat "Kernel DMA Protection: On" as proof every internal
endpoint is ATS-untrusted. Verify ATS state per endpoint.
```

## Driver–IOMMU Contract and Bypass Catalog

### Legitimate DMA Path (Windows)
```
1. Acquire DMA adapter: IoGetDmaAdapter / WDF wrapper
2. Allocate buffer: MmAllocateContiguousMemorySpecifyCacheNode
   or WdfCommonBufferCreate
3. Map for DMA: AllocateCommonBuffer / MapTransferEx
   - OS allocates IOVA from device's domain
   - Creates IOMMU page-table entries: [IOVA, IOVA+size) → physical pages
   - Returns IOVA to driver
4. Program device: driver writes IOVA into device's BAR registers
5. Device DMAs: TLPs arrive at IOMMU with BDF + IOVA
6. IOMMU translates: page-walk produces physical address
7. Completion and unmap: teardown IOMMU entries + IOTLB invalidation

In this model, device can DMA only to addresses the driver
explicitly mapped. Game memory is not in that range.
```

### Six Paths to Out-of-Domain Access
```
1. IOMMU not active or not applied to this path
   VT-d/AMD-Vi disabled, OS not enforcing, device outside protected ports

2. Pre-boot DMA injection
   Inject before IOMMU initialized; requires firmware-level exploit

3. Identity-mapped / passthrough domains
   Legacy drivers request 1:1 mapping; modern strict-mode rejects it

4. Driver mapping over-allocation (Thunderclap class)
   OS maps full 4 KB page when buffer is smaller; adjacent kernel data exposed

5. Legitimate-path data exfiltration
   Cheat spoofed as NIC; OS network stack passes game packets through
   NIC's RX ring buffer (legitimately IOMMU-mapped). Cheat reads game data
   without leaving allowed mappings. Undetectable at IOMMU layer.

6. IOMMU page-table manipulation via kernel compromise
   BYOVD / vulnerable driver reprograms IOMMU tables.
   Requires code execution on gaming PC.

Approaches 1–3 are the foundation of most current DMA cheats.
```

### IOMMU Bypass Catalog (16 Techniques)
```
#   Technique                   Mechanism                           Mitigation
─────────────────────────────────────────────────────────────────────────────────
1   IOMMU disabled              VT-d/AMD-Vi off in BIOS             Refuse misconfigured platforms
2   Pre-boot DMA                Firmware leaves injection window     UEFI updates; verify ACPI indicators
3   Identity/passthrough        1:1 IOVA-to-physical mapping        Strict-mode IOMMU policy
4   Driver over-allocation      Full 4 KB page, adjacent data       OS bounce buffers; strict mappings
5   ATS abuse                   AT=10 TLPs with arbitrary addrs     ATS Untrusted mode for non-allowlisted
6   ACS missing on bridge       P2P or spoofed Requester ID         Verify ACS state on all bridges
7   Lazy IOTLB invalidation    Stale translations valid briefly    Strict invalidation mode
8   FLR race                    FLR/Hot Reset race window           Synchronized FLR handling
9   SMM bypass                  SMM code exempt from IOMMU          Boot Guard / Platform Secure Boot
10  DMA-remapping driver bugs   Bugs in OS IOMMU manager            OS patching
11  Hypervisor trust failure    Compromised hypervisor              Platform remediation; boot evidence is not runtime proof
12  Interrupt injection (no IR) Write arbitrary interrupts           Mandatory IR enforcement
13  RMRR/IVMD scope abuse       Fake ACPI tables cover attacker     Measured boot; runtime RMRR audit
                                physical ranges
14  Snoop-bit manipulation      Stale cache lines visible           Strict snoop enforcement
15  PASID confusion             Misconfigured PASID Table           PASID-aware IOMMU programming
16  DMAR/IVRS spoofing          Compromised firmware, fake tables   Measured boot covering firmware

Techniques 1–6: active attack surface for current commercial DMA cheats
Techniques 7–13: academic, APT, firmware-level contexts
Techniques 14–16: largely theoretical
```

## Hypervisor-Level Defense

### EPT-Based Memory Protection

EPT supplies a processor-side guest-physical to host-physical translation and
permission boundary. A violation concerns an access governed by the active EPT
policy. IOMMU remapping supplies the separate device-to-memory boundary; an EPT
trap is not direct evidence of a PCIe DMA request.

A trusted hypervisor can own both policies, but verify each path independently.
Protection depends on correct region coverage, page lifetime, backing-memory
isolation, and trusted policy/configuration interfaces. A guest CPU permission
change alone establishes no device-DMA coverage. Hypervisor presence and effects
may be observable; operating outside the guest kernel does not imply invisibility.
[CPU, DMA, and hypervisor assurance](assurance-boundaries.md)

### VBS, HVCI, and VTL Split

VBS and memory integrity strengthen isolation of kernel code-integrity decisions.
They do not grant arbitrary third-party drivers a VTL 1 extension interface or
make every signed driver safe. Review documented integration and the effective
vulnerable-driver policy separately; blocklist coverage has limits.

Record platform support, configured policy, services actually running, and
compatibility evidence. Kernel DMA Protection does not require VBS, and per-device
DMA remapping can be enabled independently of the overall feature. Select an
explicit deployment baseline for the product instead of treating every security
feature as a universal requirement or its absence as misconduct.
[Feature and deployment boundaries](assurance-boundaries.md)

### SMM Considerations
```
System Management Mode (Ring -2) runs in SMRAM, isolated from
the OS. SMM CPU memory accesses are not mediated by the device IOMMU, but
accessible data still depends on platform protections, memory encryption,
firmware design, and virtualization context.

A vulnerable SMI handler = path to arbitrary memory access
without IOMMU mediation.

Mitigations:
- Intel Boot Guard / AMD Platform Secure Boot (firmware signatures)
- SMI Transfer Monitor (STM): hypervisor-resident, treats SMM as
  constrained guest; availability and deployment are platform-specific
- Runtime verification of SMM lockdown registers
```

### PCIe IDE (Integrity and Data Encryption)
```
IDE adds link-level TLP protection: integrity (MAC-based, required)
and confidentiality (encryption, optional).
Incorporated into PCIe 6.0 base specification.

Valuable against: physical link interposers, malicious retimers/switches,
traffic tampering.

NOT a DMA-cheat silver bullet: cheat installed as the endpoint
still originates legitimate IDE-protected TLPs after key establishment.
IDE raises the bar for passive bus sniffing but endpoint identity,
IOMMU policy, ACS topology, ATS policy, and attestation remain required.
```

## External Trust Anchors

### TPM Measurements and PCR Profiles

A TPM supports protected keys and measurement reporting. Record the actual TPM
implementation, PCR bank, platform profile, and selected measurements. PCR reset
and extend rules are profile-dependent; a universal extend-only table is
inaccurate. Resolve measurement meaning from the applicable profile and event
log, rather than assigning one fixed PCR layout to every system.

### Remote Attestation Evidence

Review key enrollment, verifier trust anchors, signature validity, expected
qualifying data, PCR selection/digest consistency, event-log consistency, and
the appraisal policy. An attestation key's trust chain depends on the enrollment
scheme; it does not automatically terminate at a TPM manufacturer certificate.

A valid quote supports the selected measurements under that trust model. It does
not establish the absence of a DMA-capable device or authenticate every current
IOMMU mapping. Separate accepted boot evidence, unsupported measurement coverage,
and verified runtime state in the report.

### DRTM and Secure Launch

Secure Launch uses DRTM during startup to establish a measured execution path.
Do not describe this as an arbitrary post-boot application launch or assume that
one PCR comparison verifies every security component. Record platform support,
launch state, applicable measurement profile, and appraisal policy.

### Pre-Boot DMA Evidence

Firmware's pre-boot isolation responsibilities and Windows runtime DMA policy
are distinct. Microsoft's OEM contract specifies a PCR 7 event when relevant
DMA protections are disabled or reduced. Interpret its presence or absence only
against the applicable contract and a trustworthy measurement/event-log path.
ACPI indicators describe platform capabilities and policy inputs, not a complete
snapshot of live IOMMU mappings.

Sources and verification limits: [attestation and platform contracts](assurance-boundaries.md).

## Layered Detection Pipeline

### Pre-Game Environmental Verification

Record supported, configured, and observed-running state separately for device
remapping, interrupt remapping, Secure Boot, VBS/memory integrity, and attestation.
Bind requirements to a documented product/platform policy. Assess firmware update
applicability and relevant topology; absence from a known-issue list is not proof
that firmware has no vulnerabilities. Unsupported or unavailable evidence should
remain explicit, with compatibility and recovery paths defined.

### PCIe Inventory Pass
```
- Enumerate all PCIe devices via PnP tree
- Supported configuration snapshot, recording readable span and missing fields
- Check device problem codes (DEVPKEY_Device_ProblemCode)
- Cross-reference SMBIOS slot inventory with populated devices
```

### Configuration Integrity Per Device
```
- VID/DID/SVID/SDID against known-good list
- Capability-chain walk and validation
- Signature-residue scan
- OS-reported BAR/resource consistency
- Configuration consistency from permitted observations
- Compare against per-donor reference database
```

### Behavioral Sampling During Play
```
- Periodic Link Status reads (LTSSM, ASPM transitions)
- AER counter snapshots
- Per-device interrupt rate and distribution
- Per-device IOMMU fault rate
- BAR-region content sampling for class consistency
```

### Statistical Analysis Over Session
```
- Latency distribution comparison (KS test, Hill estimator)
- Interrupt arrival distribution
- ASPM transition rate
```

### Cheat-Phase Detection
```
- Honeypot region access
- Memory access frequency / locality classifiers
```

### Containment Before Verdict
```
Each detection produces evidence, not a verdict.
Verdict informed by:
- Multi-signal correlation with measured joint error rates; correlated
  signals can share the same false-positive cause
- Server-side aggregation across sessions
- Behavioral verification (input timing, gameplay statistics)

Any authorized containment must use the established OS/platform owner and
verify its actual scope and completion. EPT CPU permissions and device DMA
isolation are different controls; neither implies a guaranteed real-time outcome.
```

Apply [`research-rigor`](../../research-rigor/SKILL.md) when converting these
signals into a claim or response. Validate baselines per device, firmware,
platform, topology, driver, and power state; preserve raw captures and test
benign alternatives before attribution.

### Realistic Limits

A passing identity or behavioral check establishes consistency only in the
observed dimensions. A denied DMA request establishes the enforced boundary
for that request; it does not classify every device or actor. A valid attestation
result covers its selected measurements and appraisal policy, not all current
memory access.

Choose complementary controls for independently identified trust gaps. External
attestation can support boot-state confidence but is not a universal solution to
unobserved runtime activity. Report coverage, missing evidence, shared failure
modes, and measured error rates instead of an evasion checklist or a claim that
one device class requires a particular detector.

Layered protection may increase attack cost; the magnitude and economic effect
remain deployment-specific claims requiring evidence.
