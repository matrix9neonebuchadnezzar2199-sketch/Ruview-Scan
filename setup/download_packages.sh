#!/bin/bash
# ============================================================
# RuView Scan - Offline Package Downloader
# オフライン同梱パッケージを一括ダウンロードするスクリプト
#
# 使い方: オンライン環境のUbuntu/Debian/Kali上で実行
#   chmod +x download_packages.sh
#   ./download_packages.sh
#
# ダウンロード先:
#   setup/deb/           - システムdebパッケージ
#   setup/firmware/       - iwlwifiファームウェア
#   setup/feitcsi/        - FeitCSIソースコード
#   setup/python_wheels/  - Pythonパッケージ(wheel)
# ============================================================
# ERR-F007: download_packages.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETUP_DIR="$SCRIPT_DIR"

echo "============================================"
echo "  RuView Scan - Offline Package Downloader"
echo "============================================"
echo "  保存先: $SETUP_DIR"
echo ""

# --- ディレクトリ作成 ---
mkdir -p "$SETUP_DIR/deb"
mkdir -p "$SETUP_DIR/firmware"
mkdir -p "$SETUP_DIR/feitcsi"
mkdir -p "$SETUP_DIR/python_wheels"

# ============================================================
# 1. FeitCSI ソースコード (GitHub)
# ============================================================
echo ""
echo "[1/5] FeitCSI ソースコード"
echo "----------------------------------------------"

if [ -d "$SETUP_DIR/feitcsi/FeitCSI-iwlwifi/.git" ]; then
    echo "  FeitCSI-iwlwifi: 既存。git pull で更新..."
    cd "$SETUP_DIR/feitcsi/FeitCSI-iwlwifi"
    git pull || echo "  ⚠️  pull失敗（オフラインの可能性）"
    cd "$SCRIPT_DIR"
else
    echo "  FeitCSI-iwlwifi: git clone..."
    git clone https://github.com/KuskoSoft/FeitCSI-iwlwifi.git \
        "$SETUP_DIR/feitcsi/FeitCSI-iwlwifi"
fi

if [ -d "$SETUP_DIR/feitcsi/FeitCSI/.git" ]; then
    echo "  FeitCSI: 既存。git pull で更新..."
    cd "$SETUP_DIR/feitcsi/FeitCSI"
    git pull || echo "  ⚠️  pull失敗（オフラインの可能性）"
    cd "$SCRIPT_DIR"
else
    echo "  FeitCSI: git clone..."
    git clone https://github.com/KuskoSoft/FeitCSI.git \
        "$SETUP_DIR/feitcsi/FeitCSI"
fi

# FeitCSI deb パッケージもダウンロード
echo "  FeitCSI deb パッケージをダウンロード..."
wget -q -nc -P "$SETUP_DIR/deb/" \
    "https://github.com/KuskoSoft/FeitCSI/releases/download/v2.0.0/feitcsi-iwlwifi_2.0.0_all.deb" \
    || echo "  ⚠️  feitcsi-iwlwifi deb ダウンロード失敗"
wget -q -nc -P "$SETUP_DIR/deb/" \
    "https://github.com/KuskoSoft/FeitCSI/releases/download/v2.0.0/feitcsi_2.0.0_all.deb" \
    || echo "  ⚠️  feitcsi deb ダウンロード失敗"

echo "  ✅ FeitCSI ソース完了"

# ============================================================
# 2. システム deb パッケージ
# ============================================================
echo ""
echo "[2/5] システム deb パッケージ"
echo "----------------------------------------------"

# apt-get download でカレントディレクトリに.debを取得
cd "$SETUP_DIR/deb"

PACKAGES=(
    build-essential
    dkms
    flex
    bison
    libgtkmm-3.0-dev
    libnl-genl-3-dev
    libiw-dev
    libpcap-dev
    iw
    wireless-tools
    rfkill
    pciutils
    usbutils
)

for pkg in "${PACKAGES[@]}"; do
    echo "  Downloading: $pkg"
    apt-get download "$pkg" 2>/dev/null || echo "    ⚠️  $pkg ダウンロード失敗"
done

