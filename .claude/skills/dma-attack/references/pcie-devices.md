# Pcie Devices

## PCIe Protocol Stack

### Three Protocol Layers
```
Layer              Unit                Function
────────────────────────────────────────────────────────────────
Transaction        TLP                 Memory/IO/Config reads & writes,
                                       completions, messages
Data Link          DLLP                Acknowledgements, flow control
                                       credits, power management
Physical           Ordered Sets        Link training, equalization,
                                       clock recovery

A real device's behavior is shaped by all three layers.
Many FPGA designs primarily customize Transaction-Layer behavior; Physical and
Data Link behavior may retain implementation fingerprints unless the selected
IP, configuration, and surrounding behavior closely match the claimed device.
Whether a fingerprint is usable must be validated on the actual link.
```

### TLP (Transaction Layer Packet) Format
```
Every TLP contains a 3 DW (12-byte) or 4 DW (16-byte) base header; optional
TLP Prefixes may precede it. 4 DW headers are used for 64-bit addresses and
certain message types.

First DWord (DW0) encoding:
Bits       Field         Notes
[31:29]    Fmt[2:0]      Header format + data presence
[28:24]    Type[4:0]     TLP type (combined with Fmt)
[22:20]    TC[2:0]       Traffic Class (default 0)
[18]       Attr[2]       ID-Based Ordering (IDO)
[15]       TD            TLP Digest (ECRC trailer)
[14]       EP            Poisoned data
[13:12]    Attr[1:0]     Relaxed Ordering, No Snoop
[11:10]    AT[1:0]       Address Type (critical for ATS bypass)
[9:0]      Length[9:0]   Payload length in DWords (0x000 = 1024 DW = 4 KB)

Fmt[2:0] encoding:
000 = 3 DW header, no data
001 = 4 DW header, no data
010 = 3 DW header, with data
011 = 4 DW header, with data
100 = TLP Prefix

Key TLP types (Fmt + Type combinations):
Fmt  Type     TLP
000  0_0000   MRd (Memory Read, 3DW / 32-bit addr)
001  0_0000   MRd (Memory Read, 4DW / 64-bit addr)
010  0_0000   MWr (Memory Write, 3DW)
011  0_0000   MWr (Memory Write, 4DW)
000  0_0100   CfgRd0 (Config read — terminate at this device)
010  0_0100   CfgWr0
000  0_0101   CfgRd1 (Config read — forwarded by bridges)
010  0_0101   CfgWr1
000  0_1010   Cpl (Completion without data)
010  0_1010   CplD (Completion with data)
001  1_0rrr   Msg (Message, no data)
011  1_0rrr   MsgD (Message with data)
```

### Detection-Relevant DW0 Fields
```
TC[2:0] — Traffic Class. Default traffic commonly uses TC0, but non-zero TC is
valid when platform and device policy configure it. Compare usage with the
claimed device, driver, and workload rather than flagging it in isolation.

Attr[2:0] — RO/NS/IDO. A device emulating a NIC must follow that NIC's
typical NS/RO usage pattern; mismatches are visible.

AT[1:0] — Address Type:
  00 = Untranslated (IOMMU will translate)
  01 = Translation Request (ATS only)
  10 = Translated (device claims it has already translated via ATS)
This field is the basis of ATS bypass attacks.

TD — TLP Digest. If set, an ECRC trailer is present.
EP — Poisoned. Indicates data is known-bad.
```

### TLP Routing and Requester ID
```
Three routing modes:
- Address routing — Memory and IO TLPs, matched against bridge apertures
- ID routing — Config TLPs and Completions, by BDF
- Implicit routing — Some Messages (broadcast, terminate at root)

DW1 carries the Requester ID (16 bits = Bus:Device:Function, "BDF")
and an 8-bit Tag for matching completions to requests.

Requester ID is a key input to IOMMU lookup, ACS source validation, AER source
identification, and interrupt-remapping policy. If spoofed IDs are accepted
without topology or source validation, per-function isolation can be
undermined; the exact effect depends on the platform and remapping path.

Transaction categories:
- Posted (P) — fire-and-forget (Memory Writes, Messages)
- Non-Posted (NP) — requires completion (Memory Reads, IO/Config R/W)
- Completion (Cpl/CplD) — response to Non-Posted requests

Completion Status codes:
000 = Successful Completion (SC)
001 = Unsupported Request (UR)
010 = Configuration Request Retry Status (CRS)
100 = Completer Abort (CA)

UR vs CA distinction matters for spoofing detection — real silicon
responds differently to malformed config accesses vs accesses to
unimplemented offsets. Many spoofed firmwares hard-code one or the other.
```

