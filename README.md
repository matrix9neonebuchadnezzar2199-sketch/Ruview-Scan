
---

# RuView Scan

**Wi-Fi CSI 壁面透視スキャナ — 6 面同時可視化 / 深度スライダー式構造探査 / 異物(盗聴器)検出**

> 1 台のモバイル Wi-Fi ルーター + 1 台のノート PC で、部屋の壁・床・天井の **内部構造** を非接触で透視する。

![説明](https://sspark.genspark.ai/cfimages?u1=zUHvXfvPQTW%2BW5t0z0dMNg1Po35Lnox%2BWwJ1KxKFaOyfTaWchD2v5AEK32Nm1%2F6JdwfAWSKv9OGHx3ykUHRoYNitxNxDv1Rjx2LVSQNFNTqHwdadTp%2Bl4lzJSNV1mRDSDhQBpsbKag2R%2BfPx46rD%2FAPWNkARFltd&u2=yF0eymjcOiUXc%2Bq2&width=1024)


> 🇯🇵 日本語 | [🇬🇧 English](README_EN.md)

---

## 動作原理

### CSI (Channel State Information) とは

Wi-Fi フレームの各サブキャリアに対する複素チャネル応答 $H(f_k)$ を取得する技術。振幅はパス損失・反射強度を、位相は伝搬遅延（ToF）を含む。Intel AX210 + [FeitCSI](https://feitcsi.kuskosoft.com/) でリアルタイム CSI 抽出が可能。

### 設計思想

- **CTスキャン方式の壁内探査** — CSI 振幅を深度に見立て、スライダーで反射強度範囲を絞り込むことにより壁表面から深部まで層ごとに構造を可視化。医療 CT のウィンドウ調整に着想を得た操作性
- **「部屋の外形は人間が測り、壁の中身は CSI が透視する」** — 160 MHz 帯域幅での距離分解能は ≈ 0.94 m。80 MHz (1.875 m) と組み合わせることで壁内の反射パターンをより高精度に解析
- **完全オフライン動作** — FeitCSI ソース・ドライバ・依存パッケージをすべて同梱。初回起動時にオンラインで自動構築し、以降はオフラインで動作（カーネル更新時のみ再構築）
- **OS 非依存設計** — FeitCSI はカーネルモジュールをソースからビルドするため、Ubuntu / Kali / Debian 系であればカーネルバージョンを問わず動作
- **TSCM (Technical Surveillance Countermeasures) 対応** — RF パッシブスキャンと CSI 残差解析を組み合わせて盗聴器等の不審デバイスを検出

### マルチパス反射モデル

チャネル応答は以下のマルチパス合成で表現される:

$$H(f_k) = \sum_{n=0}^{N-1} \alpha_n \cdot e^{-j2\pi f_k \tau_n}$$

| 記号 | 意味 |
|------|-----|
| $\alpha_n$ | 第 n パスの複素振幅（反射材質で変化） |
| $\tau_n$ | 第 n パスの伝搬遅延 = 距離 / 光速 |
| $f_k$ | 第 k サブキャリア周波数 |

壁内の金属管・電気配線・塩ビ管はそれぞれ反射率が異なり、$\alpha_n$ の大きさから材質を推定できる。

### 測定方式: 9 点シーケンシャル (5 必須 + 4 オプション)

```
          北壁
    ┌─────────────────┐
    │⑨(NW)  ①(N)  ⑥(NE)│
    │                 │
 西 │④(W)    ⑤     ②(E)│ 東
    │       (中心)    │
    │⑧(SW)  ③(S)  ⑦(SE)│
    └─────────────────┘
          南壁

TX: モバイルWi-Fi (部屋中心, 固定)
RX: ノートPC (①→②→③→④→⑤ 必須, ⑥→⑦→⑧→⑨ 任意)
```

各ポイントで 2.4 GHz (ch1, 40 MHz, 114 sc) + 5 GHz (ch36, 80 MHz, 234 sc) + 5 GHz (ch36, 160 MHz, 468 sc) を各 30 秒収集。距離分解能:

| バンド | 帯域幅 | 理論分解能 $c / (2 \cdot BW)$ |
|--------|--------|------------------------------|
| 2.4 GHz | 40 MHz | 3.75 m |
| 5 GHz | 80 MHz | 1.875 m |
| 5 GHz | 160 MHz | **≈ 0.94 m** |

160 MHz が最高分解能帯域、80 MHz が主要推定帯域、2.4 GHz は壁透過性が高いため補完に使用。

---

## 使用技術

| 区分 | 技術 | 用途 |
|------|------|------|
| CSI 抽出 | [FeitCSI](https://feitcsi.kuskosoft.com/) v2.0 | オープンソース CSI ツール。802.11a/g/n/ac/ax 全帯域対応 |
| NIC | Intel AX210 / AX211 / AX200 (M.2) | モニターモード CSI 受信 (最大 160 MHz, 2×2 MIMO) |
| ドライバ | FeitCSI-iwlwifi (カスタム iwlwifi) | DKMS 対応。カーネル版に合わせて自動ビルド |
| バックエンド | Python 3.11+ / FastAPI / uvicorn | REST API (20 endpoints) + WebSocket |
| フロントエンド | HTML5 Canvas / Three.js / WebSocket | 6面ヒートマップ + 3D ルームビュー |
| 信号処理 | NumPy / SciPy / MUSIC 超解像 | ToF 推定・位相校正・バンド融合 |
| CSI パーサー | feitcsi_parser.py / CSIKit | FeitCSI .dat バイナリ (272B ヘッダ + IQ) |
| レポート | jsPDF / html2canvas | PDF/CSV エクスポート |

---

## システムアーキテクチャ

```
┌──────────────┐     ┌───────────────────────────────────────────┐
│  Browser UI  │◄────►  FastAPI Server (uvicorn, port 8080)     │
│  (6面ビュー) │ WS  │                                           │
└──────────────┘     │  routes.py ── REST API (20 endpoints)     │
                     │  ws.py ───── WebSocket /ws/scan           │
                     │                                           │
                     │  ┌─── Setup Layer ──────────────────┐     │
                     │  │ boot_sequence.py  起動シーケンス  │     │
                     │  │ env_checker.py    環境8項目検証   │     │
                     │  │ offline_installer.py オフラインDep │     │
                     │  │ feitcsi_builder.py  ソースビルド  │     │
                     │  │ monitor_setup.py モニターモード   │     │
                     │  │ setup_state.py   状態永続化       │     │
                     │  └──────────────────────────────────┘     │
                     │  ┌─── CSI Layer ────────────────────┐     │
                     │  │ adapter.py   FeitCSI / Sim        │     │
                     │  │ feitcsi_bridge.py  UDP:8008       │     │
                     │  │ feitcsi_parser.py  .dat パーサー  │     │
                     │  │ collector.py DualBandCollector     │     │
                     │  │ calibration.py PhaseCalibrator     │     │
                     │  │ models.py    CSIFrame / Session    │     │
                     │  └──────────────────────────────────┘     │
                     │  ┌─── Scan Layer ───────────────────┐     │
                     │  │ tof_estimator.py   MUSIC / ESPRIT │     │
                     │  │ aoa_estimator.py   AoA推定        │     │
                     │  │ room_estimator.py  壁距離推定      │     │
                     │  │ reflection_map.py  CSI→6面グリッド │     │
                     │  │ structure_detector.py 配管検出     │     │
                     │  │ foreign_detector.py  異物検出      │     │
                     │  └──────────────────────────────────┘     │
                     │  ┌─── Fusion / RF ──────────────────┐     │
                     │  │ band_merger.py   2.4+5GHz統合     │     │
                     │  │ spatial_integrator.py 5点統合      │     │
                     │  │ view_generator.py 6面データ生成    │     │
                     │  │ scanner.py  パッシブRFスキャン      │     │
                     │  │ device_classifier.py デバイス分類  │     │
                     │  └──────────────────────────────────┘     │
                     └───────────────────────────────────────────┘
```

### FeitCSI 統合設計

```
┌──────────────┐     UDP:8008      ┌──────────────────┐
│              │  ←── CSI data ──  │                  │
│  RuView Scan │                   │  FeitCSI         │
│  (Python)    │  ── commands ──→  │  (--udp-socket)  │
│              │                   │                  │
│  feitcsi_    │                   │  カスタム        │
│  bridge.py   │                   │  iwlwifi ドライバ│
└──────┬───────┘                   └────────┬─────────┘
       │                                     │
       │  CSI data (272B header + IQ data)   │ Monitor Mode
       │                                     │
       ▼                                     ▼
┌──────────────┐                   ┌──────────────────┐
│ feitcsi_     │                   │  AX210 NIC       │
│ parser.py    │                   │  (PCIe/M.2)      │
│              │                   │                  │
│ → amplitude  │                   │  ← Wi-Fi frames  │
│ → phase      │                   │     from         │
│ → ToF推定    │                   │     モバイルWiFi  │
└──────────────┘                   └──────────────────┘
```

---

## 起動フロー

```
ruview-scan (起動)
  │
  ├─ 1. setup_state.json 読み込み
  │     ├─ 存在しない → 初回セットアップ（オンライン必須）
  │     ├─ kernel_version 不一致 → 再ビルド
  │     └─ 正常 → クイックチェックへ
  │
  ├─ 2. 環境チェック（env_checker.py: 8項目）
  │     ├─ [1] OS      Linux か（Debian系推奨）
  │     ├─ [2] Arch    x86_64 / arm64
  │     ├─ [3] CPU     コア数・周波数
  │     ├─ [4] NIC     AX210/AX211/AX200 検出（lspci）
  │     ├─ [5] FW      /lib/firmware/iwlwifi-* 存在確認
  │     ├─ [6] Headers linux-headers-$(uname -r) 存在確認
  │     ├─ [7] FeitCSI feitcsi バイナリ & カーネル一致
  │     └─ [8] Deps    libgtkmm, libnl, libpcap 等
  │
  ├─ 3. 自動修復（offline_installer.py + feitcsi_builder.py）
  │     ├─ setup/firmware/ → ファームウェアコピー
  │     ├─ setup/deb/ → dpkg -i（オフライン）
  │     ├─ setup/python_wheels/ → pip install
  │     ├─ FeitCSI ソースビルド（make → install）
  │     └─ setup_state.json に成否記録
  │
  ├─ 4. モニターモード設定（monitor_setup.py）
  │     ├─ NIC 未検出 → シミュレーションモードで続行
  │     ├─ NIC 検出 → rfkill unblock → monitor mode
  │     └─ feitcsi --udp-socket でバックグラウンド起動
  │
  ├─ 5. FeitCSI ブリッジ初期化（feitcsi_bridge.py）
  │     ├─ UDP ポート 8008 接続確認
  │     ├─ 測定パラメータ送信（周波数/帯域幅/フォーマット）
  │     └─ CSI データ受信ループ開始
  │
  └─ 6. WebUI 起動 → スキャン画面表示
        ├─ NIC あり → 実機スキャンモード
        └─ NIC なし → シミュレーションモード
```

---

## 処理パイプライン

```
CSIFrame収集 (9点×3バンド)
    │
    ├─ PhaseCalibrator: 位相校正 (STO/CPE 推定除去)
    │
    ▼
ToFEstimator (MUSIC 超解像)
    │   MUSIC空間スペクトラム → パス距離 + 振幅
    │
    ├───────────────────┐
    ▼                   ▼
RoomEstimator      ReflectionMapGenerator
(鏡像法逆変換)      CSI振幅を各面グリッド
    │               (0.05 m) に直接マッピング
    ▼               ガウス重み付き空間補間
RoomDimensions     正規化 0.0–1.0 出力
(手動入力 80% +         │
 ToF 20% 融合)          ▼
                   6×ReflectionMap
                   (正規化グリッド)
                        │
                   ┌────┴────┐
                   ▼         ▼
              StructureDetector   → ブラウザ UI
              (連結成分解析)         深度スライダーで
              (UIデフォルトOFF)      閾値範囲を指定し
                                    Canvas リアルタイム描画
```

### ToF 推定: MUSIC 超解像

```python
# 空間相関行列の固有値分解
Rxx = (1/K) Σ x(k) x(k)^H     # K: スナップショット数
Rxx = U Λ U^H                  # 固有値分解
# 雑音部分空間
Un = U[:, n_paths:]
# MUSIC スペクトラム
P(τ) = 1 / |a(τ)^H Un Un^H a(τ)|
# a(τ) = [1, e^{-j2πΔfτ}, ..., e^{-j2π(M-1)Δfτ}]^T
```

### 部屋寸法推定: 鏡像法逆変換

壁反射パスの距離から壁距離を逆算:

$$d_{wall} = \frac{\sqrt{d_{reflection}^2 - d_{direct}^2}}{2}$$

手動入力値がある場合は 80/20 融合: $d_{fused} = 0.8 \cdot d_{manual} + 0.2 \cdot d_{ToF}$

### 材質分類閾値

| 材質 | 反射強度 | 閾値 |
|------|---------|------|
| 金属管 (鋼管, 銅管) | 高 | ≥ 0.6 |
| 間柱 (木/軽鉄) | 中高 | 0.45–0.6 |
| 電気配線 (VVF) | 中 | 0.35–0.45 |
| 塩ビ管 (VP/VU) | 低 | 0.35–0.45 |

---

## UI 機能

### 深度スライダー (CTスキャン方式)

壁内の反射強度を深度に見立て、ユーザーがスライダーで表示範囲を調整する。

- **下限スライダー** (0–100): この値以下の反射強度を非表示
- **上限スライダー** (0–100): この値以上の反射強度を非表示
- **不透明度スライダー** (0–100): ヒートマップ全体の透明度を調整

各面 (6タブ) ごとにスライダー値を独立保持。タブ切替時に自動保存・復元される。

![説明](https://sspark.genspark.ai/cfimages?u1=%2B0jLHT%2FtanDnsd8Xv5UQDf4YXd5IhqLSxYKyDaNDbD84trPgRJq7wWk3A5Pgalh3D02gyqBq05TiRhrqFPmuGAZiM3RBIR6AzE7Z14yzfPyMNi6QRiGSOyZwqerp0jPS9wSZI2otWY2rv1yg76RYyim%2BVTeHuaBm&u2=Hnii8d%2F50tFaheNn&width=1024)

### カラーマップ切替

5 種類のカラーマップを即時切替:

| ID | 名称 | 用途 |
|----|------|------|
| thermal | サーマル | デフォルト。青→紫→マゼンタ→赤→オレンジ |
| heat | ヒート | 黒→赤→黄→白。高コントラスト |
| cool | クール | 黒→青→シアン→白。配線に最適 |
| grayscale | グレー | 白黒。印刷・PDF用 |
| rainbow | 虹 | 虹色全域。細かい強度差を視認 |

![説明](https://sspark.genspark.ai/cfimages?u1=%2F615NXX2%2Bt5GeshUxsI%2FzaAgBfAeJwi%2ByDIiYlcpPOvtcgO14xW%2FXW0qLpkpm2JAvd4JPdZuidMkH1O8U0jBLChyw3diU2jd34z0ocW5OnbBEY4qri5X1ithdm0KnKHbAYDOiWXkYPL7heFv93XQnrXyqfvu9fhr&u2=Rj5FtBwNwVSsqy75&width=1024)

### 3D ルームビュー

- Three.js による 6面 BOX 内面にヒートマップテクスチャを貼付
- OrbitControls で回転・ズーム操作
- 配管・異物を 3D 空間内にチューブ/球体で描画
- 深度スライダー・カラーマップ・不透明度が 2D/3D 連動

### その他 UI 機能

- **マウスホバーツールチップ**: Canvas 上の座標 (m) と反射強度値 (0.00–1.00) をリアルタイム表示
- **フィルターボタン**: 配管・配線 (デフォルトOFF) / 異物 / ヒートマップ を独立ON/OFF
- **周波数切替**: Mix (全帯域統合) / 2.4 GHz / 5 GHz(80MHz) / 5 GHz(160MHz) を即時切替
- **異物検出モーダル**: 不審デバイス検出時の詳細レポート表示
- **PDF/CSV レポート出力**: スキャン結果の外部エクスポート
- **起動時システムステータス表示**: OS・NIC・FeitCSI・モニターモードの状態をログに自動表示

---

## ディレクトリ構成

```
ruview-scan/
├── config/
│   ├── default.yaml ........... 測定パラメータ, 解析設定
│   └── setup_state.json ....... 構築状態永続化 (自動生成)
├── src/
│   ├── main.py ................ CLI: --simulate, --feitcsi, --skip-setup, --host, --port
│   ├── config.py .............. YAML → AppConfig (pydantic)
│   ├── errors.py .............. 例外階層 (RuViewError → 7サブクラス)
│   ├── setup/ ................. ★ 環境自動構築モジュール
│   │   ├── __init__.py
│   │   ├── setup_state.py .... 構築状態管理 (JSON永続化, カーネル版追跡)
│   │   ├── env_checker.py .... 環境スキャン (8項目チェック)
│   │   ├── offline_installer.py オフライン同梱パッケージインストール
│   │   ├── feitcsi_builder.py  FeitCSI ソースビルド自動化 (DKMS対応)
│   │   ├── monitor_setup.py .. AX210 モニターモード自動起動
│   │   └── boot_sequence.py .. 起動シーケンス統合制御
│   ├── api/
│   │   ├── server.py .......... AppState, FastAPI app, lifespan
│   │   ├── routes.py .......... REST 20 endpoints (/api/system/status 含む)
│   │   └── ws.py .............. WebSocket 進捗ストリーム
│   ├── csi/
│   │   ├── models.py .......... CSIFrame, DualBandCapture, ScanSession
│   │   ├── adapter.py ......... CSIAdapter ABC, FeitCSIAdapter, SimulatedAdapter
│   │   ├── feitcsi_bridge.py .. FeitCSI UDP ブリッジ (port 8008)
│   │   ├── feitcsi_parser.py .. FeitCSI .dat バイナリパーサー
│   │   ├── collector.py ....... DualBandCollector (3バンド切替)
│   │   └── calibration.py ..... PhaseCalibrator (STO/CPE 補正)
│   ├── scan/
│   │   ├── scan_manager.py .... セッション管理 (9点) + 進捗コールバック
│   │   ├── tof_estimator.py ... MUSIC / ESPRIT / IFFT 超解像
│   │   ├── aoa_estimator.py ... AoA 推定 (Phase F-1 統合予定)
│   │   ├── room_estimator.py .. 鏡像法逆変換 → RoomDimensions
│   │   ├── reflection_map.py .. CSI振幅→6面グリッド直接マッピング
│   │   ├── structure_detector.py 連結成分 → 配管/配線判定
│   │   └── foreign_detector.py  RF+CSI残差 → 不審デバイス検出
│   ├── fusion/
│   │   ├── band_merger.py ..... 2.4+5GHz 加重統合
│   │   ├── spatial_integrator.py 5点距離重み統合
│   │   └── view_generator.py .. 6面 JSON + Canvas 座標変換
│   ├── rf/
│   │   ├── scanner.py ......... パッシブRFスキャン
│   │   └── device_classifier.py OUI/RSSI/beacon → デバイス分類
│   └── utils/
│       ├── math_utils.py ...... MUSIC, ESPRIT, 相関行列
│       └── geo_utils.py ....... channel_to_freq, project_to_wall
├── setup/ ..................... ★ オフライン同梱パッケージ
│   ├── feitcsi/ ............... FeitCSI ソース (git clone 済み)
│   │   ├── FeitCSI/
│   │   └── FeitCSI-iwlwifi/
│   ├── deb/ ................... システム依存 deb パッケージ
│   ├── firmware/ .............. iwlwifi ファームウェア (AX210用)
│   ├── python_wheels/ ......... Python 依存パッケージ (.whl)
│   └── download_packages.sh ... 同梱パッケージ一括ダウンロードスクリプト
├── static/
│   ├── index.html ............. 3カラム UI (6面ビュー, 3D, 計測制御)
│   ├── css/style.css .......... ダークテーマ UI
│   └── js/
│       ├── app.js ............. メインモジュール + システムステータス表示
│       ├── scan_control.js .... 9点スキャン制御 + 3バンド
│       ├── websocket.js ....... WS 接続 + 自動再接続
│       ├── heatmap_renderer.js  サーバーグリッド描画 (5カラーマップ)
│       ├── floor_renderer.js .. 配管/異物/計測点 Canvas 描画
│       ├── room3d_three.js .... Three.js 3D ルームビュー
│       ├── report.js .......... PDF/CSV エクスポート
│       ├── audio.js ........... 異物検出アラート音
│       └── lib/ ............... Three.js, OrbitControls, jsPDF, html2canvas
├── docs/images/ ............... スクリーンショット
├── ruview.bat ................. Windows 起動スクリプト
├── ruview.sh .................. Linux 起動スクリプト
└── requirements.txt
```

---

## セットアップ

### 必要機材

| 機材 | 要件 | 用途 |
|------|------|------|
| モバイル Wi-Fi | 2.4 + 5 GHz デュアルバンド | TX (部屋中心に固定) |
| ノート PC | Intel AX210/AX211 搭載 | RX (5〜9箇所移動) |
| OS | Kali Linux / Ubuntu 22.04+ / Debian 系 | 実機運用 |
| OS (シミュレーション) | Windows / macOS / Linux 任意 | 開発・デモ |

### インストール

```bash
cd ruview-scan
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### オフラインパッケージの事前ダウンロード（実機用）

```bash
# オンライン環境で実行 — FeitCSI ソース・deb・firmware・wheels を setup/ に一括取得
bash setup/download_packages.sh
```

### 起動

```bash
# シミュレーションモード（物理ベース CSI 生成、NIC 不要）
python src/main.py --simulate

# 実機モード（FeitCSI 自動構築 → モニターモード → スキャン）
sudo python src/main.py

# FeitCSI モード強制
sudo python src/main.py --feitcsi

# セットアップスキップ（構築済み環境）
sudo python src/main.py --skip-setup
```

→ ブラウザで **http://127.0.0.1:8080** にアクセス

---

## 使い方

1. **部屋寸法を入力** — 幅(東西)・奥行(南北)・天井高をメジャーで測定し入力 → 「寸法を確定」
2. **モバイル Wi-Fi を部屋中心に設置**
3. **5〜9 箇所を順次スキャン** — 各壁から 1m の位置にノート PC を配置 → 「スキャン」
   (各ポイント: 2.4 GHz + 5 GHz(80MHz) + 5 GHz(160MHz) = 約 1.5 分/箇所。4隅はオプション)
4. **「スキャン結果を 3D 化」** を実行
5. **深度スライダーで壁内部を探索**:
   - 下限・上限スライダーを動かし、反射強度の表示範囲を絞り込む
   - カラーマップを変更して視認性を調整
   - マウスホバーで任意地点の座標・強度値を確認
6. **6 面タブ切替** で各面を確認 — 各面のスライダー設定は独立保持

---

## 依存関係

### 完全オフライン同梱 (setup/ フォルダ)

```
┌──────────────────────────────────────────────────────────────┐
│  [FeitCSI ソース]                                            │
│    FeitCSI/           → git clone --recursive 済み           │
│    FeitCSI-iwlwifi/   → git clone 済み                       │
│    ※起動時にカーネルに合わせてビルド（make → make install）   │
│                                                              │
│  [システム deb パッケージ]                                    │
│    build-essential, dkms, flex, bison                        │
│    libgtkmm-3.0-dev, libnl-genl-3-dev                       │
│    libiw-dev, libpcap-dev, iw, wireless-tools, rfkill        │
│                                                              │
│  [ファームウェア]                                             │
│    iwlwifi-ty-a0-gf-a0-*.ucode (AX210用)                    │
│                                                              │
│  [Python wheels]                                              │
│    fastapi, uvicorn, websockets, numpy, scipy, etc.          │
│                                                              │
│  [フロントエンド]                                             │
│    Three.js, jsPDF, html2canvas → static/js/lib/ に配置済み  │
└──────────────────────────────────────────────────────────────┘
```

### 起動時にのみ必要

```
┌──────────────────────────────────────────────────────────────┐
│  [linux-headers]                                             │
│    linux-headers-$(uname -r)                                 │
│    カーネル版が環境ごとに異なるため事前同梱不可               │
│    ※同梱 deb が一致すればオフラインでもOK                     │
│    ※不一致の場合のみ apt install が必要                      │
│                                                              │
│  → 同じカーネルで運用する限り完全オフライン                   │
│  → カーネル更新時のみ linux-headers の再取得が必要            │
└──────────────────────────────────────────────────────────────┘
```

---

## WebSocket

| Endpoint | 方向 | メッセージ type |
|----------|------|----------------|
| `/ws/scan` | Server→Client | `status`, `progress`, `scan_complete`, `error` |
| `/ws/scan` | Client→Server | `{action: "start_scan", point_id: "north"}` |

---

## シミュレーションモード

`--simulate` フラグで物理ベース CSI シミュレーションが起動する。

### `SimulatedAdapter` の仕組み

1. **鏡像法 (Image Source Method)** で壁反射経路を計算:
   - 4 壁 + 天井 + 床 = 6 鏡像ルーター
   - 各鏡像からの距離 → ToF

2. **配管散乱体** をシミュレーション:
   - 金属管, 電気配線, 塩ビ管, 間柱の 3D 座標を定義
   - 散乱体までの距離 + 材質別反射率 → $\alpha_n$

3. **サブキャリアごとの複素チャネル応答**:
   ```
   H(f_k) = Σ α_n · exp(-j·2π·f_k·τ_n) + noise
   ```

4. `set_point()` で計測点切替: 計測点の位置に応じてマルチパス構造が変化。9 点すべてに対応。

---

## 変更履歴

### Phase A (完了)
- CSI 取得・ToF 推定・基本 UI 実装
- buildResult フリーズ修正、手動寸法ハンドリング、エラーログ改善
- SimulatedAdapter による反射マップシミュレーション

### Phase B (完了)
- `reflection_map.py` 全面書き換え: 逆投影/既知座標カンニング → CSI 振幅直接マッピング
- 深度スライダー (下限・上限) を UI に追加
- `/api/result/map/{face}/{band}` グリッドデータ API 追加
- `heatmap_renderer.js` → サーバーグリッド描画方式 (`drawGrid`) に変更

### Phase B+ (完了)
- 5 種カラーマップ切替 (サーマル/ヒート/クール/グレー/虹)
- 不透明度スライダー
- プリセットボタン (全表示/壁表面/浅部/深部/自動)
- マウスホバーツールチップ (座標 + 反射強度値)
- Canvas ストレッチフィル (全面フル表示、アスペクト比非固定)
- 配管自動描画をデフォルト OFF 化

### Phase C (完了)
- 異物検出システム実装 (RF パッシブスキャン + CSI 残差解析)
- 脅威レベル分類 (high/medium/low/none)
- RSSI ベース位置推定
- 異物検出モーダル (詳細レポート表示)
- RF シミュレーション (正常 AP 3 台 + 不審デバイス 2 台)

### Phase D (完了)
- 160 MHz 帯域幅対応 (468 サブキャリア, 分解能 ≈ 0.94 m)
- 3 バンド収集 (2.4 GHz → 5 GHz 80 MHz → 5 GHz 160 MHz)
- 追加測定点 4 隅 (northeast/southeast/southwest/northwest) — オプション
- 測定点数 5 → 9 (必須 5 + 任意 4)
- UI: 160M 周波数ボタン、3 段プログレスバー、4 隅スキャンカード
- スキャン前から床面に全測定点を表示
- API: /result/map/{face}/{band} でバンド別オンデマンド生成

### Phase E (完了)
- Three.js 3D ルームビューア実装 (6面BOX + OrbitControls 回転/ズーム)
- 6面ヒートマップを3D BOX内面にテクスチャとして貼付
- 深度スライダー・カラーマップ・不透明度が3Dビューとリアルタイム連動
- ヒートマップ ON/OFF フィルタが2D・3D統一動作
- 配管・異物を3D空間内に描画 (チューブ/球体)
- 配管・異物の深度フィルタ対応 (depthプロパティベース)
- 方角ラベル (北/南/東/西) + 測定ポイント (pos.1-9) を3D空間に表示
- 2D描画でも配管・異物に深度フィルタ適用
- PDF/CSV レポート出力

### Phase F-0 (完了)
- PicoScenes → FeitCSI に完全切替（オープンソース、OS/カーネル非依存）
- 環境自動構築システム実装（8項目チェック: OS/Arch/CPU/NIC/FW/Headers/FeitCSI/Deps）
- オフラインインストーラ（setup/ フォルダに deb/firmware/wheels を同梱）
- FeitCSI ソース自動ビルド（DKMS 対応、カーネル変更時は自動再ビルド）
- AX210 モニターモード自動起動 + FeitCSI UDP サービス起動
- 起動シーケンス統合（boot_sequence.py → 環境チェック → インストール → ビルド → モニター → WebUI）
- FeitCSI UDP ブリッジ（port 8008）+ .dat バイナリパーサー
- CSI アダプタに FeitCSIAdapter 追加（feitcsi/picoscenes/simulate 3択、デフォルト feitcsi）
- main.py 改修（--feitcsi / --skip-setup オプション追加、ブート結果の自動判定）
- WebUI システムステータス表示（/api/system/status + ログエリア自動表示）

---

## ロードマップ

| Phase | 内容 | 状態 |
|-------|------|------|
| **A** | CSI 取得, ToF 推定, 基本 UI | ✅ 完了 |
| **B** | CSI 振幅直接マッピング, 深度スライダー | ✅ 完了 |
| **B+** | カラーマップ, 不透明度, プリセット, ホバーツールチップ | ✅ 完了 |
| **C** | 異物検出, RF パッシブスキャン, 脅威レベル分類 | ✅ 完了 |
| **D** | 160 MHz 対応 (≈0.94 m 分解能), 追加測定点 (5→9) | ✅ 完了 |
| **E** | 3D ビュー (Three.js), PDF/CSV レポート出力 | ✅ 完了 |
| **F-0** | FeitCSI 統合, 環境自動構築, オフラインセットアップ | ✅ 完了 |
| **F-1** | 実機キャリブレーション, AoA 統合, DI パターン | 🔧 予定 |

---

## ライセンス

Private — 無断転載・複製禁止（商用利用不可）