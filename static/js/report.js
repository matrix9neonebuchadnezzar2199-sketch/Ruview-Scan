/**
 * RuView Scan - PDF/CSV レポート出力 (Phase E → 1-B: レポート内容充実)
 * jsPDF 3.x + html2canvas
 */
const ReportExport = (function () {

    /**
     * 現在のスキャン条件を取得
     */
    function _getScanConditions() {
        return {
            freq: (typeof currentFreq !== 'undefined') ? currentFreq : 'mix',
            diffCut: (typeof diffCutEnabled !== 'undefined') ? diffCutEnabled : false,
            contrastEnhance: (typeof contrastEnhance !== 'undefined') ? contrastEnhance : false,
            colorMap: (typeof currentColorMap !== 'undefined') ? currentColorMap : 'thermal',
            date: new Date()
        };
    }

    /**
     * 日時フォーマット
     */
    function _formatDate(d) {
        return d.getFullYear() + '/' +
            String(d.getMonth() + 1).padStart(2, '0') + '/' +
            String(d.getDate()).padStart(2, '0') + ' ' +
            String(d.getHours()).padStart(2, '0') + ':' +
            String(d.getMinutes()).padStart(2, '0');
    }

    /**
     * ファイル名用日時
     */
    function _fileDate(d) {
        return d.getFullYear() +
            String(d.getMonth() + 1).padStart(2, '0') +
            String(d.getDate()).padStart(2, '0') + '_' +
            String(d.getHours()).padStart(2, '0') +
            String(d.getMinutes()).padStart(2, '0');
    }

    /**
     * 周波数ラベル
     */
    function _freqLabel(freq) {
        var map = { mix: '2.4+5+160MHz統合', '24': '2.4GHz', '5': '5GHz(80MHz)', '160': '5GHz(160MHz)' };
        return map[freq] || freq;
    }

    /**
     * ページ背景（ダーク）
     */
    function _darkPage(doc, pageW, pageH) {
        doc.setFillColor(6, 12, 24);
        doc.rect(0, 0, pageW, pageH, 'F');
    }

    /**
     * フッター（ページ番号）
     */
    function _addFooter(doc, pageW, pageH, pageNum, totalPages) {
        doc.setFontSize(8);
        doc.setTextColor(100, 100, 100);
        doc.text('RuView Scan Report — Page ' + pageNum + ' / ' + totalPages, pageW / 2, pageH - 8, { align: 'center' });
    }

    /**
     * 全ページにフッターを後付け
     */
    function _addAllFooters(doc, pageW, pageH) {
        var total = doc.getNumberOfPages();
        for (var i = 1; i <= total; i++) {
            doc.setPage(i);
            _addFooter(doc, pageW, pageH, i, total);
        }
    }

    /**
     * 指定面のヒートマップをオフスクリーンCanvasで描画しDataURLを返す
     */
    function _renderFaceToImage(grid, faceW, faceH, colorMapId, equalize) {
        if (!grid || grid.length === 0) return null;

        var canvasW = 400;
        var canvasH = Math.floor(canvasW * (faceH / faceW));
        if (canvasH <= 0) canvasH = 300;

        var offCanvas = document.createElement('canvas');
        offCanvas.width = canvasW;
        offCanvas.height = canvasH;
        var offCtx = offCanvas.getContext('2d');

        // 背景
        offCtx.fillStyle = '#0a0e1a';
        offCtx.fillRect(0, 0, canvasW, canvasH);

        // ヒートマップ描画
        HeatmapRenderer.drawGrid(
            offCtx, grid,
            0, 0, canvasW, canvasH,
            0, 1,
            'mix',
            colorMapId || 'thermal',
            1.0,
            equalize || false
        );

        return offCanvas.toDataURL('image/png');
    }

    /** PDF出力 */
    async function exportPDF(ROOM, VIEW_DATA, GRID_DATA, scanned, scanCond) {

        if (!scanned) { alert('スキャン結果がありません'); return; }

        var cond = scanCond || {};
        cond.date = cond.date || new Date();
        cond.freq = cond.freq || 'mix';
        cond.diffCut = cond.diffCut || false;
        cond.contrastEnhance = cond.contrastEnhance || false;
        cond.colorMap = cond.colorMap || 'thermal';

        if (btn) { btn.disabled = true; btn.textContent = 'PDF生成中...'; }

        try {
            var jsPDF = window.jspdf.jsPDF;
            var doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
            var pageW = 210, pageH = 297;
            var margin = 15;
            var y = margin;
            var cond = _getScanConditions();

            // ============================================
            // PAGE 1: 表紙
            // ============================================
            _darkPage(doc, pageW, pageH);

            doc.setTextColor(79, 195, 247);
            doc.setFontSize(28);
            doc.text('RUVIEW SCAN', pageW / 2, 50, { align: 'center' });

            doc.setFontSize(12);
            doc.setTextColor(150, 170, 190);
            doc.text('Wi-Fi CSI Wall Scanner Report', pageW / 2, 62, { align: 'center' });

            doc.setTextColor(200, 200, 200);
            doc.setFontSize(10);
            doc.text('Date: ' + _formatDate(cond.date), pageW / 2, 80, { align: 'center' });

            // 部屋情報
            y = 100;
            doc.setTextColor(79, 195, 247);
            doc.setFontSize(14);
            doc.text('Room Dimensions', margin, y);
            y += 10;
            doc.setTextColor(200, 200, 200);
            doc.setFontSize(10);
            doc.text('Width:  ' + ROOM.w.toFixed(1) + ' m', margin + 5, y); y += 7;
            doc.text('Depth:  ' + ROOM.d.toFixed(1) + ' m', margin + 5, y); y += 7;
            doc.text('Height: ' + ROOM.h.toFixed(1) + ' m', margin + 5, y); y += 7;
            doc.text('Area:   ' + (ROOM.w * ROOM.d).toFixed(1) + ' m2', margin + 5, y); y += 7;
            doc.text('Volume: ' + (ROOM.w * ROOM.d * ROOM.h).toFixed(1) + ' m3', margin + 5, y); y += 14;

            // スキャン条件
            doc.setTextColor(79, 195, 247);
            doc.setFontSize(14);
            doc.text('Scan Conditions', margin, y);
            y += 10;
            doc.setTextColor(200, 200, 200);
            doc.setFontSize(10);
            doc.text('Frequency:          ' + _freqLabel(cond.freq), margin + 5, y); y += 7;
            doc.text('Wall Reflection Cut: ' + (cond.diffCut ? 'ON' : 'OFF'), margin + 5, y); y += 7;
            doc.text('Contrast Enhance:    ' + (cond.contrastEnhance ? 'ON' : 'OFF'), margin + 5, y); y += 7;
            doc.text('Color Map:           ' + cond.colorMap, margin + 5, y); y += 14;

            // 検出サマリー
            var totalPipes = 0, totalForeign = 0;
            var foreignList = [];
            var pipeList = [];
            var faceLabels = { floor: 'Floor', ceiling: 'Ceiling', north: 'North', south: 'South', east: 'East', west: 'West' };
            var faceLabelsJa = { floor: '床面', ceiling: '天井', north: '北壁', south: '南壁', east: '東壁', west: '西壁' };

            for (var f in VIEW_DATA) {
                totalPipes += VIEW_DATA[f].pipes.length;
                totalForeign += VIEW_DATA[f].foreign.length;
                for (var i = 0; i < VIEW_DATA[f].pipes.length; i++) {
                    var p = VIEW_DATA[f].pipes[i];
                    pipeList.push({ face: f, type: p.type, label: p.label, conf: p.dispConf, x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2 });
                }
                for (var j = 0; j < VIEW_DATA[f].foreign.length; j++) {
                    var fo = VIEW_DATA[f].foreign[j];
                    foreignList.push({
                        face: f, label: fo.label, conf: fo.dispConf,
                        x: fo.x, y: fo.y, r: fo.r, detail: fo.detail,
                        threat: fo.threat_level || 'medium',
                        method: fo.detection_method || 'unknown'
                    });
                }
            }

            doc.setTextColor(79, 195, 247);
            doc.setFontSize(14);
            doc.text('Detection Summary', margin, y);
            y += 10;
            doc.setTextColor(200, 200, 200);
            doc.setFontSize(10);
            doc.text('Structures (Pipes/Wiring): ' + totalPipes, margin + 5, y); y += 7;
            doc.text('Foreign Objects:           ' + totalForeign, margin + 5, y); y += 7;

            // 面ごとの検出数内訳
            y += 5;
            doc.setFontSize(9);
            doc.setTextColor(150, 150, 150);
            for (var ff in VIEW_DATA) {
                var pc = VIEW_DATA[ff].pipes.length;
                var fc = VIEW_DATA[ff].foreign.length;
                if (pc > 0 || fc > 0) {
                    doc.text('  ' + (faceLabelsJa[ff] || ff) + ': Structures=' + pc + ', Foreign=' + fc, margin + 5, y);
                    y += 6;
                }
            }

            // ============================================
            // PAGE 2: 現在のメインキャンバスキャプチャ
            // ============================================
            var mainCanvas = document.getElementById('mainCanvas');
            if (mainCanvas) {
                doc.addPage();
                _darkPage(doc, pageW, pageH);
                doc.setTextColor(79, 195, 247);
                doc.setFontSize(14);
                doc.text('Current View - 2D Heatmap', margin, margin + 5);

                var imgData = mainCanvas.toDataURL('image/png');
                var imgW = pageW - margin * 2;
                var imgH = imgW * (mainCanvas.height / mainCanvas.width);
                if (imgH > pageH - 60) { imgH = pageH - 60; imgW = imgH * (mainCanvas.width / mainCanvas.height); }
                doc.addImage(imgData, 'PNG', margin, margin + 14, imgW, imgH);
            }

            // ============================================
            // PAGE 3: 3Dビューキャプチャ
            // ============================================
            var threeContainer = document.getElementById('three3dContainer');
            var threeCanvas = threeContainer ? threeContainer.querySelector('canvas') : null;
            if (threeCanvas && threeCanvas.width > 0) {
                doc.addPage();
                _darkPage(doc, pageW, pageH);
                doc.setTextColor(79, 195, 247);
                doc.setFontSize(14);
                doc.text('3D Room View', margin, margin + 5);

                var img3D = threeCanvas.toDataURL('image/png');
                var img3W = pageW - margin * 2;
                var img3H = img3W * (threeCanvas.height / threeCanvas.width);
                if (img3H > pageH - 60) { img3H = pageH - 60; img3W = img3H * (threeCanvas.width / threeCanvas.height); }
                doc.addImage(img3D, 'PNG', margin, margin + 14, img3W, img3H);
            }

            // ============================================
            // PAGE 4-9: 全6面ヒートマップ（オフスクリーン描画）
            // ============================================
            var faces = ['floor', 'ceiling', 'north', 'south', 'east', 'west'];
            for (var fi = 0; fi < faces.length; fi++) {
                var face = faces[fi];
                var grid = GRID_DATA[face];
                if (!grid) continue;

                var vd = VIEW_DATA[face];
                if (!vd) continue;

                var faceImg = _renderFaceToImage(grid, vd.w, vd.h, cond.colorMap, cond.contrastEnhance);
                if (!faceImg) continue;

                doc.addPage();
                _darkPage(doc, pageW, pageH);

                // 面タイトル
                doc.setTextColor(79, 195, 247);
                doc.setFontSize(14);
                doc.text('Heatmap: ' + (faceLabelsJa[face] || face) + ' (' + (faceLabels[face] || face) + ')', margin, margin + 5);

                // 面サイズ情報
                doc.setFontSize(9);
                doc.setTextColor(150, 150, 150);
                doc.text('Size: ' + vd.w.toFixed(1) + 'm x ' + vd.h.toFixed(1) + 'm', margin, margin + 13);

                // ヒートマップ画像
                var hmW = pageW - margin * 2;
                var hmH = hmW * (vd.h / vd.w);
                if (hmH > pageH - 80) { hmH = pageH - 80; hmW = hmH * (vd.w / vd.h); }
                var hmX = (pageW - hmW) / 2;
                doc.addImage(faceImg, 'PNG', hmX, margin + 20, hmW, hmH);

                // 面ごとの検出物リスト
                var faceY = margin + 20 + hmH + 10;
                var facePipes = VIEW_DATA[face].pipes;
                var faceForeign = VIEW_DATA[face].foreign;

                if (facePipes.length > 0 && faceY < pageH - 40) {
                    doc.setTextColor(79, 195, 247);
                    doc.setFontSize(10);
                    doc.text('Structures (' + facePipes.length + ')', margin, faceY);
                    faceY += 6;
                    doc.setTextColor(180, 180, 180);
                    doc.setFontSize(8);
                    for (var pi = 0; pi < facePipes.length; pi++) {
                        if (faceY > pageH - 20) break;
                        var pp = facePipes[pi];
                        doc.text(pp.label + ' (' + pp.type + ') — Conf: ' + (pp.conf * 100).toFixed(0) + '% — (' + pp.x1.toFixed(1) + ',' + pp.y1.toFixed(1) + ')->(' + pp.x2.toFixed(1) + ',' + pp.y2.toFixed(1) + ')', margin + 3, faceY);
                        faceY += 5;
                    }
                    faceY += 3;
                }

                if (faceForeign.length > 0 && faceY < pageH - 30) {
                    doc.setTextColor(255, 23, 68);
                    doc.setFontSize(10);
                    doc.text('Foreign Objects (' + faceForeign.length + ')', margin, faceY);
                    faceY += 6;
                    doc.setTextColor(239, 154, 154);
                    doc.setFontSize(8);
                    for (var fj = 0; fj < faceForeign.length; fj++) {
                        if (faceY > pageH - 20) break;
                        var ffo = faceForeign[fj];
                        doc.text(ffo.label + ' — Conf: ' + ((ffo.dispConf || 0) * 100).toFixed(0) + '% — (' + ffo.x.toFixed(2) + ',' + ffo.y.toFixed(2) + ')m', margin + 3, faceY);
                        faceY += 5;
                    }
                }
            }

            // ============================================
            // 配管一覧ページ
            // ============================================
            if (pipeList.length > 0) {
                doc.addPage();
                _darkPage(doc, pageW, pageH);
                doc.setTextColor(79, 195, 247);
                doc.setFontSize(14);
                y = margin + 5;
                doc.text('Detected Structures — Full List (' + pipeList.length + ')', margin, y); y += 12;

                // テーブルヘッダー
                doc.setFontSize(8);
                doc.setTextColor(100, 120, 140);
                doc.text('#', margin, y);
                doc.text('Face', margin + 8, y);
                doc.text('Type', margin + 30, y);
                doc.text('Label', margin + 55, y);
                doc.text('Conf', margin + 90, y);
                doc.text('From (x,y)', margin + 110, y);
                doc.text('To (x,y)', margin + 145, y);
                y += 3;
                doc.setDrawColor(40, 60, 80);
                doc.line(margin, y, pageW - margin, y);
                y += 4;

                doc.setTextColor(200, 200, 200);
                for (var pi2 = 0; pi2 < pipeList.length; pi2++) {
                    if (y > pageH - 20) {
                        doc.addPage();
                        _darkPage(doc, pageW, pageH);
                        y = margin;
                        doc.setTextColor(200, 200, 200);
                        doc.setFontSize(8);
                    }
                    var pp2 = pipeList[pi2];
                    doc.text(String(pi2 + 1), margin, y);
                    doc.text(faceLabelsJa[pp2.face] || pp2.face, margin + 8, y);
                    doc.text(pp2.type, margin + 30, y);
                    doc.text(pp2.label, margin + 55, y);
                    doc.text((pp2.conf * 100).toFixed(0) + '%', margin + 90, y);
                    doc.text('(' + pp2.x1.toFixed(1) + ', ' + pp2.y1.toFixed(1) + ')', margin + 110, y);
                    doc.text('(' + pp2.x2.toFixed(1) + ', ' + pp2.y2.toFixed(1) + ')', margin + 145, y);
                    y += 5;
                }
            }

            // ============================================
            // 異物一覧ページ
            // ============================================
            if (foreignList.length > 0) {
                doc.addPage();
                _darkPage(doc, pageW, pageH);
                doc.setTextColor(255, 23, 68);
                doc.setFontSize(14);
                y = margin + 5;
                doc.text('Foreign Object Report (' + foreignList.length + ')', margin, y); y += 12;

                var threatLabels = { high: 'DANGER', medium: 'WARNING', low: 'CAUTION', none: 'SAFE' };
                var threatColors = { high: [255, 23, 68], medium: [255, 145, 0], low: [255, 214, 0], none: [102, 187, 106] };
                var methodLabels = { rf: 'RF', csi: 'CSI', both: 'RF+CSI', unknown: 'N/A' };

                for (var fi2 = 0; fi2 < foreignList.length; fi2++) {
                    if (y > pageH - 50) {
                        doc.addPage();
                        _darkPage(doc, pageW, pageH);
                        y = margin;
                    }
                    var ff2 = foreignList[fi2];
                    var tc = threatColors[ff2.threat] || [255, 145, 0];

                    // 脅威ラベル
                    doc.setFontSize(10);
                    doc.setTextColor(tc[0], tc[1], tc[2]);
                    doc.text((threatLabels[ff2.threat] || 'WARNING') + ' — ' + ff2.label, margin, y);
                    y += 6;

                    // 詳細
                    doc.setFontSize(8);
                    doc.setTextColor(180, 180, 180);
                    doc.text('Location: ' + (faceLabelsJa[ff2.face] || ff2.face) + ' (' + ff2.x.toFixed(2) + ', ' + ff2.y.toFixed(2) + ')m', margin + 5, y); y += 5;
                    doc.text('Confidence: ' + (ff2.conf * 100).toFixed(0) + '%    Detection: ' + (methodLabels[ff2.method] || 'N/A') + '    Est. Size: ' + ((ff2.r || 0) * 100).toFixed(0) + 'cm', margin + 5, y); y += 5;
                    if (ff2.detail) {
                        doc.setTextColor(140, 140, 140);
                        doc.text('Detail: ' + ff2.detail, margin + 5, y); y += 5;
                    }
                    y += 4;

                    // 区切り線
                    doc.setDrawColor(40, 30, 30);
                    doc.line(margin, y - 2, pageW - margin, y - 2);
                }
            }

            // ============================================
            // 全ページにフッター（ページ番号）を後付け
            // ============================================
            _addAllFooters(doc, pageW, pageH);

            doc.save('RuView_Scan_Report_' + _fileDate(cond.date) + '.pdf');

        } catch (e) {
            console.error('PDF export error:', e);
            alert('PDF生成に失敗しました: ' + e.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'PDF'; }
        }
    }

    /** CSV出力: 検出レポート */
    function exportCSV(ROOM, VIEW_DATA, GRID_DATA, scanned, scanCond) {

        if (!scanned) { alert('スキャン結果がありません'); return; }

        var cond = scanCond || {};
        cond.date = cond.date || new Date();
        cond.freq = cond.freq || 'mix';
        cond.diffCut = cond.diffCut || false;
        cond.contrastEnhance = cond.contrastEnhance || false;
        cond.colorMap = cond.colorMap || 'thermal';

        var lines = [];

        // ヘッダー + スキャン条件
        lines.push('# RuView Scan Report');
        lines.push('# Date: ' + cond.date.toISOString());
        lines.push('# Room: ' + ROOM.w.toFixed(1) + 'm x ' + ROOM.d.toFixed(1) + 'm x ' + ROOM.h.toFixed(1) + 'm');
        lines.push('# Area: ' + (ROOM.w * ROOM.d).toFixed(1) + ' m2');
        lines.push('# Volume: ' + (ROOM.w * ROOM.d * ROOM.h).toFixed(1) + ' m3');
        lines.push('# Frequency: ' + _freqLabel(cond.freq));
        lines.push('# Wall Reflection Cut: ' + (cond.diffCut ? 'ON' : 'OFF'));
        lines.push('# Contrast Enhance: ' + (cond.contrastEnhance ? 'ON' : 'OFF'));
        lines.push('# Color Map: ' + cond.colorMap);
        lines.push('');

        // 配管
        lines.push('## Structures');
        lines.push('face,type,label,confidence,x1,y1,x2,y2');
        for (var f in VIEW_DATA) {
            for (var i = 0; i < VIEW_DATA[f].pipes.length; i++) {
                var p = VIEW_DATA[f].pipes[i];
                lines.push(f + ',' + p.type + ',' + p.label + ',' + p.dispConf.toFixed(3) + ',' + p.x1.toFixed(3) + ',' + p.y1.toFixed(3) + ',' + p.x2.toFixed(3) + ',' + p.y2.toFixed(3));
            }
        }
        lines.push('');

        // 異物
        lines.push('## Foreign Objects');
        lines.push('face,label,threat,detection_method,confidence,x,y,radius,detail');
        for (var f2 in VIEW_DATA) {
            for (var j = 0; j < VIEW_DATA[f2].foreign.length; j++) {
                var fo = VIEW_DATA[f2].foreign[j];
                var detail = (fo.detail || '').replace(/,/g, ';').replace(/\n/g, ' ');
                lines.push(f2 + ',' + fo.label + ',' + (fo.threat_level || 'medium') + ',' + (fo.detection_method || 'unknown') + ',' + (fo.dispConf || 0).toFixed(3) + ',' + fo.x.toFixed(3) + ',' + fo.y.toFixed(3) + ',' + (fo.r || 0).toFixed(3) + ',' + detail);
            }
        }
        lines.push('');

        // グリッドデータ（閾値0.01以上のみ）
        lines.push('## Grid Data (face,row,col,value)');
        lines.push('face,row,col,value');
        var faces = ['floor', 'ceiling', 'north', 'south', 'east', 'west'];
        for (var fi = 0; fi < faces.length; fi++) {
            var face = faces[fi];
            var grid = GRID_DATA[face];
            if (!grid) continue;
            for (var r = 0; r < grid.length; r++) {
                for (var c = 0; c < grid[r].length; c++) {
                    if (grid[r][c] > 0.01) {
                        lines.push(face + ',' + r + ',' + c + ',' + grid[r][c].toFixed(4));
                    }
                }
            }
        }

        var csv = lines.join('\n');
        var bom = '\uFEFF';
        var blob = new Blob([bom + csv], { type: 'text/csv;charset=utf-8;' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'RuView_Scan_Data_' + _fileDate(cond.date) + '.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    return {
        exportPDF: exportPDF,
        exportCSV: exportCSV
    };
})();