### Memory Read Completion Splitting
```
A single Memory Read TLP returns up to Max_Read_Request_Size (MRRS) bytes.
The completer splits the payload at any boundary >= RCB
(Read Completion Boundary, 64 or 128 bytes).
Each fragment cannot exceed Max_Payload_Size (MPS).

Each Completion carries:
- Lower Address[6:0] — lowest 7 bits of first byte address
- Byte Count[11:0] — bytes remaining (last fragment's Byte Count
  equals its own payload length)
- BCM — PCI-X compatibility (typically 0)
- Tag — matches originating MRd's Tag

The split pattern (fragment count, boundary positions) is a
strong fingerprint: real memory controllers produce characteristic
distributions of fragment sizes and inter-fragment gaps.
BRAM-backed emulators producing perfectly uniform 64-byte fragments
at constant cadence are anomalous.
```

### Tag Space and Fingerprinting
```
- 5-bit Tag (original): 32 outstanding non-posted requests per Requester ID
- Extended Tag (PCIe 1.1+, Device Control[8]): 8-bit / 256 outstanding
- 10-Bit Tag (PCIe 4.0+, Device Control 2[12]): 1024 outstanding

Tag turnover discipline — which tags get reissued and how quickly —
reflects the device's internal request tracking pipeline.
Firmware that issues reads with no tag turnover (same tag, or monotonic
beyond negotiated limit) is observably distinct from real silicon.
```

### MPS and MRRS as Fingerprints
```
Record current MPS/MRRS configuration and the responsible platform software;
do not infer the active values solely from advertised link capability.
- Device Capabilities[2:0]: Max_Payload_Size_Supported
  (0=128, 1=256, 2=512, 3=1024, 4=2048, 5=4096 bytes)
- Device Control[7:5]: current MPS (must be <= Supported,
  set to minimum of all devices in hierarchy)
- Device Control[14:12]: Max_Read_Request_Size (same encoding)

The discriminator is donor consistency: a device claiming a donor
that is known to support larger payloads, different tag behavior,
or a different negotiated profile should match that donor under
the same root-port constraints.
```

### Data Link Layer
```
DLLPs provide reliable delivery between Physical and Transaction layers.

DLLP          Purpose
─────────────────────────────────────────
Ack           TLP received correctly
Nak           TLP received with error; sender must replay
InitFC1/2     Flow control credit initialization at link bring-up
UpdateFC      Ongoing flow control credit updates
PM_*          Power management (L0s, L1 entry/exit)
Vendor        Vendor-defined

Flow control credits are per TLP category:
- PH / PD — Posted Header / Data
- NPH / NPD — Non-Posted Header / Data
- CplH / CplD — Completion Header / Data

Negotiated credit values are not generally exposed through standard
Link Capabilities register. They are visible in protocol-level traces,
some root-port/vendor performance counters, or FPGA-side debug.
Useful for lab fingerprinting and forensic captures, not normal
runtime config-space detection.
```

### Physical Layer
```
Two details matter even without PHY-level instrumentation:

LTSSM (Link Training and Status State Machine):
- States: Detect → Polling → Configuration → L0 (operational)
  → L0s, L1, L2 (low-power) → Recovery → Hot Reset → Disabled → Loopback
- Observable via Link Status Register and root-port performance counters

Detection-relevant:
- Negotiated Link Width (Link Status[9:4]):
  Compare with slot wiring, platform policy, signal quality, and matched donor
  deployments; devices can legitimately train below maximum width
- Current Link Speed (Link Status[3:0]):
  A lower negotiated generation is contextual, not a contradiction by itself
- Recovery cycle frequency:
  Comparative signal; materially different from donor reference is anomalous

ASPM (Active State Power Management):
- L0s and L1 are link-level low-power states
- Capability does not imply the platform enabled ASPM; evaluate transitions only
  under verified policy and workload conditions that should exercise them
```

