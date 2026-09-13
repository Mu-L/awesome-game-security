# Detection And Forensics

## Detection at the PCIe Layer

### Configuration Integrity

Use supported, permitted observations of device identity, capability structure,
OS-assigned resources, and advertised functions. Compare with the exact device
contract and a matched baseline; document unavailable or inaccessible fields.
Collection should not modify another driver's configuration registers.

### BAR and Register Evidence

Distinguish OS-reported BAR resources from device-specific register contents.
A zero or unexpected value may reflect reset, power state, a missing driver,
unsupported functionality, or collector scope. Establish register semantics and
which actor owns access before interpreting it as a conformance failure.

### Configuration Ownership and Consistency

Assess consistency from existing traces, device documentation, owned-source
review, and documented platform interfaces. Windows retains control of PCI
headers and capabilities. A generic collector is not entitled to toggle bus
mastering, payload size, MSI state, or reserved bits to classify live devices.
Any separately designed device validation must respect the owning driver and
platform lifecycle. See [configuration and containment boundaries](assurance-boundaries.md).

### LTSSM and Link-State Validation
```
Sample PCIe Express Capability Link Status over time:
- Negotiated Width (Link Status[9:4]): consistent with donor deployment
  and FPGA hard block capability
- Current Link Speed (Link Status[3:0]): track slot's actual speed
- A device can legitimately train below its maximum capability; compare the
  result with slot topology, platform policy, signal quality, and matched donor
  deployments
- DLL Active (Link Status[13]): should be 1 during operation
- Slot Clock Config (Link Status[12]): match real common-clock state
```

### ASPM Behavioral Validation
```
Real devices claiming ASPM exhibit characteristic L0 ↔ L1 transitions.

Spoofed device anomalies:
- Claims and enables ASPM but shows no expected transition under a workload,
  policy, and observation window known to exercise it
- Transitions with exit latency inconsistent with claimed value
- Does not reach L1.1/L1.2 when donor, platform, firmware policy, and workload
  are verified to enable those substates

Sample Link Status "DLL Active" bit over time + PMC counters.
```

### AER Baselining
```
- Departure from donor baseline: per-silicon correctable-error footprint
  should be stable. Implausibly clean (zero correctables when donor
  normally produces Bad TLP / Replay Timer Timeout) is anomalous.
- Implausible Header Log content (default/zeroed values)
- Inconsistent UR/CA responses to probes of unimplemented offsets
```

### Completion Latency Fingerprinting
```
Completion latency can reflect memory, arbitration, buffering, power state,
link, driver, and workload behavior. A simplistic BRAM-backed emulator may show
lower variance, but real and emulated distributions can overlap.

Detection signal is distribution shape, not absolute mean.

Statistical methods:
- Kolmogorov–Smirnov test: compare empirical CDFs
- Tail estimators where sample size and distributional assumptions support them
- Anderson-Darling test: sensitive to tail differences

Choose the sample size from power/variance analysis, collect under controlled
conditions, compare with a matched donor reference, and validate any decision
threshold on held-out devices.

Random jitter alone need not reproduce donor behavior. Compare mean, variance,
tails, modes, autocorrelation, and responses to condition changes.
```

### MSI/MSI-X Behavioral Validation
```
A device with MSI enabled, programmed Address/Data, an attached driver, and a
verified interrupt-producing condition should produce interrupts:

- Zero interrupts when driver should exercise device = anomalous
- Uniform arrival times may indicate a timer-driven generator, but legitimate
  periodic workloads must be excluded
- Implausibly bursty patterns not matching donor class

Monitor via OS interrupt accounting, ETW/performance telemetry,
driver counters, kernel instrumentation.
```

### Cheat-Phase Access Pattern Recognition
```
One possible workflow has a broad discovery phase followed by narrower,
periodic reads during use. Implementations can cache, randomize, batch, or avoid
these phases, and legitimate devices can also show periodic access.

Candidate execution features:
  Temporal periodicity, address-space breadth, and alignment to game-frame
  intervals, calibrated against matched benign device/workload behavior.

Distinguishing features:
- Fano factor
- Autocorrelation at frame intervals
- Address-space coverage entropy

Decoy observations require a defined collector and access path. An EPT event
records processor access under the active EPT policy; device DMA requires
separate remapping/fault or platform evidence. Server events have their own
application semantics. Do not attribute one collector's event to another layer.
```

