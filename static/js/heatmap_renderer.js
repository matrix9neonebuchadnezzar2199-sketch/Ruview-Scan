/**
 * RuView Scan - ヒートマップ描画エンジン (Phase B: gridデータ直接描画)
 *
 * サーバーから受信した反射マップ (grid: 2D配列, 0.0〜1.0) を
 * Canvas上に直接描画する。スライダーの閾値範囲内の値のみ色付け。
 */
const HeatmapRenderer = (function() {

    /**
     * gridデータをCanvasに描画
     * @param {CanvasRenderingContext2D} ctx
     * @param {number[][]} grid - サーバーから受信した2D配列 (0.0〜1.0)
     * @param {number} offX - 描画オフセットX (px)
     * @param {number} offY - 描画オフセットY (px)
     * @param {number} drawW - 描画領域の幅 (px)
     * @param {number} drawH - 描画領域の高さ (px)
     * @param {number} lower - 下限閾値 (0.0〜1.0)
     * @param {number} upper - 上限閾値 (0.0〜1.0)
     * @param {string} freqTint - 周波数による色味 ('mix'|'24'|'5')
     */
    function drawGrid(ctx, grid, offX, offY, drawW, drawH, lower, upper, freqTint) {
        if (!grid || grid.length === 0 || grid[0].length === 0) return;

        const nRows = grid.length;
        const nCols = grid[0].length;
        const iw = Math.floor(drawW);
        const ih = Math.floor(drawH);
        if (iw <= 0 || ih <= 0) return;

        const imageData = ctx.createImageData(iw, ih);
        const data = imageData.data;

        // 周波数ごとの色味調整
        const tintR = freqTint === '24' ? 1.3 : freqTint === '5' ? 0.7 : 1.0;
        const tintB = freqTint === '24' ? 0.7 : freqTint === '5' ? 1.3 : 1.0;

        // Canvas px → grid cell のマッピング比率
        const colScale = nCols / iw;
        const rowScale = nRows / ih;

        for (let py = 0; py < ih; py++) {
            const row = Math.min(Math.floor(py * rowScale), nRows - 1);
            for (let px = 0; px < iw; px++) {
                const col = Math.min(Math.floor(px * colScale), nCols - 1);
                const val = grid[row][col];

                const idx = (py * iw + px) * 4;

                // 閾値範囲外は透明
                if (val < lower || val > upper) {
                    data[idx]     = 0;
                    data[idx + 1] = 0;
                    data[idx + 2] = 0;
                    data[idx + 3] = 0;
                    continue;
                }

                // 閾値範囲内での正規化 (0.0〜1.0)
                const range = upper - lower;
                const norm = range > 0.001 ? (val - lower) / range : 0;

                // カラーマップ: 低(青紫) → 中(マゼンタ) → 高(赤橙)
                let r, g, b;
                if (norm < 0.5) {
                    const t = norm * 2;
                    r = Math.floor(30 + 90 * t);
                    g = Math.floor(10 + 30 * t);
                    b = Math.floor(120 + 80 * t);
                } else {
                    const t = (norm - 0.5) * 2;
                    r = Math.floor(120 + 135 * t);
                    g = Math.floor(40 - 20 * t);
                    b = Math.floor(200 - 160 * t);
                }

                // 周波数色味を適用
                r = Math.min(255, Math.floor(r * tintR));
                b = Math.min(255, Math.floor(b * tintB));

                // 透明度: 値が高いほど不透明
                const alpha = Math.floor(40 + norm * 160);

                data[idx]     = r;
                data[idx + 1] = g;
                data[idx + 2] = b;
                data[idx + 3] = alpha;
            }
        }

        ctx.putImageData(imageData, Math.floor(offX), Math.floor(offY));
    }

    /**
     * 旧方式フォールバック: gridデータがない場合にpipes/foreignから描画
     * (3D化前のプレビュー用に残す)
     */
    function drawLegacy(ctx, vd, pipes, foreign, offX, offY, scale, currentFreq) {
        const iw = Math.floor(vd.w * scale);
        const ih = Math.floor(vd.h * scale);
        if (iw <= 0 || ih <= 0) return;

        const id = ctx.createImageData(iw, ih);
        const tintR = currentFreq === '24' ? 1.3 : currentFreq === '5' ? 0.7 : 1;
        const tintB = currentFreq === '24' ? 0.7 : currentFreq === '5' ? 1.3 : 1;

        for (let py = 0; py < ih; py++) {
            for (let px = 0; px < iw; px++) {
                let val = 0;
                const mx = px / scale, my = py / scale;
                const ds = [mx, vd.w - mx, my, vd.h - my];
                for (const d of ds) { if (d < 0.4) val += (0.4 - d) / 0.4 * 0.5; }
                for (const p of pipes) {
                    const dist = distSeg(mx, my, p.x1, p.y1, p.x2, p.y2);
                    const str = { metal: 1, stud: 0.7, pvc: 0.4, wire: 0.3 }[p.type] || 0.3;
                    if (dist < 0.5) val += (0.5 - dist) / 0.5 * str;
                }
                for (const f of foreign) {
                    const dist = Math.hypot(mx - f.x, my - f.y);
                    if (dist < 0.6) val += (0.6 - dist) / 0.6 * 0.8;
                }
                val = Math.max(0, Math.min(1, val));
                const idx = (py * iw + px) * 4;
                id.data[idx] = Math.floor(val * 120 * tintR);
                id.data[idx + 1] = Math.floor(val * 50);
                id.data[idx + 2] = Math.floor(val * 200 * tintB);
                id.data[idx + 3] = Math.floor(val * 80);
            }
        }
        ctx.putImageData(id, Math.floor(offX), Math.floor(offY));
    }

    function distSeg(px, py, x1, y1, x2, y2) {
        const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy;
        if (l2 === 0) return Math.hypot(px - x1, py - y1);
        let t = ((px - x1) * dx + (py - y1) * dy) / l2;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
    }

    return { drawGrid, drawLegacy, distSeg };
})();
