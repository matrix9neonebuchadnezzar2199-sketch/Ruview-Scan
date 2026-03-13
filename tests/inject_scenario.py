#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RuView Scan - シナリオ注入スクリプト
====================================
起動済みの RuView Scan (--simulate モード) に対して、
YAMLシナリオファイルのデータを API 経由で注入し、
5点スキャン → 3D化 を自動実行する。

使い方:
    # ターミナル1: ツール起動
    python src/main.py --simulate

    # ターミナル2: シナリオ注入
    python tests/inject_scenario.py --scenario tests/scenarios/scenario_office.yaml
    python tests/inject_scenario.py --scenario tests/scenarios/scenario_hotel.yaml
    python tests/inject_scenario.py --scenario tests/scenarios/scenario_empty.yaml

    # ブラウザで確認
    http://127.0.0.1:8080
"""

import argparse
import json
import sys
import time
from pathlib import Path

import yaml
import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
REQUIRED_POINTS = ["north", "east", "south", "west", "center"]


def load_scenario(path: str) -> dict:
    """YAMLシナリオファイルを読み込む"""
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] シナリオファイルが見つかりません: {path}")
        sys.exit(1)

    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # バリデーション
    if "room" not in data:
        print("[ERROR] 'room' セクションが必要です")
        sys.exit(1)
    for key in ("width", "depth", "height"):
        if key not in data["room"]:
            print(f"[ERROR] room.{key} が必要です")
            sys.exit(1)

    return data


def wait_for_server(base_url: str, timeout: int = 30):
    """サーバーの起動を待つ"""
    print(f"[INFO] サーバー接続待ち: {base_url}")
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{base_url}/api/health", timeout=3)
            if r.status_code == 200:
                data = r.json()
                print(f"[OK]   サーバー接続成功 (CSI: {data.get('csi_source', '?')})")
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)

    print(f"[ERROR] サーバーに接続できません ({timeout}秒タイムアウト)")
    print(f"        先に 'python src/main.py --simulate' を実行してください")
    sys.exit(1)


def inject_scenario(base_url: str, scenario: dict):
    """シナリオデータをサーバーに注入"""
    print(f"\n[INFO] シナリオ注入: {scenario.get('scenario', {}).get('name', '不明')}")

    payload = {
        "room": scenario["room"],
        "router": scenario.get("router", {}),
        "structures": scenario.get("structures", []),
        "foreign_objects": scenario.get("foreign_objects", []),
        "simulation": scenario.get("simulation", {}),
    }

    r = requests.post(
        f"{base_url}/api/test/load-scenario",
        json=payload,
        timeout=10,
    )

    if r.status_code == 200:
        data = r.json()
        print(f"[OK]   シナリオ注入成功")
        print(f"       部屋: {data.get('room_dims', '?')}")
        print(f"       構造物: {data.get('structure_count', 0)}個")
        print(f"       異物: {data.get('foreign_count', 0)}個")
    else:
        print(f"[ERROR] シナリオ注入失敗: {r.status_code} {r.text}")
        sys.exit(1)


def reset_session(base_url: str):
    """既存セッションをリセット"""
    print("\n[INFO] セッションリセット")
    r = requests.post(f"{base_url}/api/reset", timeout=10)
    if r.status_code == 200:
        print("[OK]   リセット完了")
    else:
        print(f"[WARN] リセット失敗: {r.status_code}")


def create_session(base_url: str, room_name: str):
    """スキャンセッション作成"""
    print(f"\n[INFO] セッション作成: {room_name}")
    r = requests.post(
        f"{base_url}/api/session/create",
        params={"room_name": room_name},
        timeout=10,
    )
    if r.status_code == 200:
        data = r.json()
        print(f"[OK]   セッション: {data.get('session_id', '?')}")
    else:
        print(f"[ERROR] セッション作成失敗: {r.status_code}")
        sys.exit(1)


def run_scan_point(base_url: str, point_id: str):
    """1計測点のスキャンを実行し、完了を待つ"""
    labels = {
        "north": "① 北壁側", "east": "② 東壁側",
        "south": "③ 南壁側", "west": "④ 西壁側",
        "center": "⑤ 中心",
    }
    label = labels.get(point_id, point_id)
    print(f"\n[SCAN] {label} ({point_id}) スキャン開始...")

    # スキャン開始
    r = requests.post(f"{base_url}/api/scan/{point_id}/start", timeout=10)
    if r.status_code != 200:
        print(f"[ERROR] スキャン開始失敗: {r.status_code} {r.text}")
        sys.exit(1)

    # 完了待ち (ポーリング)
    max_wait = 120  # 秒
    start = time.time()
    last_progress = -1

    while time.time() - start < max_wait:
        time.sleep(1)
        r = requests.get(f"{base_url}/api/scan/status", timeout=10)
        if r.status_code != 200:
            continue

        status = r.json()

        # 完了判定
        if point_id in status.get("completed", []):
            elapsed = time.time() - start
            print(f"[OK]   {label} 完了 ({elapsed:.1f}秒)")
            return True

        # スキャン中の進捗表示
        if status.get("scanning") and status.get("scanning_point") == point_id:
            progress = status.get("progress", 0)
            pct = int(progress * 100)
            if pct != last_progress:
                print(f"       進捗: {pct}%", end="\r")
                last_progress = pct

    print(f"[ERROR] {label} タイムアウト ({max_wait}秒)")
    sys.exit(1)


def run_build(base_url: str, room: dict):
    """3D化処理を実行"""
    print(f"\n[BUILD] 3D化処理開始...")

    params = {
        "manual_width": room["width"],
        "manual_depth": room["depth"],
        "manual_height": room["height"],
    }
    print(f"[DEBUG] Build URL: {base_url}/api/build")
    print(f"[DEBUG] Params: {params}")

    r = requests.post(
        f"{base_url}/api/build",
        params=params,
        timeout=60,
    )

    if r.status_code == 200:
        data = r.json()
        room_data = data.get("room", {})
        structures = data.get("structures", [])
        foreign = data.get("foreign", [])

        print(f"[OK]   3D化完了")
        print(f"       部屋寸法: {room_data.get('width')}m × {room_data.get('depth')}m × {room_data.get('height')}m")
        print(f"       面積: {room_data.get('area', 0):.1f}㎡")
        print(f"       構造物検出: {len(structures)}個")
        print(f"       異物検出: {len(foreign)}個")

        if structures:
            print(f"\n       --- 検出構造物 ---")
            for s in structures:
                print(f"       [{s.get('face')}] {s.get('label', s.get('material'))} "
                      f"信頼度: {s.get('confidence', 0):.0%}")

        if foreign:
            print(f"\n       --- 検出異物 ---")
            for f in foreign:
                print(f"       [{f.get('face')}] {f.get('label')} "
                      f"脅威: {f.get('threat_level', '?')} "
                      f"信頼度: {f.get('confidence', 0):.0%}")

        return data
    else:
        print(f"[ERROR] 3D化失敗: {r.status_code} {r.text}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="RuView Scan シナリオ注入スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python tests/inject_scenario.py --scenario tests/scenarios/scenario_office.yaml
  python tests/inject_scenario.py --scenario tests/scenarios/scenario_hotel.yaml --url http://192.168.1.100:8080
        """,
    )
    parser.add_argument(
        "--scenario", "-s",
        required=True,
        help="YAMLシナリオファイルのパス",
    )
    parser.add_argument(
        "--url", "-u",
        default=DEFAULT_BASE_URL,
        help=f"RuView ScanサーバーのURL (デフォルト: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="スキャンをスキップしてシナリオ注入のみ実行",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="3D化処理をスキップ (スキャンのみ実行)",
    )

    args = parser.parse_args()

    # ヘッダー表示
    print("=" * 56)
    print("  RuView Scan - シナリオ注入テスト")
    print("=" * 56)

    # 1. シナリオ読み込み
    scenario = load_scenario(args.scenario)
    scenario_info = scenario.get("scenario", {})
    print(f"\nシナリオ: {scenario_info.get('name', '不明')}")
    print(f"説明:     {scenario_info.get('description', '-')}")
    room = scenario["room"]
    print(f"部屋:     {room['width']}m × {room['depth']}m × {room['height']}m")
    print(f"構造物:   {len(scenario.get('structures', []))}個")
    print(f"異物:     {len(scenario.get('foreign_objects', []))}個")

    # 2. サーバー接続確認
    wait_for_server(args.url)

    # 3. セッションリセット
    reset_session(args.url)

    # 4. シナリオ注入
    inject_scenario(args.url, scenario)

    if args.skip_scan:
        print("\n[INFO] --skip-scan: スキャンをスキップしました")
        print(f"\n[DONE] ブラウザで確認: {args.url}")
        return

    # 5. セッション作成
    create_session(args.url, scenario_info.get("name", "test"))

    # 6. 5点スキャン実行
    print("\n" + "=" * 56)
    print("  5点スキャン自動実行")
    print("=" * 56)

    total_start = time.time()
    for point_id in REQUIRED_POINTS:
        run_scan_point(args.url, point_id)

    scan_elapsed = time.time() - total_start
    print(f"\n[OK]   全5点スキャン完了 (合計: {scan_elapsed:.1f}秒)")

    if args.no_build:
        print("\n[INFO] --no-build: 3D化をスキップしました")
        print(f"\n[DONE] ブラウザで手動で「3D化」ボタンを押してください: {args.url}")
        return

    # 7. 3D化
    print("\n" + "=" * 56)
    print("  3D化処理")
    print("=" * 56)
    run_build(args.url, room)

    # 8. 完了
    print("\n" + "=" * 56)
    print("  完了")
    print("=" * 56)
    print(f"\n  ブラウザで結果を確認してください:")
    print(f"  {args.url}")
    print(f"\n  操作ガイド:")
    print(f"  - 床/天井/北壁/南壁/東壁/西壁 タブで各面を切替")
    print(f"  - 「3D」タブで6面一括3D表示")
    print(f"  - 深度スライダーで壁面内の深さをフィルタ")
    print(f"  - カラーマップ切替で視認性を調整")
    print(f"  - 構造物/異物 フィルタのON/OFFが可能")


if __name__ == "__main__":
    main()
