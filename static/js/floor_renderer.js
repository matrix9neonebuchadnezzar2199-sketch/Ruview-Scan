/**
 * RuView Scan - 6面描画エンジン (配管ライン + 異物グロー)
 */
const FloorRenderer = (function() {

    function pipeColor(t) { return { metal:'#ef5350', wire:'#ffa726', pvc:'#66bb6a', stud:'#ce93d8' }[t] || '#888'; }
    function pipeDash(t) { return { wire:[5,4], stud:[2,3] }[t] || []; }
    function pipeWidth(t) { return { metal:4, stud:6, pvc:3 }[t] || 2.5; }

    function drawInfrastructure(ctx, pipes, tx, ty, lower, upper) {
        for (const p of pipes) {
            if (typeof p.depth === 'number' && typeof lower === 'number' && typeof upper === 'number') {
                if (p.depth < lower || p.depth > upper) continue;
            }
            ctx.beginPath(); ctx.moveTo(tx(p.x1), ty(p.y1)); ctx.lineTo(tx(p.x2), ty(p.y2));
            ctx.strokeStyle = pipeColor(p.type); ctx.lineWidth = pipeWidth(p.type);
            ctx.setLineDash(pipeDash(p.type)); ctx.shadowColor = pipeColor(p.type); ctx.shadowBlur = 8; ctx.stroke();
            ctx.shadowBlur = 0; ctx.setLineDash([]);
            const mx = (tx(p.x1) + tx(p.x2)) / 2, my = (ty(p.y1) + ty(p.y2)) / 2;
            ctx.font = '9px Meiryo'; ctx.fillStyle = '#aaa'; ctx.textAlign = 'left';
            ctx.fillText(`${p.label} (${(p.dispConf * 100).toFixed(0)}%)`, mx + 6, my - 5);
        }
    }

    function drawForeignObjects(ctx, foreign, tx, ty, scale, lower, upper) {
        for (const f of foreign) {
            if (typeof f.depth === 'number' && typeof lower === 'number' && typeof upper === 'number') {
                if (f.depth < lower || f.depth > upper) continue;
            }
            const cx = tx(f.x), cy = ty(f.y), pr = f.r * scale;
            const glowR = pr * 2.2;
            // Outer glow
            const g3 = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR * 2.5);
            g3.addColorStop(0, 'rgba(255,23,68,0.12)'); g3.addColorStop(0.5, 'rgba(255,23,68,0.05)'); g3.addColorStop(1, 'rgba(255,23,68,0)');
            ctx.beginPath(); ctx.arc(cx, cy, glowR * 2.5, 0, Math.PI * 2); ctx.fillStyle = g3; ctx.fill();
            // Mid glow
            const g2 = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR * 1.5);
            g2.addColorStop(0, 'rgba(255,23,68,0.25)'); g2.addColorStop(0.6, 'rgba(255,23,68,0.08)'); g2.addColorStop(1, 'rgba(255,23,68,0)');
            ctx.beginPath(); ctx.arc(cx, cy, glowR * 1.5, 0, Math.PI * 2); ctx.fillStyle = g2; ctx.fill();
            // Core
            const g1 = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
            g1.addColorStop(0, 'rgba(255,23,68,0.5)'); g1.addColorStop(0.4, 'rgba(255,23,68,0.3)'); g1.addColorStop(1, 'rgba(255,23,68,0)');
            ctx.beginPath(); ctx.arc(cx, cy, glowR, 0, Math.PI * 2); ctx.fillStyle = g1; ctx.fill();
            // Center dot
            ctx.beginPath(); ctx.arc(cx, cy, 3, 0, Math.PI * 2); ctx.fillStyle = '#ff1744'; ctx.shadowColor = '#ff1744'; ctx.shadowBlur = 12; ctx.fill(); ctx.shadowBlur = 0;
            // Crosshair
            ctx.strokeStyle = 'rgba(255,23,68,0.5)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
            ctx.beginPath(); ctx.moveTo(cx - glowR * 1.5, cy); ctx.lineTo(cx + glowR * 1.5, cy); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx, cy - glowR * 1.5); ctx.lineTo(cx, cy + glowR * 1.5); ctx.stroke();
            ctx.setLineDash([]);
            // Label
            ctx.font = 'bold 10px Meiryo'; ctx.fillStyle = '#ff1744'; ctx.textAlign = 'left';
            ctx.fillText(`⚠ ${f.label}`, cx + glowR * 1.5 + 4, cy - 6);
            ctx.font = '8px Meiryo'; ctx.fillStyle = '#ef9a9a';
            ctx.fillText(`信頼度: ${(f.dispConf * 100).toFixed(0)}% | ${f.detail}`, cx + glowR * 1.5 + 4, cy + 6);
        }
    }

    function drawMeasurementPoints(ctx, ROOM, tx, ty) {
        const pts = [
            { x: ROOM.w / 2, y: ROOM.d / 2, label: 'Wi-Fi TX', isR: true },
            { x: ROOM.w / 2, y: 0.4, label: 'pos.1' },
            { x: ROOM.w - 0.4, y: ROOM.d / 2, label: 'pos.2' },
            { x: ROOM.w / 2, y: ROOM.d - 0.4, label: 'pos.3' },
            { x: 0.4, y: ROOM.d / 2, label: 'pos.4' },
            { x: ROOM.w / 2, y: ROOM.d / 2 + 0.01, label: 'pos.5', skip: true },
            // Phase D: 4隅の追加測定点
            { x: ROOM.w - 1.0, y: 1.0, label: 'pos.6', isOpt: true },
            { x: ROOM.w - 1.0, y: ROOM.d - 1.0, label: 'pos.7', isOpt: true },
            { x: 1.0, y: ROOM.d - 1.0, label: 'pos.8', isOpt: true },
            { x: 1.0, y: 1.0, label: 'pos.9', isOpt: true },
        ];
        for (const pt of pts) {
            if (pt.skip) continue;
            const px = tx(pt.x), py = ty(pt.y);
            if (!pt.isR) {
                ctx.beginPath(); ctx.moveTo(tx(ROOM.w / 2), ty(ROOM.d / 2)); ctx.lineTo(px, py);
                ctx.strokeStyle = 'rgba(78,195,247,.15)'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]); ctx.stroke(); ctx.setLineDash([]);
            }
            ctx.beginPath(); ctx.arc(px, py, pt.isR ? 8 : 4, 0, Math.PI * 2);
            ctx.fillStyle = pt.isR ? 'rgba(255,167,38,.3)' : pt.isOpt ? 'rgba(79,195,247,.15)' : 'rgba(102,187,106,.2)'; ctx.fill();
            ctx.beginPath(); ctx.arc(px, py, pt.isR ? 4 : 2.5, 0, Math.PI * 2);
            ctx.fillStyle = pt.isR ? '#ffa726' : pt.isOpt ? '#4fc3f7' : '#66bb6a'; ctx.fill();
            ctx.font = '8px Meiryo'; ctx.fillStyle = '#8a9ab0'; ctx.textAlign = 'center'; ctx.fillText(pt.label, px, py + 14);
        }
    }

    return { drawInfrastructure, drawForeignObjects, drawMeasurementPoints, pipeColor };
})();