### Configuration Access Mechanisms
```
Two mechanisms on x86:

CAM (Legacy I/O-port path):
1. CPU writes to I/O port 0xCF8 (Bus:Device:Function:Register)
2. CPU reads/writes at I/O port 0xCFC
- Reaches only first 256 bytes
- Still used during early BIOS/UEFI boot

ECAM (Enhanced, MMIO path):
1. Read MCFG ACPI table for segment base addresses
2. Compute: addr = base + ((bus << 20) | (dev << 15) | (func << 12) | offset)
3. OS maps physical address into kernel virtual memory
- Required for Extended Configuration Space (0x100–0xFFF)
- Where AER, DSN, LTR, VSEC, ATS, PASID, SR-IOV live

On Windows, supported paths are:
- IRP_MN_READ_CONFIG / IRP_MN_WRITE_CONFIG
- BUS_INTERFACE_STANDARD.GetBusData / SetBusData
Use documented bus interfaces within the caller's permitted ownership scope.
Direct MCFG mapping is not a supported substitute for the Windows PCI stack;
OS ownership of headers and capabilities still applies.
```

## PCIe Configuration Space

### Legacy 256-Byte Header (Type 0 Endpoint)
```
Offset  Field                    Notes
0x00    Vendor ID (2B)           Chip manufacturer (e.g., 0x8086 Intel)
0x02    Device ID (2B)           Specific product
0x04    Command (2B)             BME (bit 2), MemSpace (bit 1), IOSpace (bit 0)
0x06    Status (2B)              Capabilities List (bit 4)
0x08    Revision ID + Class Code Class triplet: Base / Sub / ProgIF
0x0C    Cache Line / Latency /   Header Type 0x00 = endpoint,
        Header Type / BIST       0x01 = bridge, 0x80 = multi-function
0x10–27 BAR0–BAR5               Memory or I/O windows
0x2C    Subsystem Vendor ID      Often distinguishes board manufacturers
0x2E    Subsystem Device ID
0x30–33 Expansion ROM Base
0x34    Capabilities Pointer     Offset of first capability in linked list
0x3C    IRQ Line/Pin/Min/Max     Legacy INTx routing

BAR encoding (32-bit BAR):
bit 0:    0 = Memory BAR, 1 = I/O BAR
bits 2:1: 00 = 32-bit, 10 = 64-bit (BAR pair)
bit 3:    Prefetchable

BAR sizing belongs to platform enumeration and resource management.
For a collector, compare OS-reported resources with the exact device contract;
do not rewrite a live device's BARs. A size discrepancy requires context about
the device revision, active function, firmware, and collection method.
```

### Capabilities Chain
```
If Status[4] is set, 0x34 points to the first capability.
Each capability has a 2-byte header: [ID | Next].
Next is DWord-aligned in 0x40–0xFF, or 0x00 to terminate.

Common capability IDs:
ID    Capability
0x01  PCI Power Management
0x05  MSI
0x10  PCI Express
0x11  MSI-X
0x12  SATA Configuration
0x13  PCI Advanced Features
0x14  Enhanced Allocation

Detection: walk the chain, validate each capability's declared size
doesn't overlap the next, Next is DWord-aligned and within bounds,
no cycle exists. A malformed chain is itself a signal.
```

