# RuView Scan

**Wi-Fi CSI 壁面透視スキャナ — 6 面同時可視化 / 配管検出 / 異物(盗聴器)検出**

> 1 台のモバイル Wi-Fi ルーター + 1 台のノート PC で、部屋の壁・床・天井の **内部構造** を非接触で透視する。

---

## 動作原理

### CSI (Channel State Information) とは

Wi-Fi フレームの各サブキャリアに対する複素チャネル応答 $H(f_k)$ を取得する技術。振幅はパス損失・反射強度を、位相は伝搬遅延（ToF）を含む。Intel AX210 + [PicoScenes](https://ps.zpj.io/) で 100 Hz サンプリング可能。

### マルチパス反射モデル

チャネル応答は以下のマルチパス合成で表現される:

$$H(f_k) = \sum_{n=0}^{N-1} \alpha_n \cdot e^{-j2\pi f_k \tau_n}$$

| 記号 | 意味 |
|------|-----|
| $\alpha_n$ | 第 n パスの複素振幅（反射材質で変化） |
| $\tau_n$ | 第 n パスの伝搬遅延 = 距離 / 光速 |
| $f_k$ | 第 k サブキャリア周波数 |

壁内の金属管・電気配線・塩ビ管はそれぞれ反射率が異なり、$\alpha_n$ の大きさから材質を推定できる。

### 測定方式: 5 点シーケンシャル

```
        北壁
    ┌─────────────┐
    │     ① (北)  │
    │             │
 西 │④      ⑤    │② 東
    │      (中心) │
    │     ③ (南)  │
    └─────────────┘
        南壁

TX: モバイルWi-Fi (部屋中心, 固定)
RX: ノートPC (①→②→③→④→⑤ 移動)
```

各ポイントで 2.4 GHz (ch1, 40 MHz, 114 sc) + 5 GHz (ch36, 80 MHz, 234 sc) を各 30 秒収集。距離分解能:

| バンド | 帯域幅 | 理論分解能 $c / (2 \cdot BW)$ |
|--------|--------|------------------------------|
| 2.4 GHz | 40 MHz | 3.75 m |
| 5 GHz | 80 MHz | **1.875 m** |

5 GHz が主要推定帯域、2.4 GHz は壁透過性が高いため補完に使用。

---

## システムアーキテクチャ

```
┌──────────────┐     ┌───────────────────────────────────────────┐
│  Browser UI  │◄────►  FastAPI Server (uvicorn, port 8080)     │
│  (6面ビュー) │ WS  │                                           │
└──────────────┘     │  routes.py ── REST API (19 endpoints)     │
                     │  ws.py ───── WebSocket /ws/scan           │
                     │                                           │
                     │  ┌─── CSI Layer ────────────────────┐     │
                     │  │ adapter.py   PicoScenes / Sim     │     │
                     │  │ collector.py DualBandCollector     │     │
                     │  │ calibration.py PhaseCalibrator     │     │
                     │  │ models.py    CSIFrame / Session    │     │
                     │  └──────────────────────────────────┘     │
                     │  ┌─── Scan Layer ───────────────────┐     │
                     │  │ tof_estimator.py   MUSIC / ESPRIT │     │
                     │  │ aoa_estimator.py   (Phase B)      │     │
                     │  │ room_estimator.py  壁距離推定      │     │
                     │  │ reflection_map.py  6面ヒートマップ │     │
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

---

## 処理パイプライン

```
CSIFrame収集 (5点×2バンド)
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
(鏡像法逆変換)      (sim: 既知配管投影 / 実機: 逆投影法)
    │                   │
    ▼                   ▼
RoomDimensions     6×ReflectionMap (0.05m解像度グリッド)
(手動入力 80% +        │
 ToF 20% 融合)         ▼
                   StructureDetector
                   (連結成分解析 → 材質分類)
                        │
    ┌───────────────────┤
    ▼                   ▼
ForeignDetector    BandMerger → SpatialIntegrator → ViewGenerator
(RF+CSI残差)           │
    │                   ▼
    └──────────► JSON Response → フロントエンド描画
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

手動入力値がある場合は 80/20 融合:
$d_{fused} = 0.8 \cdot d_{manual} + 0.2 \cdot d_{ToF}$

### 材質分類閾値

| 材質 | 反射強度 | 閾値 |
|------|---------|------|
| 金属管 (鋼管, 銅管) | 高 | ≥ 0.6 |
| 間柱 (木/軽鉄) | 中高 | 0.45–0.6 |
| 電気配線 (VVF) | 中 | 0.35–0.45 |
| 塩ビ管 (VP/VU) | 低 | 0.35–0.45 |

---

## ディレクトリ構成

```
ruview-scan/
├── config/
│   └── default.yaml ........... 測定パラメータ, 解析設定, サーバー設定
├── src/
│   ├── main.py ................ CLI (click): --simulate, --host, --port
│   ├── config.py .............. YAML → AppConfig (pydantic)
│   ├── errors.py .............. 例外階層 (RuViewError → 7サブクラス)
│   ├── api/
│   │   ├── server.py .......... AppState (シングルトン), FastAPI app
│   │   ├── routes.py .......... REST 19 endpoints, /build 融合ロジック
│   │   └── ws.py .............. WebSocket 進捗ストリーム
│   ├── csi/
│   │   ├── models.py .......... CSIFrame, DualBandCapture, ScanSession
│   │   ├── adapter.py ......... CSIAdapter ABC, PicoScenesAdapter, SimulatedAdapter
│   │   ├── collector.py ....... DualBandCollector (バンド切替 + 収集)
│   │   └── calibration.py ..... PhaseCalibrator (STO/CPE 補正)
│   ├── scan/
│   │   ├── scan_manager.py .... セッション管理 + 進捗コールバック
│   │   ├── tof_estimator.py ... MUSIC / ESPRIT / IFFT (超解像 ToF)
│   │   ├── aoa_estimator.py ... AoA 推定 (Phase B 統合予定)
│   │   ├── room_estimator.py .. 5点ToF → 鏡像法逆変換 → RoomDimensions
│   │   ├── reflection_map.py .. sim: 既知配管投影 / 実機: 距離ベース逆投影
│   │   ├── structure_detector.py  連結成分 → 配管/配線判定
│   │   └── foreign_detector.py .. RF+CSI残差 → 不審デバイス検出
│   ├── fusion/
│   │   ├── band_merger.py ..... 2.4+5GHz ヒートマップ加重統合
│   │   ├── spatial_integrator.py  5点の寄与を距離重み統合
│   │   └── view_generator.py .. 6面 JSON + Canvas 座標変換
│   ├── rf/
│   │   ├── scanner.py ......... iw パッシブスキャン (ch→freq全帯域対応)
│   │   └── device_classifier.py  OUI, RSSI, beacon → デバイス分類
│   └── utils/
│       ├── math_utils.py ...... MUSIC, ESPRIT, 相関行列
│       └── geo_utils.py ....... channel_to_freq, project_to_wall, 鏡像法
├── static/
│   ├── index.html ............. 3カラムレイアウト (6面ビュー, 3D, 計測制御)
│   ├── css/style.css .......... ダークテーマ UI
│   └── js/
│       ├── app.js ............. メインモジュール (RuView IIFE)
│       ├── scan_control.js .... 5点スキャン制御 + SIM フォールバック
│       ├── websocket.js ....... WS 接続 + 自動再接続
│       ├── heatmap_renderer.js  Canvas ヒートマップ描画
│       ├── floor_renderer.js .. 配管/異物/計測点 Canvas 描画
│       ├── room3d.js .......... アイソメ 3D 部屋ビュー
│       └── audio.js ........... 異物検出アラート音
├── ruview.bat ................. Windows 起動スクリプト
├── ruview.sh .................. Linux 起動 (monitor mode 自動設定)
└── requirements.txt
```

---

## セットアップ

### 必要機材

| 機材 | 要件 | 用途 |
|------|------|------|
| モバイル Wi-Fi | 2.4 + 5 GHz デュアルバンド | TX (部屋中心に固定) |
| ノート PC | Intel AX210/AX211 搭載 | RX (5箇所移動) |
| OS | Kali Linux 2024+ / Windows 10+ | 実機: Kali, シミュレーション: 任意 |

### インストール

```bash
cd ruview-scan
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 実機のみ: PicoScenes インストールが必要
# → https://ps.zpj.io/
```

### 起動

```bash
# シミュレーション (物理ベース CSI 生成)
ruview.bat --simulate              # Windows
bash ruview.sh --simulate          # Linux

# 実機 (PicoScenes + monitor mode)
sudo bash ruview.sh
```

→ ブラウザで **http://127.0.0.1:8080** にアクセス

---

## 使い方

1. **部屋寸法を入力** — 幅(東西)・奥行(南北)・天井高をメジャーで測定し入力 → 「寸法を確定」
2. **モバイル Wi-Fi を部屋中心に設置**
3. **5 箇所を順次スキャン** — 各壁から 1m の位置にノート PC を配置 → 「スキャン」  
   (各ポイント: 2.4 GHz 30 秒 + 5 GHz 30 秒 = 約 1 分)
4. **「スキャン結果を 3D 化」** を実行
5. **6 面タブ切替** で壁内構造を確認 — フィルター (配管/異物/ヒートマップ) + 周波数切替

---

## API リファレンス

### REST Endpoints

| Endpoint | Method | 説明 | パラメータ |
|----------|--------|------|-----------|
| `/api/health` | GET | ヘルスチェック | — |
| `/api/session/create` | POST | セッション作成 | — |
| `/api/scan/{point_id}/start` | POST | スキャン開始 | point_id: north/east/south/west/center |
| `/api/scan/{point_id}/status` | GET | ポイント別状態 | — |
| `/api/scan/status` | GET | 全体状態 | — |
| `/api/build` | POST | 3D 化実行 | `?manual_width=&manual_depth=&manual_height=` (Optional) |
| `/api/result/room` | GET | 推定部屋寸法 | — |
| `/api/result/structures` | GET | 検出構造物リスト | — |
| `/api/result/foreign` | GET | 異物情報 | — |
| `/api/reset` | POST | セッションリセット | — |

### WebSocket

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
   → 位相・振幅が周波数選択性フェージングを再現

4. `set_point()` で計測点切替: 計測点の位置に応じてマルチパス構造が変化

---

## 設計思想

- **「部屋の外形は人間が測り、壁の中身は CSI が透視する」** — 80 MHz 帯域幅での距離分解能は 1.875 m。部屋寸法推定には不十分だが、壁内の反射パターン解析には十分
- **シミュレーション / 実機の自動切替** — `SimulatedAdapter` の MAC アドレス (`AA:BB:CC:DD:EE:FF`) で判定し、反射マップ生成ロジックを分岐
- **TSCM (Technical Surveillance Countermeasures) 対応** — RF パッシブスキャンと CSI 残差解析を組み合わせて盗聴器等の不審デバイスを検出

---

## ロードマップ

| Phase | 内容 | 状態 |
|-------|------|------|
| **A** | CSI 取得, ToF 推定, 基本 UI | ✅ 完了 |
| **B** | AoA 統合, Hough 変換による配管方向推定 | 🔧 予定 |
| **C** | RF パッシブスキャン + 異物検出の精度向上 | 🔧 予定 |
| **D** | テスト基盤, DI パターン, ログ永続化 | 🔧 予定 |

---

## ライセンス

Private — 無断転載・複製禁止
