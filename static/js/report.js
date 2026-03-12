/**
 * RuView Scan - PDF/CSV レポート出力 (Phase E)
 * jsPDF 3.x + html2canvas
 */
const ReportExport = (function() {

    /** PDF出力 */
    async function exportPDF(ROOM, VIEW_DATA, GRID_DATA, scanned) {
        if (!scanned) { alert('スキャン結果がありません'); return; }

        var btn = document.getElementById('btnExportPDF');
        if (btn) { btn.disabled = true; btn.textContent = 'PDF生成中...'; }

        try {
            var jsPDF = window.jspdf.jsPDF;
            var doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
            var pageW = 210, pageH = 297;
            var margin = 15;
            var y = margin;

            // === 表紙 ===
            doc.setFillColor(6, 12, 24);
            doc.rect(0, 0, pageW, pageH, 'F');

            doc.setTextColor(79, 195, 247);
            doc.setFontSize(22);
            doc.text('RUVIEW SCAN', pageW / 2, 40, { align: 'center' });
            doc.setFontSize(12);
            doc.text('Wi-Fi CSI Wall Scanner Report', pageW / 2, 50, { align: 'center' });

            doc.setTextColor(200, 200, 200);
            doc.setFontSize(10);
            var now = new Date();
            var dateStr = now.getFullYear() + '/' + String(now.getMonth()+1).padStart(2,'0') + '/' + String(now.getDate()).padStart(2,'0') + ' ' + String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0');
            doc.text('Date: ' + dateStr, pageW / 2, 65, { align: 'center' });

            // 部屋情報
            y = 85;
            doc.setTextColor(79, 195, 247);
            doc.setFontSize(14);
            doc.text('Room Dimensions', margin, y);
            y += 8;
            doc.setTextColor(200, 200, 200);
            doc.setFontSize(10);
            doc.text('Width: ' + ROOM.w.toFixed(1) + ' m', margin, y); y += 6;
            doc.text('Depth: ' + ROOM.d.toFixed(1) + ' m', margin, y); y += 6;
            doc.text('Height: ' + ROOM.h.toFixed(1) + ' m', margin, y); y += 6;
            doc.text('Area: ' + (ROOM.w * ROOM.d).toFixed(1) + ' m2', margin, y); y += 6;
            doc.text('Volume: ' + (ROOM.w * ROOM.d * ROOM.h).toFixed(1) + ' m3', margin, y); y += 12;

            // 検出サマリー
            var totalPipes = 0, totalForeign = 0;
            var foreignList = [];
            var pipeList = [];
            for (var f in VIEW_DATA) {
                totalPipes += VIEW_DATA[f].pipes.length;
                totalForeign += VIEW_DATA[f].foreign.length;
                for (var i = 0; i < VIEW_DATA[f].pipes.length; i++) {
                    var p = VIEW_DATA[f].pipes[i];
                    pipeList.push({ face: f, type: p.type, label: p.label, conf: p.dispConf, x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2 });
                }
                for (var j = 0; j < VIEW_DATA[f].foreign.length; j++) {
                    var fo = VIEW_DATA[f].foreign[j];
                    foreignList.push({ face: f, label: fo.label, conf: fo.dispConf, x: fo.x, y: fo.y, r: fo.r, detail: fo.detail, threat: fo.threat_level || 'medium' });
                }
            }

            doc.setTextColor(79, 195, 247);
            doc.setFontSize(14);
            doc.text('Detection Summary', margin, y); y += 8;
            doc.setTextColor(200, 200, 200);
            doc.setFontSize(10);
            doc.text('Pipes/Wiring: ' + totalPipes, margin, y); y += 6;
            doc.text('Foreign Objects: ' + totalForeign, margin, y); y += 12;

            // === 2D ヒートマップキャプチャ ===
            var mainCanvas = document.getElementById('mainCanvas');
            if (mainCanvas) {
                doc.addPage();
                doc.setFillColor(6, 12, 24);
                doc.rect(0, 0, pageW, pageH, 'F');
                doc.setTextColor(79, 195, 247);
                doc.setFontSize(14);
                doc.text('2D Heatmap - Current View', margin, margin + 5);

                var imgData = mainCanvas.toDataURL('image/png');
                var imgW = pageW - margin * 2;
                var imgH = imgW * (mainCanvas.height / mainCanvas.width);
                if (imgH > pageH - 50) { imgH = pageH - 50; imgW = imgH * (mainCanvas.width / mainCanvas.height); }
                doc.addImage(imgData, 'PNG', margin, margin + 12, imgW, imgH);
            }

            // === 3D ビューキャプチャ ===
            var threeContainer = document.getElementById('three3dContainer');
            var threeCanvas = threeContainer ? threeContainer.querySelector('canvas') : null;
            if (threeCanvas && threeCanvas.width > 0) {
                doc.addPage();
                doc.setFillColor(6, 12, 24);
                doc.rect(0, 0, pageW, pageH, 'F');
                doc.setTextColor(79, 195, 247);
                doc.setFontSize(14);
                doc.text('3D Room View', margin, margin + 5);

                var img3D = threeCanvas.toDataURL('image/png');
                var img3W = pageW - margin * 2;
                var img3H = img3W * (threeCanvas.height / threeCanvas.width);
                if (img3H > pageH - 50) { img3H = pageH - 50; img3W = img3H * (threeCanvas.width / threeCanvas.height); }
                doc.addImage(img3D, 'PNG', margin, margin + 12, img3W, img3H);
            }

            // === 配管リスト ===
            if (pipeList.length > 0) {
                doc.addPage();
                doc.setFillColor(6, 12, 24);
                doc.rect(0, 0, pageW, pageH, 'F');
                doc.setTextColor(79, 195, 247);
                doc.setFontSize(14);
                y = margin + 5;
                doc.text('Detected Structures (' + pipeList.length + ')', margin, y); y += 10;

                doc.setFontSize(8);
                doc.setTextColor(150, 150, 150);
                doc.text('Face', margin, y);
                doc.text('Type', margin + 25, y);
                doc.text('Label', margin + 50, y);
                doc.text('Confidence', margin + 85, y);
                doc.text('Position', margin + 115, y);
                y += 5;

                doc.setTextColor(200, 200, 200);
                for (var pi = 0; pi < pipeList.length; pi++) {
                    var pp = pipeList[pi];
                    if (y > pageH - 20) { doc.addPage(); doc.setFillColor(6,12,24); doc.rect(0,0,pageW,pageH,'F'); y = margin; doc.setTextColor(200,200,200); doc.setFontSize(8); }
                    doc.text(pp.face, margin, y);
                    doc.text(pp.type, margin + 25, y);
                    doc.text(pp.label, margin + 50, y);
                    doc.text((pp.conf * 100).toFixed(0) + '%', margin + 85, y);
                    doc.text('(' + pp.x1.toFixed(1) + ',' + pp.y1.toFixed(1) + ')-(' + pp.x2.toFixed(1) + ',' + pp.y2.toFixed(1) + ')', margin + 115, y);
                    y += 5;
                }
            }

            // === 異物リスト ===
            if (foreignList.length > 0) {
                doc.addPage();
                doc.setFillColor(6, 12, 24);
                doc.rect(0, 0, pageW, pageH, 'F');
                doc.setTextColor(255, 23, 68);
                doc.setFontSize(14);
                y = margin + 5;
                doc.text('Foreign Object Report (' + foreignList.length + ')', margin, y); y += 10;

                doc.setFontSize(8);
                doc.setTextColor(150, 150, 150);
                doc.text('Face', margin, y);
                doc.text('Threat', margin + 25, y);
                doc.text('Label', margin + 50, y);
                doc.text('Confidence', margin + 90, y);
                doc.text('Position', margin + 120, y);
                y += 5;

                doc.setTextColor(200, 200, 200);
                for (var fi = 0; fi < foreignList.length; fi++) {
                    var ff = foreignList[fi];
                    if (y > pageH - 20) { doc.addPage(); doc.setFillColor(6,12,24); doc.rect(0,0,pageW,pageH,'F'); y = margin; doc.setTextColor(200,200,200); doc.setFontSize(8); }
                    doc.text(ff.face, margin, y);
                    doc.text(ff.threat, margin + 25, y);
                    doc.text(ff.label, margin + 50, y);
                    doc.text((ff.conf * 100).toFixed(0) + '%', margin + 90, y);
                    doc.text('(' + ff.x.toFixed(2) + ', ' + ff.y.toFixed(2) + ')', margin + 120, y);
                    y += 5;
                    if (ff.detail) {
                        doc.setTextColor(150, 150, 150);
                        doc.text('  ' + ff.detail, margin + 10, y);
                        doc.setTextColor(200, 200, 200);
                        y += 5;
                    }
                }
            }

            doc.save('RuView_Scan_Report_' + now.getFullYear() + String(now.getMonth()+1).padStart(2,'0') + String(now.getDate()).padStart(2,'0') + '.pdf');

        } catch(e) {
            console.error('PDF export error:', e);
            alert('PDF generation failed: ' + e.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'PDF'; }
        }
    }

    /** CSV出力: 検出レポート */
    function exportCSV(ROOM, VIEW_DATA, GRID_DATA, scanned) {
        if (!scanned) { alert('No scan results available'); return; }

        var lines = [];

        // ヘッダー
        lines.push('# RuView Scan Report');
        lines.push('# Date: ' + new Date().toISOString());
        lines.push('# Room: ' + ROOM.w + 'm x ' + ROOM.d + 'm x ' + ROOM.h + 'm');
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
        lines.push('face,label,threat,confidence,x,y,radius,detail');
        for (var f in VIEW_DATA) {
            for (var j = 0; j < VIEW_DATA[f].foreign.length; j++) {
                var fo = VIEW_DATA[f].foreign[j];
                var detail = (fo.detail || '').replace(/,/g, ';');
                lines.push(f + ',' + fo.label + ',' + (fo.threat_level || 'medium') + ',' + (fo.dispConf || 0).toFixed(3) + ',' + fo.x.toFixed(3) + ',' + fo.y.toFixed(3) + ',' + (fo.r || 0).toFixed(3) + ',' + detail);
            }
        }
        lines.push('');

        // グリッドデータ
        lines.push('## Grid Data (face,row,col,value)');
        lines.push('face,row,col,value');
        var faces = ['floor','ceiling','north','south','east','west'];
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
        var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        var now = new Date();
        a.download = 'RuView_Scan_Data_' + now.getFullYear() + String(now.getMonth()+1).padStart(2,'0') + String(now.getDate()).padStart(2,'0') + '.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    return {
        exportPDF: exportPDF,
        exportCSV: exportCSV
    };
})();