### PCIe Express Capability (ID 0x10)
```
The single most important capability for spoofing detection.

Offset  Field                    Notes
+0x02   PCIe Capabilities        Cap Version, Device/Port Type, Slot Impl
+0x04   Device Capabilities      MPS Supported, FLR, Phantom Functions
+0x08   Device Control           MPS current, MRRS, Error Enables
+0x0A   Device Status            CED, NFED, FED, URD, Transactions Pending
+0x0C   Link Capabilities        Max Link Speed/Width, ASPM, L0s/L1 latencies
+0x10   Link Control             ASPM Control, RCB, Link Disable, Retrain
+0x12   Link Status              Current Link Speed/Width, Link Training
+0x24   Device Capabilities 2    Completion Timeout Ranges, AtomicOp,
                                 OBFF, LTR mechanism
+0x28   Device Control 2         Completion Timeout Value, AtomicOp, LTR Enable
+0x2C   Link Capabilities 2      Supported Link Speeds Vector
+0x30   Link Control 2           Target Link Speed, Compliance
+0x32   Link Status 2            De-emphasis, EQ Phase status

Detection leverage per field:
- Device Type (+0x02[7:4]): must match donor's role
- MPS Supported (+0x04[2:0]): hard-IP ceiling contradicts donor
- FLR support (+0x04[28]): verify FLR changes same sticky/non-sticky
  state as claimed donor; naive firmware acknowledges FLR but continues
  unchanged, producing state inconsistent with donor-defined reset semantics
- Link Status (+0x12): Width/Speed are negotiated, observable, hard to
  lie about — hard IP reports what LTSSM actually achieved
- Slot Clock Config (+0x12[12]): must match real platform behavior
- Completion Timeout ranges (+0x24): selecting outside claimed ranges
  is a discriminator
- AtomicOp (+0x24[6-9]): server-class GPUs/NICs may support; FPGA
  support depends on IP generation and configuration; compare advertised and
  exercised behavior with the claimed donor
```

### MSI and MSI-X Capabilities
```
MSI (ID 0x05):
Message Control bits:
  [0]    MSI Enable
  [3:1]  Multiple Message Capable (0–5, representing 1–32 vectors)
  [6:4]  Multiple Message Enable (cannot exceed Capable)
  [7]    64-bit Address Capable
  [8]    Per-Vector Masking Capable

x86 MSI Address: bits [31:20] fixed at 0xFEE (LAPIC prefix)
  [19:12] Destination ID, [3] Redirection Hint, [2] Destination Mode
Message Data: [15] Trigger Mode, [10:8] Delivery Mode, [7:0] Vector

MSI-X (ID 0x11):
- Supports up to 2,048 vectors
- Table stored in BAR-mapped region (not Config Space)
- Each entry: 16 bytes (Addr Low, Addr High, Data, Vector Control)
- PBA (Pending Bit Array): bit-per-vector pending state

Naive MSI-X emulation failures:
- Ignores Vector Control Mask writes
- Sets PBA bits but never clears on unmask
- Returns hardcoded PBA values
- Doesn't retire pending interrupts when masks clear
Detection probe: mask vector → induce interrupt condition →
observe PBA bit → unmask → observe interrupt firing.
A conforming implementation should satisfy the relevant MSI-X semantics;
incomplete emulations may fail, while sophisticated emulations can pass.
```

### AER Extended Capability (ID 0x0001)
```
Three error classes:
- Correctable: Receiver Error, Bad TLP, Bad DLLP, Replay Timer Timeout
- Uncorrectable Non-Fatal: Completion Timeout, Completer Abort, UR, ACS Violation
- Uncorrectable Fatal: Malformed TLP, DLL Protocol Error, Surprise Down

Each has Status (sticky, W1C), Mask, and Severity registers.
Header Log (16B) captures full TLP header of first logged uncorrectable error.

Detection:
- Absence of AER when donor model is known to expose it = mismatch
- Zero correctable-error count over long window when donor's silicon
  normally produces a baseline rate = anomalous
- Anomalous UR response patterns to probes of unimplemented offsets
```