### Hot-Plug and Link Disruption Events
```
Firmware swaps and donor reconfigurations require link renegotiation.
Three observable signals:

1. AER Surprise Down — uncorrectable fatal error logged when link
   drops unexpectedly mid-session.

2. Slot Status hot-plug events — Presence Detect Changed,
   Data Link Layer State Changed, MRL Sensor Changed.
   Register via IoRegisterPlugPlayNotification with
   EventCategoryTargetDeviceChange or EventCategoryDeviceInterfaceChange.

3. LTSSM re-training cycles — Link Training bit toggling,
   transient Recovery state.

A device that surprise-downs then reappears with subtly different
Config Space (adjusted MSI layout, different latency profile,
different VID/DID) = fingerprint of mid-session firmware reload.
```

## Detection at the IOMMU Layer

### Fault-Rate Monitoring
```
Sample per-device fault counters from IOMMU fault-recording structure
(VT-d Fault Recording Registers, AMD-Vi Event Log) or from WHEA.

Pipeline:
1. Snapshot baseline at session start
2. Sample at intervals; compute per-device fault rate
3. Threshold-trigger additional PCIe probing on devices exceeding baseline
4. Aggregate evidence across signals before action
```

### Domain Assignment Audit
```
Walk IOMMU domain assignments for anomalies:
- Devices on passthrough/identity domains when strict mode is active
- Devices in unexpectedly large IOMMU groups (poor ACS topology)
- Multiple devices sharing Domain ID when they shouldn't
```

### ACS Topology Verification
```
Walk PCIe bridge topology between every endpoint and root complex.
For each bridge with ACS Capability:
- Verify Source Validation (SV) enabled
- Verify Translation Blocking (TB) enabled
- Verify P2P Request Redirect (RR) and Completion Redirect (CR) enabled

Missing or disabled ACS can limit isolation where peer routing is possible.
Assess the complete topology, root-complex behavior, firmware policy, and actual
IOMMU grouping before calling it an exploitable isolation hole.
```

### IOMMU as Containment Primitive

Containment is a platform/driver responsibility. Record the authorized policy
owner, affected device hierarchy, existing mappings, in-flight work, recovery
path, and evidence that the requested isolation completed. Remapping, bus-master
state, and downstream-port containment have different prerequisites and scope;
none has an effectiveness guarantee derived from a firmware tier.

Use supported OS-managed device lifecycle and isolation controls. Do not instruct
a generic game-security driver to rewrite another device's PCI configuration or
IOMMU ownership. Preserve evidence and evaluate availability impact before an
authorized response; restriction is separate from misconduct attribution.
[Platform ownership and containment](assurance-boundaries.md)

## Forensic Evidence Capture

### What to Capture
```
Artifact                     Source                          Purpose
──────────────────────────────────────────────────────────────────────────────
Supported config snapshot    OS PCI interface                Device identity and collection scope
Capability chain walk        Parsed from config              Capability presence
PCIe link state history      Link Status over session        LTSSM anomaly evidence
MSI/MSI-X arrival timeline   OS interrupt telemetry          Rate claim refutation
AER correctable counts       AER capability registers        Baseline outlier evidence
IOMMU fault log entries      WHEA/ETW, Driver Verifier       Invalid-DMA evidence
IOMMU domain assignments     IOMMU manager state walk        Passthrough anomaly
ACS bridge state             Bridge enumeration              Isolation assessment
Protected-page CPU event    Hypervisor EPT event evidence   CPU access-policy observation
Device DMA fault evidence    Platform/IOMMU collector        Device request-policy observation
TPM quote and measurement log Attestation provider           Selected-measurement appraisal
MCFG / DMAR / IVRS tables   ACPI subsystem                  Platform config baseline
SMBIOS slot inventory        DMI subsystem                   Slot-population audit
BIOS version + patch level   SMBIOS                          Pre-Boot DMA fix verify
Latency-distribution hists   Per-session sampling            Statistical fingerprint
```

