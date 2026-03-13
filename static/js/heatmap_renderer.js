/**
 * RuView Scan - ヒートマップ描画エンジン (Phase B+ → 1-A: コントラスト自動調整追加)
 */
const HeatmapRenderer = (function () {

    /** カラーマップ定義 */
    const COLOR_MAPS = {
        thermal: {
            label: 'サーマル',
            fn: function (t) {
                if (t < 0.5) {
                    var s = t * 2;
                    return [30 + 90 * s, 10 + 30 * s, 120 + 80 * s];
                } else {
                    var s = (t - 0.5) * 2;
                    return [120 + 135 * s, 40 - 20 * s, 200 - 160 * s];
                }
            }
        },
        heat: {
            label: 'ヒート',
            fn: function (t) {
                if (t < 0.33) {
                    var s = t / 0.33;
                    return [Math.floor(s * 200), 0, 0];
                } else if (t < 0.66) {
                    var s = (t - 0.33) / 0.33;
                    return [200 + Math.floor(55 * s), Math.floor(200 * s), 0];
                } else {
                    var s = (t - 0.66) / 0.34;
                    return [255, 200 + Math.floor(55 * s), Math.floor(255 * s)];
                }
            }
        },
        cool: {
            label: 'クール',
            fn: function (t) {
                if (t < 0.5) {
                    var s = t * 2;
                    return [0, Math.floor(80 * s), Math.floor(180 + 75 * s)];
                } else {
                    var s = (t - 0.5) * 2;
                    return [Math.floor(100 * s), 80 + Math.floor(175 * s), 255];
                }
            }
        },
        grayscale: {
            label: 'グレー',
            fn: function (t) {
                var v = Math.floor(t * 255);
                return [v, v, v];
            }
        },
        rainbow: {
            label: 'レインボー',
            fn: function (t) {
                if (t < 0.25) {
                    var s = t / 0.25;
                    return [0, Math.floor(s * 255), 255];
                } else if (t < 0.5) {
                    var s = (t - 0.25) / 0.25;
                    return [0, 255, 255 - Math.floor(s * 255)];
                } else if (t < 0.75) {
                    var s = (t - 0.5) / 0.25;
                    return [Math.floor(s * 255), 255, 0];
                } else {
                    var s = (t - 0.75) / 0.25;
                    return [255, 255 - Math.floor(s * 255), 0];
                }
            }
        }
    };

    /**
     * ヒストグラム平坦化用ルックアップテーブルを構築
     * gridの値分布を均一化し、微小な差異を強調する。
     * @param {number[][]} grid - 2D配列 (0.0〜1.0)
     * @param {number} bins - 量子化ビン数 (default: 256)
     * @returns {Float32Array} LUT[0..bins-1] → 平坦化後の値 (0.0〜1.0)
     */
    function buildEqualizeLUT(grid, bins) {
        bins = bins || 256;
        var hist = new Float64Array(bins);
        var totalPixels = 0;

        for (var r = 0; r < grid.length; r++) {
            for (var c = 0; c < grid[r].length; c++) {
                var bin = Math.min(Math.floor(grid[r][c] * bins), bins - 1);
                if (bin < 0) bin = 0;
                hist[bin]++;
                totalPixels++;
            }
        }

        if (totalPixels === 0) return null;

        // CDF (累積分布関数) を構築
        var cdf = new Float64Array(bins);
        cdf[0] = hist[0];
        for (var i = 1; i < bins; i++) {
            cdf[i] = cdf[i - 1] + hist[i];
        }

        // cdf_min: 最初の非ゼロCDF値
        var cdfMin = 0;
        for (var j = 0; j < bins; j++) {
            if (cdf[j] > 0) { cdfMin = cdf[j]; break; }
        }

        // LUT: 平坦化マッピング
        var lut = new Float32Array(bins);
        var denom = totalPixels - cdfMin;
        if (denom <= 0) denom = 1;

        for (var k = 0; k < bins; k++) {
            lut[k] = (cdf[k] - cdfMin) / denom;
            if (lut[k] < 0) lut[k] = 0;
            if (lut[k] > 1) lut[k] = 1;
        }

        return lut;
    }

    /**
     * gridデータ全体をヒストグラム平坦化した新しいgridを返す
     * @param {number[][]} grid - 元の2D配列 (0.0〜1.0)
     * @returns {number[][]} 平坦化済みの2D配列
     */
    function equalizeGrid(grid) {
        if (!grid || grid.length === 0 || grid[0].length === 0) return grid;

        var bins = 256;
        var lut = buildEqualizeLUT(grid, bins);
        if (!lut) return grid;

        var result = [];
        for (var r = 0; r < grid.length; r++) {
            var row = new Array(grid[r].length);
            for (var c = 0; c < grid[r].length; c++) {
                var bin = Math.min(Math.floor(grid[r][c] * bins), bins - 1);
                if (bin < 0) bin = 0;
                row[c] = lut[bin];
            }
            result.push(row);
        }
        return result;
    }

    /**
     * gridデータをCanvasに描画
     * @param {CanvasRenderingContext2D} ctx
     * @param {number[][]} grid - 2D配列 (0.0〜1.0)
     * @param {number} offX - 描画オフセットX (px)
     * @param {number} offY - 描画オフセットY (px)
     * @param {number} drawW - 描画幅 (px)
     * @param {number} drawH - 描画高さ (px)
     * @param {number} lower - 下限閾値 (0.0〜1.0)
     * @param {number} upper - 上限閾値 (0.0〜1.0)
     * @param {string} freqTint - 周波数色味 ('mix'|'24'|'5')
     * @param {string} colorMapId - カラーマップID
     * @param {number} opacity - 全体透明度 (0.0〜1.0)
     * @param {boolean} equalize - ヒストグラム平坦化の有無 (default: false)
     */
    function drawGrid(ctx, grid, offX, offY, drawW, drawH, lower, upper, freqTint, colorMapId, opacity, equalize) {
        if (!grid || grid.length === 0 || grid[0].length === 0) return;

        // 平坦化が有効な場合、描画用gridを差し替え
        var renderGrid = (equalize === true) ? equalizeGrid(grid) : grid;

        var cmap = COLOR_MAPS[colorMapId] || COLOR_MAPS.thermal;
        var opacityVal = (typeof opacity === 'number') ? opacity : 1.0;

        var nRows = renderGrid.length;
        var nCols = renderGrid[0].length;
        var iw = Math.floor(drawW);
        var ih = Math.floor(drawH);
        if (iw <= 0 || ih <= 0) return;

        var imageData = ctx.createImageData(iw, ih);
        var data = imageData.data;

        var tintR = freqTint === '24' ? 1.3 : freqTint === '5' ? 0.7 : 1.0;
        var tintB = freqTint === '24' ? 0.7 : freqTint === '5' ? 1.3 : 1.0;

        var colScale = nCols / iw;
        var rowScale = nRows / ih;

        for (var py = 0; py < ih; py++) {
            var row = Math.min(Math.floor(py * rowScale), nRows - 1);
            for (var px = 0; px < iw; px++) {
                var col = Math.min(Math.floor(px * colScale), nCols - 1);
                var val = renderGrid[row][col];
                var idx = (py * iw + px) * 4;

                if (val < lower || val > upper) {
                    data[idx] = 0; data[idx + 1] = 0; data[idx + 2] = 0; data[idx + 3] = 0;
                    continue;
                }

                var range = upper - lower;
                var norm = range > 0.001 ? (val - lower) / range : 0;

                var rgb = cmap.fn(norm);
                var r = Math.min(255, Math.floor(rgb[0] * tintR));
                var g = rgb[1];
                var b = Math.min(255, Math.floor(rgb[2] * tintB));

                var baseAlpha = 40 + norm * 160;
                var alpha = Math.floor(baseAlpha * opacityVal);

                data[idx] = r; data[idx + 1] = g; data[idx + 2] = b; data[idx + 3] = alpha;
            }
        }
        ctx.putImageData(imageData, Math.floor(offX), Math.floor(offY));
    }

    /**
     * 旧方式フォールバック
     */
    function drawLegacy(ctx, vd, pipes, foreign, offX, offY, scale, currentFreq) {
        var iw = Math.floor(vd.w * scale);
        var ih = Math.floor(vd.h * scale);
        if (iw <= 0 || ih <= 0) return;

        var id = ctx.createImageData(iw, ih);
        var tintR = currentFreq === '24' ? 1.3 : currentFreq === '5' ? 0.7 : 1;
        var tintB = currentFreq === '24' ? 0.7 : currentFreq === '5' ? 1.3 : 1;

        for (var py = 0; py < ih; py++) {
            for (var px = 0; px < iw; px++) {
                var val = 0;
                var mx = px / scale, my = py / scale;
                var ds = [mx, vd.w - mx, my, vd.h - my];
                for (var i = 0; i < ds.length; i++) { if (ds[i] < 0.4) val += (0.4 - ds[i]) / 0.4 * 0.5; }
                for (var j = 0; j < pipes.length; j++) {
                    var p = pipes[j];
                    var dist = distSeg(mx, my, p.x1, p.y1, p.x2, p.y2);
                    var str = { metal: 1, stud: 0.7, pvc: 0.4, wire: 0.3 }[p.type] || 0.3;
                    if (dist < 0.5) val += (0.5 - dist) / 0.5 * str;
                }
                for (var k = 0; k < foreign.length; k++) {
                    var f = foreign[k];
                    var fdist = Math.hypot(mx - f.x, my - f.y);
                    if (fdist < 0.6) val += (0.6 - fdist) / 0.6 * 0.8;
                }
                val = Math.max(0, Math.min(1, val));
                var pidx = (py * iw + px) * 4;
                id.data[pidx] = Math.floor(val * 120 * tintR);
                id.data[pidx + 1] = Math.floor(val * 50);
                id.data[pidx + 2] = Math.floor(val * 200 * tintB);
                id.data[pidx + 3] = Math.floor(val * 80);
            }
        }
        ctx.putImageData(id, Math.floor(offX), Math.floor(offY));
    }

    /**
     * gridデータからヒストグラムを算出
     * @param {number[][]} grid
     * @param {number} bins - ビン数
     * @returns {number[]} 各ビンのカウント
     */
    function calcHistogram(grid, bins) {
        if (!grid || grid.length === 0) return [];
        bins = bins || 50;
        var hist = new Array(bins).fill(0);
        for (var r = 0; r < grid.length; r++) {
            for (var c = 0; c < grid[r].length; c++) {
                var bin = Math.min(Math.floor(grid[r][c] * bins), bins - 1);
                hist[bin]++;
            }
        }
        return hist;
    }

    /**
     * マウス位置からgridの値を取得
     * @param {number[][]} grid
     * @param {number} mouseX - Canvas内マウスX
     * @param {number} mouseY - Canvas内マウスY
     * @param {number} offX - 描画オフセットX
     * @param {number} offY - 描画オフセットY
     * @param {number} drawW - 描画幅
     * @param {number} drawH - 描画高さ
     * @param {number} faceW - 面の幅(m)
     * @param {number} faceH - 面の高さ(m)
     * @returns {object|null} { row, col, value, x_m, y_m }
     */
    function probeGrid(grid, mouseX, mouseY, offX, offY, drawW, drawH, faceW, faceH) {
        if (!grid || grid.length === 0) return null;
        var relX = mouseX - offX;
        var relY = mouseY - offY;
        if (relX < 0 || relX >= drawW || relY < 0 || relY >= drawH) return null;

        var nRows = grid.length;
        var nCols = grid[0].length;
        var col = Math.min(Math.floor(relX / drawW * nCols), nCols - 1);
        var row = Math.min(Math.floor(relY / drawH * nRows), nRows - 1);

        return {
            row: row,
            col: col,
            value: grid[row][col],
            x_m: (col / nCols * faceW).toFixed(2),
            y_m: (row / nRows * faceH).toFixed(2)
        };
    }

    /** カラーマップのIDリストを返す */
    function getColorMapIds() {
        return Object.keys(COLOR_MAPS);
    }

    /** カラーマップのラベルを返す */
    function getColorMapLabel(id) {
        return COLOR_MAPS[id] ? COLOR_MAPS[id].label : id;
    }

    function distSeg(px, py, x1, y1, x2, y2) {
        var dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy;
        if (l2 === 0) return Math.hypot(px - x1, py - y1);
        var t = ((px - x1) * dx + (py - y1) * dy) / l2;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
    }

    return {
        drawGrid: drawGrid,
        drawLegacy: drawLegacy,
        equalizeGrid: equalizeGrid,
        calcHistogram: calcHistogram,
        probeGrid: probeGrid,
        getColorMapIds: getColorMapIds,
        getColorMapLabel: getColorMapLabel,
        distSeg: distSeg
    };
})();