# 依存パッケージも一括ダウンロード
echo "  依存パッケージを追加ダウンロード中..."
apt-get download $(apt-cache depends --recurse --no-recommends --no-suggests \
    --no-conflicts --no-breaks --no-replaces --no-enhances \
    build-essential dkms flex libgtkmm-3.0-dev libnl-genl-3-dev \
    libiw-dev libpcap-dev 2>/dev/null | grep "^\w" | sort -u) 2>/dev/null \
    || echo "  ⚠️  一部の依存パッケージダウンロード失敗"

cd "$SCRIPT_DIR"

DEB_COUNT=$(ls -1 "$SETUP_DIR/deb/"*.deb 2>/dev/null | wc -l)
echo "  ✅ ${DEB_COUNT}個の.debパッケージ取得完了"

# ============================================================
# 3. iwlwifi ファームウェア
# ============================================================
echo ""
echo "[3/5] iwlwifi ファームウェア"
echo "----------------------------------------------"

# システムからコピー
FW_PATTERNS=(
    "/lib/firmware/iwlwifi-ty-a0-gf-a0-*"
    "/lib/firmware/iwlwifi-ty-a0-gf-a0.pnvm"
    "/lib/firmware/iwlwifi-so-a0-gf-a0-*"
)

FW_COPIED=0
for pattern in "${FW_PATTERNS[@]}"; do
    for fw in $pattern; do
        if [ -f "$fw" ]; then
            cp -n "$fw" "$SETUP_DIR/firmware/" 2>/dev/null && FW_COPIED=$((FW_COPIED+1))
        fi
    done
done

if [ $FW_COPIED -eq 0 ]; then
    echo "  ⚠️  ローカルにファームウェアなし。linux-firmware から取得を試行..."
    # linux-firmware git リポジトリから直接ダウンロード
    for fw_name in iwlwifi-ty-a0-gf-a0-89.ucode iwlwifi-ty-a0-gf-a0.pnvm; do
        wget -q -nc -P "$SETUP_DIR/firmware/" \
            "https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/$fw_name" \
            2>/dev/null || echo "    ⚠️  $fw_name ダウンロード失敗"
    done
fi

FW_COUNT=$(ls -1 "$SETUP_DIR/firmware/"* 2>/dev/null | wc -l)
echo "  ✅ ${FW_COUNT}個のファームウェア取得完了"

# ============================================================
# 4. Python wheels
# ============================================================
echo ""
echo "[4/5] Python wheels"
echo "----------------------------------------------"

# プロジェクトルートの requirements.txt を探す
REQ_FILE="$(dirname "$SETUP_DIR")/requirements.txt"

if [ -f "$REQ_FILE" ]; then
    echo "  requirements.txt からwheelをダウンロード..."
    pip download -r "$REQ_FILE" -d "$SETUP_DIR/python_wheels/" \
        2>/dev/null || echo "  ⚠️  一部のwheelダウンロード失敗"
else
    echo "  requirements.txt が見つかりません。主要パッケージのみダウンロード..."
    pip download -d "$SETUP_DIR/python_wheels/" \
        fastapi uvicorn websockets numpy scipy aiofiles \
        2>/dev/null || echo "  ⚠️  一部のwheelダウンロード失敗"
fi

# CSIKit（FeitCSI パーサー対応）
pip download -d "$SETUP_DIR/python_wheels/" \
    csiread 2>/dev/null || echo "  ⚠️  csiread ダウンロード失敗"

WHL_COUNT=$(ls -1 "$SETUP_DIR/python_wheels/"*.whl 2>/dev/null | wc -l)
echo "  ✅ ${WHL_COUNT}個のwheelパッケージ取得完了"

# ============================================================
# 5. サマリー
# ============================================================
echo ""
echo "============================================"
echo "  ダウンロード完了サマリー"
echo "============================================"
echo "  FeitCSI ソース:   $([ -d "$SETUP_DIR/feitcsi/FeitCSI" ] && echo '✅' || echo '❌')"
echo "  deb パッケージ:   ${DEB_COUNT}個"
echo "  ファームウェア:   ${FW_COUNT}個"
echo "  Python wheels:    ${WHL_COUNT}個"
echo ""

# ディスク使用量
TOTAL_SIZE=$(du -sh "$SETUP_DIR" 2>/dev/null | cut -f1)
echo "  合計サイズ: $TOTAL_SIZE"
echo "============================================"
echo ""
echo "このsetup/フォルダをプロジェクトと一緒に持ち運べば"
echo "オフライン環境でもセットアップ可能です。"
