/**
 * RuView Scan - ヒートマップ描画エンジン
 */
const HeatmapRenderer = (function() {

    function draw(ctx, vd, pipes, foreign, offX, offY, scale, currentFreq) {
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

    return { draw, distSeg };
})();
