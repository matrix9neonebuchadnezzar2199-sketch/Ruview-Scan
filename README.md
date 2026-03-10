# RuView Scan

Wi-Fi CSI (Channel State Information) による部屋スキャンツール

## 概要

部屋の6面（床・天井・四方の壁）を Wi-Fi CSI で透視し、壁内の配管・配線・構造物を検出、さらに盗聴器などの不審デバイスを発見するツール。

## 必要機材

| 機材 | 要件 |
|------|------|
| モバイルWi-Fiルーター | 2.4GHz + 5GHz デュアルバンド対応 |
| ノートPC | Intel AX210/AX211 搭載 (CSI取得対応) |
| OS | Kali Linux 2024+ 推奨 |

## セットアップ

```bash
# 1. Python仮想環境
python3 -m venv venv
source venv/bin/activate

# 2. 依存パッケージ
pip install -r requirements.txt

# 3. PicoScenes (CSIツール) のインストール
#    → https://ps.zpj.io/
```

## 起動

### シミュレーションモード (Windows/Mac対応)
```bash
# Linux
bash ruview.sh --simulate

# Windows
ruview.bat --simulate
```

### 実機モード (Kali Linux)
```bash
sudo bash ruview.sh
```

ブラウザで `http://127.0.0.1:8080` にアクセス

## 使い方

1. モバイルWi-Fiルーターを部屋の中央に設置
2. ノートPCを **5箇所**（北壁側→東→南→西→中心）に移動しながら順次「スキャン」
3. 各ポイントで 2.4GHz(30秒) + 5GHz(30秒) = 約1分のCSIを自動収集
4. 全5箇所完了後「スキャン結果を3D化」を実行
5. 6面切替・ヒートマップ・配管/異物フィルターで結果を確認

## ディレクトリ構成

```
ruview-scan/
├── config/default.yaml     設定ファイル
├── src/
│   ├── main.py             CLIエントリポイント
│   ├── config.py           設定ローダー
│   ├── errors.py           カスタム例外
│   ├── api/                FastAPI (REST + WebSocket)
│   ├── csi/                CSIデータ取得・解析
│   ├── scan/               空間推定・検出
│   ├── fusion/             データ統合
│   ├── rf/                 RFスキャン
│   └── utils/              ユーティリティ
├── static/                 フロントエンド
│   ├── index.html
│   ├── css/style.css
│   └── js/*.js
├── ruview.sh               Linux起動スクリプト
├── ruview.bat              Windows起動スクリプト
└── requirements.txt
```

## API

| Endpoint | Method | 説明 |
|----------|--------|------|
| `/api/health` | GET | ヘルスチェック |
| `/api/session/create` | POST | セッション作成 |
| `/api/scan/{point}/start` | POST | スキャン開始 |
| `/api/scan/status` | GET | スキャン状態 |
| `/api/build` | POST | 3D化実行 |
| `/api/result/room` | GET | 部屋寸法 |
| `/api/result/structures` | GET | 検出構造物 |
| `/api/result/foreign` | GET | 異物情報 |
| `/ws/scan` | WS | リアルタイム進捗 |
