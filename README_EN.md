\# RuView Scan



\*\*Wi-Fi CSI Wall-Through Scanner — 6-Face Simultaneous Visualization / Depth-Slider Structural Exploration / Rogue Device (Bug) Detection\*\*



> Scan the \*\*internal structure\*\* of walls, floors, and ceilings non-invasively using just 1 mobile Wi-Fi router + 1 laptop.



!\[Description](https://sspark.genspark.ai/cfimages?u1=zUHvXfvPQTW%2BW5t0z0dMNg1Po35Lnox%2BWwJ1KxKFaOyfTaWchD2v5AEK32Nm1%2F6JdwfAWSKv9OGHx3ykUHRoYNitxNxDv1Rjx2LVSQNFNTqHwdadTp%2Bl4lzJSNV1mRDSDhQBpsbKag2R%2BfPx46rD%2FAPWNkARFltd\&u2=yF0eymjcOiUXc%2Bq2\&width=1024)



> \[🇯🇵 日本語](README.md) | 🇬🇧 English



---



\## How It Works
\### What is CSI (Channel State Information)?
CSI captures the complex channel response $H(f\_k)$ for each subcarrier in a Wi-Fi frame. Amplitude encodes path loss and reflection strength; phase encodes propagation delay (ToF). Intel AX210 + \[FeitCSI](https://feitcsi.kuskosoft.com/) enables real-time CSI extraction.
\### Design Philosophy
\- \*\*CT-Scan-Style Wall Exploration\*\* — CSI amplitude is treated as depth. A slider filters the reflection intensity range, enabling layer-by-layer visualization from the wall surface to deep structures. Inspired by medical CT window adjustment.
\- \*\*"Humans measure the room dimensions; CSI sees through the walls"\*\* — 160 MHz bandwidth provides ≈ 0.94 m distance resolution. Combined with 80 MHz (1.875 m) for higher-precision reflection pattern analysis.
\- \*\*Fully Offline Operation\*\* — FeitCSI source code, drivers, and all dependencies are bundled. The first boot requires an internet connection for auto-build; subsequent runs are fully offline (rebuild only on kernel updates).
\- \*\*OS-Independent Design\*\* — FeitCSI builds kernel modules from source, so it works on any Debian-based distro (Ubuntu / Kali / Debian) regardless of kernel version.
\- \*\*TSCM (Technical Surveillance Countermeasures) Support\*\* — Combines RF passive scanning with CSI residual analysis to detect surveillance devices such as hidden bugs.


\### Multipath Reflection Model
The channel response is expressed as a multipath superposition:
$$H(f\_k) = \\sum\_{n=0}^{N-1} \\alpha\_n \\cdot e^{-j2\\pi f\_k \\tau\_n}$$
| Symbol | Meaning |
|--------|---------|
| $\\alpha\_n$ | Complex amplitude of the n-th path (varies by material reflectivity) |
| $\\tau\_n$ | Propagation delay of the n-th path = distance / speed of light |
| $f\_k$ | Frequency of the k-th subcarrier |
Metal pipes, electrical wiring, and PVC pipes each have different reflectivities; the magnitude of $\\alpha\_n$ is used to estimate material type.


\### Measurement Method: 9-Point Sequential (5 Required + 4 Optional)


```

&nbsp;         North Wall
&nbsp;   ┌─────────────────┐
&nbsp;   │⑨(NW)  ①(N)  ⑥(NE)│
&nbsp;   │                 │
West│④(W)    ⑤     ②(E)│ East
&nbsp;   │      (Center)   │
&nbsp;   │⑧(SW)  ③(S)  ⑦(SE)│
&nbsp;   └─────────────────┘
&nbsp;         South Wall



TX: Mobile Wi-Fi (room center, fixed)
RX: Laptop (①→②→③→④→⑤ required, ⑥→⑦→⑧→⑨ optional)

```



At each point, data is collected on 2.4 GHz (ch1, 40 MHz, 114 sc) + 5 GHz (ch36, 80 MHz, 234 sc) + 5 GHz (ch36, 160 MHz, 468 sc) for 30 seconds each. Distance resolution:



| Band | Bandwidth | Theoretical Resolution $c / (2 \\cdot BW)$ |
|------|-----------|-------------------------------------------|
| 2.4 GHz | 40 MHz | 3.75 m |
| 5 GHz | 80 MHz | 1.875 m |
| 5 GHz | 160 MHz | \*\*≈ 0.94 m\*\* |

160 MHz provides the highest resolution; 80 MHz is the primary estimation band; 2.4 GHz offers superior wall penetration for supplementary use.



---



\## Technology Stack



| Category | Technology | Purpose |
|----------|-----------|---------|
| CSI Extraction | \[FeitCSI](https://feitcsi.kuskosoft.com/) v2.0 | Open-source CSI tool. Supports all 802.11a/g/n/ac/ax formats |
| NIC | Intel AX210 / AX211 / AX200 (M.2) | Monitor mode CSI reception (up to 160 MHz, 2×2 MIMO) |
| Driver | FeitCSI-iwlwifi (custom iwlwifi) | DKMS-compatible. Auto-builds for current kernel version |
| Backend | Python 3.11+ / FastAPI / uvicorn | REST API (20 endpoints) + WebSocket |
| Frontend | HTML5 Canvas / Three.js / WebSocket | 6-face heatmap + 3D room viewer |
| Signal Processing | NumPy / SciPy / MUSIC super-resolution | ToF estimation, phase calibration, band fusion |
| CSI Parser | feitcsi\_parser.py / CSIKit | FeitCSI .dat binary (272B header + IQ data) |
| Reports | jsPDF / html2canvas | PDF/CSV export |



---



\## System Architecture



```

┌──────────────┐     ┌───────────────────────────────────────────┐
│  Browser UI  │◄────►  FastAPI Server (uvicorn, port 8080)     │
│  (6-Face)    │ WS  │                                           │
└──────────────┘     │  routes.py ── REST API (20 endpoints)     │
&nbsp;                    │  ws.py ───── WebSocket /ws/scan           │
&nbsp;                    │                                           │
&nbsp;                    │  ┌─── Setup Layer ──────────────────┐     │
&nbsp;                    │  │ boot\_sequence.py  Boot sequence   │     │
&nbsp;                    │  │ env\_checker.py    8-item check    │     │
&nbsp;                    │  │ offline\_installer.py Offline deps │     │
&nbsp;                    │  │ feitcsi\_builder.py  Source build  │     │
&nbsp;                    │  │ monitor\_setup.py  Monitor mode    │     │
&nbsp;                    │  │ setup\_state.py    State persist   │     │
&nbsp;                    │  └──────────────────────────────────┘     │
&nbsp;                    │  ┌─── CSI Layer ────────────────────┐     │
&nbsp;                    │  │ adapter.py   FeitCSI / Sim        │     │
&nbsp;                    │  │ feitcsi\_bridge.py  UDP:8008       │     │
&nbsp;                    │  │ feitcsi\_parser.py  .dat parser    │     │
&nbsp;                    │  │ collector.py DualBandCollector     │     │
&nbsp;                    │  │ calibration.py PhaseCalibrator     │     │
&nbsp;                    │  │ models.py    CSIFrame / Session    │     │
&nbsp;                    │  └──────────────────────────────────┘     │
&nbsp;                    │  ┌─── Scan Layer ───────────────────┐     │
&nbsp;                    │  │ tof\_estimator.py   MUSIC / ESPRIT │     │
&nbsp;                    │  │ aoa\_estimator.py   AoA estimation │     │
&nbsp;                    │  │ room\_estimator.py  Wall distance  │     │
&nbsp;                    │  │ reflection\_map.py  CSI→6-face grid│     │
&nbsp;                    │  │ structure\_detector.py Pipe detect │     │
&nbsp;                    │  │ foreign\_detector.py  Rogue detect │     │
&nbsp;                    │  └──────────────────────────────────┘     │
&nbsp;                    │  ┌─── Fusion / RF ──────────────────┐     │
&nbsp;                    │  │ band\_merger.py   2.4+5GHz fusion  │     │
&nbsp;                    │  │ spatial\_integrator.py 5-pt fusion  │     │
&nbsp;                    │  │ view\_generator.py 6-face gen      │     │
&nbsp;                    │  │ scanner.py  Passive RF scan        │     │
&nbsp;                    │  │ device\_classifier.py Device class  │     │
&nbsp;                    │  └──────────────────────────────────┘     │
&nbsp;                    └───────────────────────────────────────────┘

```


\### FeitCSI Integration



```

┌──────────────┐     UDP:8008      ┌──────────────────┐
│              │  ←── CSI data ──  │                  │
│  RuView Scan │                   │  FeitCSI         │
│  (Python)    │  ── commands ──→  │  (--udp-socket)  │
│              │                   │                  │
│  feitcsi\_    │                   │  Custom          │
│  bridge.py   │                   │  iwlwifi driver  │
└──────┬───────┘                   └────────┬─────────┘
&nbsp;      │                                     │
&nbsp;      │  CSI data (272B header + IQ data)   │ Monitor Mode
&nbsp;      │                                     │
&nbsp;      ▼                                     ▼
┌──────────────┐                   ┌──────────────────┐
│ feitcsi\_     │                   │  AX210 NIC       │
│ parser.py    │                   │  (PCIe/M.2)      │
│              │                   │                  │
│ → amplitude  │                   │  ← Wi-Fi frames  │
│ → phase      │                   │     from         │
│ → ToF est.   │                   │     Mobile WiFi  │
└──────────────┘                   └──────────────────┘
```



---



\## Boot Flow



```

ruview-scan (launch)
&nbsp; │
&nbsp; ├─ 1. Load setup\_state.json
&nbsp; │     ├─ Not found → First-time setup (online required)
&nbsp; │     ├─ kernel\_version mismatch → Rebuild
&nbsp; │     └─ OK → Quick check
&nbsp; │
&nbsp; ├─ 2. Environment Check (env\_checker.py: 8 items)
&nbsp; │     ├─ \[1] OS      Linux (Debian-based recommended)
&nbsp; │     ├─ \[2] Arch    x86\_64 / arm64
&nbsp; │     ├─ \[3] CPU     Core count \& frequency
&nbsp; │     ├─ \[4] NIC     AX210/AX211/AX200 detection (lspci)
&nbsp; │     ├─ \[5] FW      /lib/firmware/iwlwifi-\* presence
&nbsp; │     ├─ \[6] Headers linux-headers-$(uname -r) presence
&nbsp; │     ├─ \[7] FeitCSI feitcsi binary \& kernel match
&nbsp; │     └─ \[8] Deps    libgtkmm, libnl, libpcap, etc.
&nbsp; │
&nbsp; ├─ 3. Auto-Repair (offline\_installer.py + feitcsi\_builder.py)
&nbsp; │     ├─ setup/firmware/ → Copy firmware
&nbsp; │     ├─ setup/deb/ → dpkg -i (offline)
&nbsp; │     ├─ setup/python\_wheels/ → pip install
&nbsp; │     ├─ FeitCSI source build (make → install)
&nbsp; │     └─ Record results in setup\_state.json
&nbsp; │
&nbsp; ├─ 4. Monitor Mode Setup (monitor\_setup.py)
&nbsp; │     ├─ NIC not found → Continue in simulation mode
&nbsp; │     ├─ NIC found → rfkill unblock → monitor mode
&nbsp; │     └─ Launch feitcsi --udp-socket in background
&nbsp; │
&nbsp; ├─ 5. FeitCSI Bridge Init (feitcsi\_bridge.py)
&nbsp; │     ├─ Verify UDP port 8008 connection
&nbsp; │     ├─ Send measurement parameters (freq/BW/format)
&nbsp; │     └─ Start CSI data receive loop
&nbsp; │
&nbsp; └─ 6. Launch WebUI → Scan screen
&nbsp;       ├─ NIC present → Live scan mode
&nbsp;       └─ NIC absent → Simulation mode
```



---



\## Processing Pipeline



```

CSIFrame Collection (9 points × 3 bands)
&nbsp;   │
&nbsp;   ├─ PhaseCalibrator: Phase correction (STO/CPE removal)
&nbsp;   │
&nbsp;   ▼
ToFEstimator (MUSIC Super-Resolution)
&nbsp;   │   MUSIC spatial spectrum → path distance + amplitude
&nbsp;   │
&nbsp;   ├───────────────────┐
&nbsp;   ▼                   ▼
RoomEstimator      ReflectionMapGenerator
(Image method       CSI amplitude → 6-face
&nbsp;inversion)         grid (0.05 m) direct mapping
&nbsp;   │               Gaussian-weighted interpolation
&nbsp;   ▼               Normalized 0.0–1.0 output
RoomDimensions          │
(Manual 80% +           ▼
&nbsp;ToF 20% fusion)   6×ReflectionMap
&nbsp;                  (Normalized grids)
&nbsp;                       │
&nbsp;                  ┌────┴────┐
&nbsp;                  ▼         ▼
&nbsp;             StructureDetector   → Browser UI
&nbsp;             (Connected-comp)       Depth slider to
&nbsp;             (UI default OFF)       specify threshold range;
&nbsp;                                    Canvas real-time rendering

```



\### ToF Estimation: MUSIC Super-Resolution



```python
\# Eigendecomposition of spatial correlation matrix
Rxx = (1/K) Σ x(k) x(k)^H     # K: number of snapshots
Rxx = U Λ U^H                  # Eigendecomposition
\# Noise subspace
Un = U\[:, n\_paths:]
\# MUSIC spectrum
P(τ) = 1 / |a(τ)^H Un Un^H a(τ)|
\# a(τ) = \[1, e^{-j2πΔfτ}, ..., e^{-j2π(M-1)Δfτ}]^T

```



\### Room Dimension Estimation: Image Method Inversion

Estimate wall distance from reflected path distance:

$$d\_{wall} = \\frac{\\sqrt{d\_{reflection}^2 - d\_{direct}^2}}{2}$$

When manual input is available, 80/20 fusion is applied: $d\_{fused} = 0.8 \\cdot d\_{manual} + 0.2 \\cdot d\_{ToF}$



\### Material Classification Thresholds



| Material | Reflection Strength | Threshold |
|----------|-------------------|-----------|
| Metal pipe (steel, copper) | High | ≥ 0.6 |
| Wall stud (wood/light steel) | Medium-high | 0.45–0.6 |
| Electrical wiring (VVF) | Medium | 0.35–0.45 |
| PVC pipe (VP/VU) | Low | 0.35–0.45 |


---



\## UI Features


\### Depth Slider (CT-Scan Style)

Reflection intensity is treated as depth, allowing users to adjust the display range with sliders.

\- \*\*Lower bound slider\*\* (0–100): Hide reflection intensities below this value
\- \*\*Upper bound slider\*\* (0–100): Hide reflection intensities above this value
\- \*\*Opacity slider\*\* (0–100): Adjust overall heatmap transparency

Each face (6 tabs) maintains independent slider values, automatically saved and restored on tab switch.

!\[Description](https://sspark.genspark.ai/cfimages?u1=%2B0jLHT%2FtanDnsd8Xv5UQDf4YXd5IhqLSxYKyDaNDbD84trPgRJq7wWk3A5Pgalh3D02gyqBq05TiRhrqFPmuGAZiM3RBIR6AzE7Z14yzfPyMNi6QRiGSOyZwqerp0jPS9wSZI2otWY2rv1yg76RYyim%2BVTeHuaBm\&u2=Hnii8d%2F50tFaheNn\&width=1024)


\### Color Map Switching



5 color maps with instant switching:



| ID | Name | Use Case |
|----|------|----------|
| thermal | Thermal | Default. Blue→Purple→Magenta→Red→Orange |
| heat | Heat | Black→Red→Yellow→White. High contrast |
| cool | Cool | Black→Blue→Cyan→White. Best for wiring |
| grayscale | Grayscale | B\&W. For printing / PDF |
| rainbow | Rainbow | Full spectrum. Fine intensity differences |


!\[Description](https://sspark.genspark.ai/cfimages?u1=%2F615NXX2%2Bt5GeshUxsI%2FzaAgBfAeJwi%2ByDIiYlcpPOvtcgO14xW%2FXW0qLpkpm2JAvd4JPdZuidMkH1O8U0jBLChyw3diU2jd34z0ocW5OnbBEY4qri5X1ithdm0KnKHbAYDOiWXkYPL7heFv93XQnrXyqfvu9fhr\&u2=Rj5FtBwNwVSsqy75\&width=1024)



\### 3D Room Viewer
\- Three.js-based 6-face BOX with heatmap textures on inner surfaces
\- OrbitControls for rotation and zoom
\- Pipes and foreign objects rendered as tubes/spheres in 3D space
\- Depth slider, color map, and opacity synchronized between 2D and 3D views



\### Other UI Features
\- \*\*Mouse hover tooltip\*\*: Real-time display of coordinates (m) and reflection intensity (0.00–1.00) on canvas
\- \*\*Filter buttons\*\*: Pipes/wiring (default OFF) / Foreign objects / Heatmap — independent toggle
\- \*\*Frequency switching\*\*: Mix (all bands) / 2.4 GHz / 5 GHz (80MHz) / 5 GHz (160MHz) — instant switch
\- \*\*Foreign object detection modal\*\*: Detailed report on rogue device detection
\- \*\*PDF/CSV report export\*\*: Export scan results
\- \*\*System status on boot\*\*: OS, NIC, FeitCSI, and monitor mode status auto-displayed in log area

---



\## Directory Structure



```

ruview-scan/
├── config/
│   ├── default.yaml ........... Measurement parameters, analysis settings
│   └── setup\_state.json ....... Build state persistence (auto-generated)
├── src/
│   ├── main.py ................ CLI: --simulate, --feitcsi, --skip-setup, --host, --port
│   ├── config.py .............. YAML → AppConfig (pydantic)
│   ├── errors.py .............. Exception hierarchy (RuViewError → 7 subclasses)
│   ├── setup/ ................. ★ Auto-setup module
│   │   ├── \_\_init\_\_.py
│   │   ├── setup\_state.py .... Build state management (JSON persistence)
│   │   ├── env\_checker.py .... Environment scan (8-item check)
│   │   ├── offline\_installer.py Offline bundled package installer
│   │   ├── feitcsi\_builder.py  FeitCSI source auto-build (DKMS)
│   │   ├── monitor\_setup.py .. AX210 monitor mode auto-setup
│   │   └── boot\_sequence.py .. Boot sequence orchestrator
│   ├── api/
│   │   ├── server.py .......... AppState, FastAPI app, lifespan
│   │   ├── routes.py .......... REST 20 endpoints (incl. /api/system/status)
│   │   └── ws.py .............. WebSocket progress stream
│   ├── csi/
│   │   ├── models.py .......... CSIFrame, DualBandCapture, ScanSession
│   │   ├── adapter.py ......... CSIAdapter ABC, FeitCSIAdapter, SimulatedAdapter
│   │   ├── feitcsi\_bridge.py .. FeitCSI UDP bridge (port 8008)
│   │   ├── feitcsi\_parser.py .. FeitCSI .dat binary parser
│   │   ├── collector.py ....... DualBandCollector (3-band switching)
│   │   └── calibration.py ..... PhaseCalibrator (STO/CPE correction)
│   ├── scan/
│   │   ├── scan\_manager.py .... Session management (9 points) + progress callback
│   │   ├── tof\_estimator.py ... MUSIC / ESPRIT / IFFT super-resolution
│   │   ├── aoa\_estimator.py ... AoA estimation (Phase F-1 integration planned)
│   │   ├── room\_estimator.py .. Image method inversion → RoomDimensions
│   │   ├── reflection\_map.py .. CSI amplitude → 6-face grid direct mapping
│   │   ├── structure\_detector.py Connected-component → pipe/wiring detection
│   │   └── foreign\_detector.py  RF+CSI residual → rogue device detection
│   ├── fusion/
│   │   ├── band\_merger.py ..... 2.4+5GHz weighted fusion
│   │   ├── spatial\_integrator.py 5-point distance-weighted fusion
│   │   └── view\_generator.py .. 6-face JSON + canvas coordinate transform
│   ├── rf/
│   │   ├── scanner.py ......... Passive RF scan
│   │   └── device\_classifier.py OUI/RSSI/beacon → device classification
│   └── utils/
│       ├── math\_utils.py ...... MUSIC, ESPRIT, correlation matrix
│       └── geo\_utils.py ....... channel\_to\_freq, project\_to\_wall
├── setup/ ..................... ★ Offline bundled packages
     ├── feitcsi/ ............... FeitCSI source (pre-cloned)
│   │   ├── FeitCSI/
│   │   └── FeitCSI-iwlwifi/
│   ├── deb/ ................... System dependency .deb packages
│   ├── firmware/ .............. iwlwifi firmware (for AX210)
│   ├── python\_wheels/ ......... Python dependency packages (.whl)
│   └── download\_packages.sh ... Bulk download script for bundled packages
├── static/
│   ├── index.html ............. 3-column UI (6-face view, 3D, scan control)
│   ├── css/style.css .......... Dark theme UI
│   └── js/
│       ├── app.js ............. Main module + system status display
│       ├── scan\_control.js .... 9-point scan control + 3 bands
│       ├── websocket.js ....... WS connection + auto-reconnect
│       ├── heatmap\_renderer.js  Server grid rendering (5 color maps)
│       ├── floor\_renderer.js .. Pipe/foreign/point canvas rendering
│       ├── room3d\_three.js .... Three.js 3D room viewer
│       ├── report.js .......... PDF/CSV export
│       ├── audio.js ........... Foreign object alert sound
│       └── lib/ ............... Three.js, OrbitControls, jsPDF, html2canvas
├── docs/images/ ............... Screenshots
├── ruview.bat ................. Windows launch script
├── ruview.sh .................. Linux launch script
└── requirements.txt

```



---



\## Setup



\### Required Hardware



| Hardware | Requirements | Purpose |
|----------|-------------|---------|
| Mobile Wi-Fi | 2.4 + 5 GHz dual band | TX (fixed at room center) |
| Laptop | Intel AX210/AX211 equipped | RX (moved to 5–9 positions) |
| OS | Kali Linux / Ubuntu 22.04+ / Debian-based | Live operation |
| OS (Simulation) | Windows / macOS / Linux (any) | Development / Demo |



\### Installation



```bash

cd ruview-scan

python3 -m venv venv

source venv/bin/activate          # Windows: venv\\Scripts\\activate

pip install -r requirements.txt

```



\### Pre-Download Offline Packages (For Live Use)



```bash

\# Run on an online machine — bulk download FeitCSI source, debs, firmware, wheels to setup/

bash setup/download\_packages.sh

```



\### Launch



```bash

\# Simulation mode (physics-based CSI generation, no NIC required)

python src/main.py --simulate



\# Live mode (FeitCSI auto-build → monitor mode → scan)

sudo python src/main.py



\# Force FeitCSI mode

sudo python src/main.py --feitcsi



\# Skip setup (pre-built environment)

sudo python src/main.py --skip-setup

```



→ Open \*\*http://127.0.0.1:8080\*\* in your browser



---



\## Usage



1\. \*\*Enter room dimensions\*\* — Measure width (E-W), depth (N-S), and ceiling height with a tape measure → Click "Confirm Dimensions"

2\. \*\*Place mobile Wi-Fi at room center\*\*

3\. \*\*Scan 5–9 positions sequentially\*\* — Place laptop 1m from each wall → Click "Scan"
&nbsp;  (Per point: 2.4 GHz + 5 GHz 80MHz + 5 GHz 160MHz ≈ 1.5 min/point. Corner positions are optional)

4\. \*\*Click "Build 3D from Scan Results"\*\*

5\. \*\*Explore wall internals with the depth slider\*\*:
&nbsp;  - Adjust lower/upper sliders to narrow the reflection intensity display range
&nbsp;  - Switch color maps for better visibility
&nbsp;  - Hover mouse to check coordinates and intensity at any point

6\. \*\*Switch between 6 face tabs\*\* — Slider settings are independently maintained per face



---



\## Dependencies



\### Fully Offline Bundled (setup/ folder)



```

┌──────────────────────────────────────────────────────────────┐
│  \[FeitCSI Source]                                            │
│    FeitCSI/           → pre-cloned with --recursive          │
│    FeitCSI-iwlwifi/   → pre-cloned                           │
│    \* Built for current kernel at boot (make → make install)  │
│                                                              │
│  \[System .deb Packages]                                      │
│    build-essential, dkms, flex, bison                        │
│    libgtkmm-3.0-dev, libnl-genl-3-dev                       │
│    libiw-dev, libpcap-dev, iw, wireless-tools, rfkill        │
│                                                              │
│  \[Firmware]                                                   │
│    iwlwifi-ty-a0-gf-a0-\*.ucode (for AX210)                  │
│                                                              │
│  \[Python Wheels]                                              │
│    fastapi, uvicorn, websockets, numpy, scipy, etc.          │
│                                                              │
│  \[Frontend]                                                   │
│    Three.js, jsPDF, html2canvas → in static/js/lib/          │
└──────────────────────────────────────────────────────────────┘

```



\### Required Only at Boot Time



```

┌──────────────────────────────────────────────────────────────┐
│  \[linux-headers]                                             │
│    linux-headers-$(uname -r)                                 │
│    Cannot be pre-bundled due to kernel version variability   │
│    \* If bundled deb matches → works offline                  │
│    \* Otherwise → apt install required                        │
│                                                              │
│  → Fully offline as long as running on the same kernel       │
│  → Only linux-headers re-download needed on kernel updates   │
└──────────────────────────────────────────────────────────────┘

```



---



\## WebSocket



| Endpoint | Direction | Message Type |
|----------|-----------|-------------|
| `/ws/scan` | Server→Client | `status`, `progress`, `scan\_complete`, `error` |
| `/ws/scan` | Client→Server | `{action: "start\_scan", point\_id: "north"}` |


---



\## Simulation Mode



The `--simulate` flag launches physics-based CSI simulation.



\### How `SimulatedAdapter` Works



1\. \*\*Image Source Method\*\* for wall reflection path calculation:
&nbsp;  - 4 walls + ceiling + floor = 6 image routers
&nbsp;  - Distance from each image → ToF

2\. \*\*Pipe scatterer\*\* simulation:
&nbsp;  - Metal pipes, electrical wiring, PVC pipes, wall studs defined in 3D coordinates
&nbsp;  - Distance to scatterer + material-specific reflectivity → $\\alpha\_n$

3\. \*\*Per-subcarrier complex channel response\*\*:
&nbsp;  ```
&nbsp;  H(f\_k) = Σ α\_n · exp(-j·2π·f\_k·τ\_n) + noise
&nbsp;  ```

4\. `set\_point()` switches measurement points: multipath structure changes based on position. All 9 points supported.

---



\## Changelog



\### Phase A (Complete)
\- CSI acquisition, ToF estimation, basic UI
\- buildResult freeze fix, manual dimension handling, error log improvements
\- SimulatedAdapter-based reflection map simulation

\### Phase B (Complete)
\- Complete rewrite of `reflection\_map.py`: back-projection/known-coordinate cheating → direct CSI amplitude mapping
\- Depth slider (lower/upper bounds) added to UI
\- `/api/result/map/{face}/{band}` grid data API added
\- `heatmap\_renderer.js` → server grid rendering (`drawGrid`)

\### Phase B+ (Complete)
\- 5 color map switching (Thermal/Heat/Cool/Grayscale/Rainbow)
\- Opacity slider
\- Preset buttons (All/Surface/Shallow/Deep/Auto)
\- Mouse hover tooltip (coordinates + reflection intensity)
\- Canvas stretch-fill (full display, non-fixed aspect ratio)
\- Pipe auto-rendering set to default OFF

\### Phase C (Complete)
\- Foreign object detection system (RF passive scan + CSI residual analysis)
\- Threat level classification (high/medium/low/none)
\- RSSI-based position estimation
\- Foreign object detection modal (detailed report)
\- RF simulation (3 normal APs + 2 rogue devices)

\### Phase D (Complete)
\- 160 MHz bandwidth support (468 subcarriers, resolution ≈ 0.94 m)
\- 3-band collection (2.4 GHz → 5 GHz 80 MHz → 5 GHz 160 MHz)
\- Additional 4 corner measurement points (NE/SE/SW/NW) — optional
\- Measurement points 5 → 9 (5 required + 4 optional)
\- UI: 160M frequency button, 3-stage progress bar, corner scan cards
\- Pre-scan display of all measurement points on floor view
\- API: /result/map/{face}/{band} on-demand per-band generation

\### Phase E (Complete)
\- Three.js 3D room viewer (6-face BOX + OrbitControls rotate/zoom)
\- 6-face heatmaps as textures on 3D BOX inner surfaces
\- Depth slider, color map, opacity synced with 3D view in real-time
\- Heatmap ON/OFF filter unified across 2D and 3D
\- Pipes and foreign objects rendered in 3D space (tubes/spheres)
\- Depth filter for pipes and foreign objects (depth-property based)
\- Direction labels (N/S/E/W) + measurement points (pos.1-9) in 3D space
\- Depth filter applied to 2D rendering as well
\- PDF/CSV report export

\### Phase F-0 (Complete)
\- Full migration from PicoScenes → FeitCSI (open-source, OS/kernel independent)
\- Auto-setup system (8-item check: OS/Arch/CPU/NIC/FW/Headers/FeitCSI/Deps)
\- Offline installer (deb/firmware/wheels bundled in setup/ folder)
\- FeitCSI source auto-build (DKMS-compatible, auto-rebuild on kernel change)
\- AX210 monitor mode auto-setup + FeitCSI UDP service launch
\- Boot sequence integration (boot\_sequence.py → check → install → build → monitor → WebUI)
\- FeitCSI UDP bridge (port 8008) + .dat binary parser
\- FeitCSIAdapter added to CSI adapters (feitcsi/picoscenes/simulate, default: feitcsi)
\- main.py updated (--feitcsi / --skip-setup options, auto boot result detection)
\- WebUI system status display (/api/system/status + auto log display)

---



\## Roadmap



| Phase | Description | Status |
|-------|------------|--------|
| \*\*A\*\* | CSI acquisition, ToF estimation, basic UI | ✅ Complete |
| \*\*B\*\* | Direct CSI amplitude mapping, depth slider | ✅ Complete |
| \*\*B+\*\* | Color maps, opacity, presets, hover tooltip | ✅ Complete |
| \*\*C\*\* | Foreign object detection, RF passive scan, threat classification | ✅ Complete |
| \*\*D\*\* | 160 MHz support (≈0.94 m resolution), additional points (5→9) | ✅ Complete |
| \*\*E\*\* | 3D viewer (Three.js), PDF/CSV report export | ✅ Complete |
| \*\*F-0\*\* | FeitCSI integration, auto-setup, offline setup | ✅ Complete |
| \*\*F-1\*\* | Live calibration, AoA integration, DI patterns | 🔧 Planned |


---

\## License
Private — Unauthorized reproduction or copying prohibited (no commercial use)