### Extended Capabilities
```
4-byte header at each offset:
[31:20] Next Capability Offset (0 to terminate)
[19:16] Capability Version
[15:0]  Extended Capability ID

Key Extended Capability IDs:
0x0001  AER
0x0002  Virtual Channel (VC)
0x0003  DSN (Device Serial Number, 8 bytes)
0x000B  Vendor-Specific Extended Capability (VSEC)
0x000D  ACS (Access Control Services)
0x000E  ARI
0x000F  ATS (Address Translation Services)
0x0010  SR-IOV
0x0015  Resizable BAR (RBAR)
0x0018  LTR (Latency Tolerance Reporting)
0x001B  PASID
0x001D  DPC (Downstream Port Containment)
0x001E  L1 PM Substates
0x001F  Precision Time Measurement (PTM)

Detection-relevant:
- DSN: 8-byte unique serial; donor-cloned firmware can collide
  with another player's identical card
- VSEC: Xilinx PCIe IP optionally emits VSEC blocks with
  characteristic Vendor ID + VSEC ID combinations
- ATS/PASID/SR-IOV presence on consumer-class donor is
  demographically suspicious — rare outside server-class hardware
```

## FPGA Hardware

### Xilinx PCIe Integrated Block
```
Hardened IP block handling:
- Physical Layer (PHY, 8b/10b or 128b/130b, LTSSM, equalization)
- Data Link Layer (sequence numbers, replay buffer, flow control)
- Transaction Layer framing and parsing
- Subset of Configuration Space

IP core documentation:
- PG054 for 7-series
- PG156 for UltraScale Gen3
- PG213 for UltraScale+ Gen4

User logic interfaces over AXI-Stream (TX/RX) and separate
config management: cfg_mgmt_* (7-series), cfg_ext_* (UltraScale).

Detection consequences:
- Default fingerprints leak through: hard block populates Config Space
  with Xilinx-characteristic byte patterns
- 7-series firmware authors who don't understand cfg_mgmt_* leave
  subtle behavioral differences (some CfgTLPs return hard-block defaults)
```

### FPGA Family Hierarchy
```
Artix-7 (consumer/mid-range, GTP transceivers, PCIe Gen2):
Chip       LUTs      BRAM(Kbit)  PCIe Hard Block
XC7A35T    20,800    1,800       Gen2 x4
XC7A50T    32,600    2,700       Gen2 x4
XC7A75T    46,200    3,780       Gen2 x4
XC7A100T   63,400    4,860       Gen2 x4
XC7A200T   134,600   13,140      Gen2 x4
(Smaller than T35 have no hard PCIe block)

Kintex-7 (high-end, GTX transceivers):
XC7K70T    41,000    4,860       Gen2 x8
XC7K160T   101,400   11,700      Gen2 x8
XC7K325T   203,800   16,020      Gen2 x8 / Gen3 x4
XC7K410T   254,200   28,620      Gen3 x8

Zynq UltraScale+ (ARM Cortex-A53 cores, GTH/GTY):
ZU2EG/CG   ~47,000   ~5.3M      Gen3 x4
ZU3EG/CG   ~70,000   ~7.6M      Gen3 x4
ZU4EG/EV   ~88,000   ~11.0M     Gen3 x8
ZU5EG/EV   ~117,000  ~18.0M     Gen3 x8
ZU6EG/CG   ~230,000  ~32.1M     Gen3 x16
(EV-suffixed: hardened H.265 codec for DMA + video-capture boards)
```

### Resource Constraints and Capability
```
BRAM size caps:
  shadow config + writable overlay + BAR emulation + state machines.
  T35 (1.8 Mbit) struggles with full 4 KB shadow + 64 KB BAR + jitter buffers.
  T100 (4.86 Mbit) fits comfortably.
  Zynq ZU3 (7+ Mbit) has effectively unlimited room.

LUT count caps behavioral complexity:
  Each subsystem (MSI generator, ASPM FSM, AER counter, BAR responder)
  costs thousands of LUTs. T35 holds 1–2; T100 the full set;
  Kintex/Zynq adds runtime-reconfigurable parameter tables.

PHY transceiver family (GTP/GTX/GTH/GTY) has measurably different
signal characteristics; can sometimes be inferred from root-port
performance counters independent of firmware spoofing.
```

