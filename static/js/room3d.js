/**
 * RuView Scan - 3Dミニビュー (isometric)
 */
const Room3D = (function() {

    function draw(canvas, ROOM, currentView, scanned, VIEW_DATA) {
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const cx = w / 2, cy = h / 2 + 10;
        const s = Math.min(w, h) / 14;
        const rw = ROOM.w, rd = ROOM.d, rh = ROOM.h;

        function iso(x, y, z) {
            return { x: cx + (x - z) * s * 0.7, y: cy + (x + z) * s * 0.35 - y * s * 0.8 };
        }

        const c = [iso(0,0,0), iso(rw,0,0), iso(rw,0,rd), iso(0,0,rd),
                    iso(0,rh,0), iso(rw,rh,0), iso(rw,rh,rd), iso(0,rh,rd)];
        const faces = {
            floor:[0,1,2,3], ceiling:[4,5,6,7],
            south:[0,1,5,4], north:[3,2,6,7],
            east:[1,2,6,5], west:[0,3,7,4]
        };

        for (const f of ['floor','north','west','south','east','ceiling']) {
            const idx = faces[f];
            ctx.beginPath();
            ctx.moveTo(c[idx[0]].x, c[idx[0]].y);
            for (let i = 1; i < 4; i++) ctx.lineTo(c[idx[i]].x, c[idx[i]].y);
            ctx.closePath();

            const hasFr = scanned && VIEW_DATA[f].foreign.length > 0;
            if (f === currentView) {
                ctx.fillStyle = hasFr ? 'rgba(255,23,68,.2)' : 'rgba(78,195,247,.25)';
                ctx.strokeStyle = hasFr ? '#ff1744' : '#4fc3f7';
                ctx.lineWidth = 2;
            } else {
                ctx.fillStyle = hasFr ? 'rgba(255,23,68,.08)' : 'rgba(30,40,60,.3)';
                ctx.strokeStyle = hasFr ? 'rgba(255,23,68,.4)' : '#2a3a5a';
                ctx.lineWidth = 1;
            }
            ctx.fill(); ctx.stroke();

            if (scanned && hasFr) {
                const fx = (c[idx[0]].x + c[idx[1]].x + c[idx[2]].x + c[idx[3]].x) / 4;
                const fy = (c[idx[0]].y + c[idx[1]].y + c[idx[2]].y + c[idx[3]].y) / 4;
                ctx.beginPath(); ctx.arc(fx, fy, 3, 0, Math.PI * 2);
                ctx.fillStyle = '#ff1744'; ctx.shadowColor = '#ff1744'; ctx.shadowBlur = 6; ctx.fill(); ctx.shadowBlur = 0;
            }
        }

        ctx.font = '10px Meiryo'; ctx.fillStyle = '#4fc3f7'; ctx.textAlign = 'center';
        ctx.fillText('▼ ' + VIEW_DATA[currentView].label, w / 2, h - 4);
    }

    return { draw };
})();