### Multi-Signal Correlation
```
Strongest evidence packages combine:
1. Hardware-layer signal (config space, BAR, link state)
2. Behavioral-layer signal (interrupt distribution, IOMMU fault rate, honeypot)
3. Temporal correlation (hardware signal preceded behavioral by plausible interval)

No signal count guarantees a target false-positive rate. Establish independence
or model dependence, validate the joint decision rule on representative benign
systems, and report confidence bounds plus expected appeal volume.
```

### PCIe Protocol Captures
```
A PCIe protocol analyzer (interposer) can provide high-fidelity evidence at its
observation point: TLP-level captures with analyzer-specific timestamp accuracy.

Commercial analyzers capture every TLP, DLLP, and physical-layer ordered set.
Traces can be replayed to confirm fingerprinting findings.

Cost and deployment complexity limit routine use. For high-impact cases,
protocol-level captures from an independent lab can materially strengthen the
record, but capture coverage, analyzer configuration, and interpretation still
need validation.
```

## Thunderbolt / USB4 DMA

### Attack Surface
```
- Thunderbolt 1-4 / USB4 provide direct PCIe tunneling
- Hot-plug capable: device can be attached at runtime
- Pre-boot DMA: device has memory access before OS loads
- Thunderbolt Security Levels:
  - SL0 (None): no security, legacy mode
  - SL1 (User Auth): user must approve new devices
  - SL2 (Secure Connect): device must match previously approved UUID
  - SL3 (No PCIe tunneling): completely disables DMA
```

### Thunderbolt-Specific Attacks
```
- Thunderclap: malicious Thunderbolt peripherals bypass IOMMU
- Device re-identification: change UUID to bypass SL2
- OS-level Thunderbolt driver vulnerabilities
- PCIe tunneling through USB4 hubs
```

### Defensive Measures
```
- Kernel DMA Protection (Windows 10 1803+): automatic IOMMU for hot-plug
- Thunderbolt firmware verification
- Platform-level: BIOS setting to disable Thunderbolt PCIe tunneling
- macOS: T2 chip enforces DMA restrictions on Thunderbolt ports
```

## Shadow CR3 / Split TLB

### Page Table Manipulation
```
- Maintain two sets of page tables (two CR3 values):
  - "Clean" CR3: legitimate page tables visible to anti-cheat
  - "Shadow" CR3: modified page tables with cheat-accessible mappings
- Swap CR3 before/after anti-cheat inspection windows
- Combine with EPT manipulation for hypervisor-level split
```

### Split TLB Techniques
```
- Desync instruction TLB (iTLB) and data TLB (dTLB):
  - Execute code from one physical page
  - Read data from another physical page at same virtual address
- Requires precise TLB invalidation control
- Hypervisor can create EPT-based split: execute on page A,
  read on page B, at same GPA
- Anti-cheat mitigation: TLB flush + re-walk, serializing instructions
```

## Memory Access Techniques

### Physical Memory Reading
```c
// Typical pcileech API usage
HANDLE hDevice;
BYTE buffer[0x1000];
pcileech_read_phys(hDevice, physAddr, buffer, sizeof(buffer));
```

### Virtual Address Translation
```c
// Walk page tables: PML4 → PDPT → PD → PT → Physical
PHYSICAL_ADDRESS TranslateVA(UINT64 cr3, UINT64 virtualAddr) {
    UINT64 pml4e = ReadPhys(cr3 + PML4_INDEX(virtualAddr) * 8);
    UINT64 pdpte = ReadPhys(PFN(pml4e) + PDPT_INDEX(virtualAddr) * 8);
    UINT64 pde = ReadPhys(PFN(pdpte) + PD_INDEX(virtualAddr) * 8);
    UINT64 pte = ReadPhys(PFN(pde) + PT_INDEX(virtualAddr) * 8);
    return PFN(pte) + PAGE_OFFSET(virtualAddr);
}
```

### DTB (Directory Table Base) Finding
```
- Scan physical memory for valid CR3 values
- Look for kernel structures
- Use signature scanning
- Validate page table entries
```

## Security Considerations

### Ethical Use
```
- Security research only
- Authorized testing environments
- Responsible disclosure
- Legal compliance
```

### Risk Awareness
```
- Physical hardware access required
- Potential system instability
- Detection by advanced anti-cheat
- Legal implications
```