### Form Factors
```
Form Factor           Description                 Detection
────────────────────────────────────────────────────────────────────
M.2 NGFF Key M        Internal NVMe slot           Dominant modern form;
                                                    physical inspection needed
M.2 + USB3 bridge     M.2 board with FT601         Gaming PC sees only M.2
PCIe x1/x4 add-in     Traditional add-in card      More physically visible
External USB3          USB3-to-PCIe (legacy)        Mostly obsolete
Combo boards           DMA + HDMI capture +         Complex device tree;
                       input injection              HDMI activity is fingerprint

M.2 slot populations are partially auditable from software through
PCI topology, ACPI, SMBIOS, storage inventory, and vendor board databases.
SMBIOS slot records are often incomplete for M.2, so detection should
be probabilistic and board-model-aware.
```

## pcileech Framework

### Project Lineage
```
Five upstream repositories:
- pcileech:       Host-side C application with attack modules
- pcileech-fpga:  FPGA firmware in Verilog/SystemVerilog, per-board variants
- MemProcFS:      Virtual filesystem mounting target memory as /proc-like tree
- LeechCore:      Low-level device abstraction library
- vmm:            Memory analysis engine (vmm.dll API)

Pipeline: FPGA → LeechCore → PCILeech attack modules / MemProcFS analysis
```

### FPGA Firmware Architecture
```
Key modules:
- pcileech_pcie_a7.v / _us.v:        Top-level Artix-7 / UltraScale integration
- pcileech_pcie_tlps128_bram_rdwr.v:  128-bit TLP source/sink (AXI-Stream)
- pcileech_pcie_cfgspace_shadow.v:    Shadow config space in BRAM
- pcileech_cfgspace.coe:              Init data (stock: Xilinx 10EE:0666)
- pcileech_bar_impl_zerowrite4k.v:    Default BAR — absorbs writes, returns zero
- pcileech_bar_impl_loopaddr.v:       Alternative BAR — echoes address
- pcileech_bar_impl_none.v:           Disables BAR (returns UR)
- pcileech_pcie_cfg_a7.v:             Config management via cfg_mgmt_*
- pcileech_mux.v:                     TLP multiplexer
- pcileech_fifo.v:                    Internal staging FIFO

Two key architectural choices:
1. Shadow config is spoofable but not spoofed by default.
   .coe ships with placeholder Xilinx IDs. User must overwrite
   with real donor's dump and resynthesize.
2. BAR controller is functionally inert.
   zerowrite4k doesn't emulate device behavior.
   Active BAR probing catches stock builds in one operation.
```

### Host-Side MemProcFS
```
Mounts target memory as filesystem:
M:\
├── pid\1234\
│   ├── name.txt
│   ├── modules\       ← loaded module list
│   ├── handles\
│   ├── vad\           ← virtual address descriptors
│   ├── memmap.txt
│   └── minidump\
├── sys\
├── name\game.exe\     ← lookup by process name
└── forensic\
    ├── yara\
    ├── timeline\
    └── registry\

One possible development/use pattern:
1. Development phase: MemProcFS, signature search, cross-references
   → slow, broad scanning to find entity manager / player array / view matrix
2. Execution phase: custom app via vmm.dll/LeechCore,
   narrower periodic or batched reads of known offsets
Behavioral analysis can test for this pattern, but implementations may cache,
randomize, or use different access strategies.
```

### Stock Firmware Fingerprints
```
Common or older vanilla pcileech-fpga configurations may exhibit the following;
verify the exact commit, FPGA IP configuration, and synthesized design:
- VID/DID 10EE:0666 (Xilinx placeholder)
- Xilinx 7-series PCIe IP signature bytes at characteristic offsets
- DSN Extended Capability absent or default
- No AER, LTR, ARI, ATS, or SR-IOV capabilities
- BAR0 mapped (DMA window); BAR1–5 disabled or all-ones
- BAR reads return zero (zerowrite4k) or echo address (loopaddr)
- MSI capability present but expected interrupts are not generated
- Config reads complete in deterministically uniform time
  (BRAM lookup with fixed pipeline depth, near-zero variance)
- no observed ASPM transitions under a workload and policy that should enter
  lower-power states
- AER correctable-error count stays at zero
- power state remains D0 under tested conditions
- Class Code matches donor placeholder but no class-specific behavior
```

## Configuration Space Spoofing

### Bridge vs Emulated Firmware
```
Bridge firmware:
  Patches identity fields via Vivado's PCIe IP Core GUI
  (VID, DID, Subsystem IDs, Class Code, sometimes DSN).
  Fast to produce, but 7-series hard IP generates internal capability
  blocks at characteristic offsets that retain FPGA-specific fingerprints.

Emulated (1:1) firmware:
  Implements complete shadow Configuration Space in BRAM.
  Entire 4 KB extended config space initialized from real donor device hex dump.
  When OS issues CfgRd TLP, firmware responds from BRAM.
  The design attempts to prevent IP-core defaults from appearing on the bus.

  Common bugs in emulated firmware:
  - First 16 bytes still come from IP block (mux priority)
  - Type 1 config reads not intercepted
  - Capability blocks bypassed in GUI still leak defaults
```

### Shadow Configuration Space Implementation
```
Requirements:
1. Intercept incoming CfgRd0/CfgWr0 TLPs
2. Decode target offset
3. Look up value in BRAM
4. Build Completion TLP with correct Completer ID, status, payload
5. Send Completion through hard IP block

4 KB coverage at 4-byte granularity = 1,024 entries × 4 bytes = 4 KB BRAM.
Well within even T35's resources.
```

### Overlay RAM and Writable Register Emulation
```
Real devices have writable registers. Firmware that returns correct
values on reads but drops writes creates detectable inconsistency.

Detection probe:
  write Command[BME] = 1 → read Command[BME]
  write Command[BME] = 0 → read Command[BME]
  Real silicon: bit toggles. Naive shadow: bit stays at BRAM init value.

Overlay RAM merges at read time:
  response = (base_value & ~writable_mask) | (overlay_value & writable_mask)

The catch: writable mask is register-specific:
- Command Register: different reserved bits than Device Control
- MSI Address Low: bits [1:0] reserved-zero
- BAR: type bits in [3:0] depend on I/O/memory, prefetchable
- Status Register: W1C bits — writing 1 clears, writing 0 no change
- AER Status: W1C across the board

Naive implementations with single global mask fail because
reserved-bit and W1C behavior diverges. Detection probes
W1C cases: write 0x00000000 to Correctable Error Status,
then write known-1 patterns, verify read-back semantics.
```

### Claimed Device Identity and Baselines

Compare the claimed device with provenance-backed inventory and a matched
reference: exact SKU, function, firmware, driver, topology, and power/workload
state. Multiple legitimate devices can share product identifiers. A lower link
speed, inactive function, or unusual device class needs context; none is an
automatic finding of device impersonation.

### Device Evidence Dimensions

Replace informal firmware tiers with a record of properties actually observed:

| Dimension | Evidence needed | Permitted conclusion |
|---|---|---|
| Identity and provenance | Device inventory, exact identifiers, trusted source and version | Consistent, inconsistent, or unverified identity |
| Configuration and function | Applicable device contract and matched observations | A specific conformance discrepancy with known alternatives |
| Runtime behavior | Collector coverage, workload and power-state baseline | A calibrated anomaly within the measured conditions |
| Memory-access policy | Active platform/driver remapping and available fault evidence | Permitted or denied access on the established path |
| Platform trust | Attestation policy and supported runtime observations | Trust in the measured properties, with unmeasured state explicit |

No public/private label establishes detector difficulty, guaranteed detection,
or a requirement for one particular trust anchor. A device can satisfy observed
behavioral checks while other properties remain unknown. See
[assurance boundaries](assurance-boundaries.md).

### Reference-Set Limits

Describe which legitimate device populations a baseline covers. A reference-set
absence is an unknown identity, not proof that a device class is malicious or
technically implausible. Do not claim that a whole class is defeated, undetected,
or exhausted without a versioned evaluation and measured error rates.
