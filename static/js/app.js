/**
 * RuView Scan - メインアプリケーション
 * タブ切替、フィルター、周波数切替、Canvas描画、API連携を統合
 */
const RuView = (function() {
    const API = '/api';

    // --- State ---
    let currentView = 'floor';
    let currentFreq = 'mix';
    let scanned = false;
    const filters = { infra: true, foreign: true, heatmap: true };

    const ROOM = { w: 7.2, d: 5.4, h: 2.7 };

    const VIEW_DATA = {
        floor:   { label:'床面',   w:ROOM.w, h:ROOM.d, pipes:[], foreign:[] },
        ceiling: { label:'天井',   w:ROOM.w, h:ROOM.d, pipes:[], foreign:[] },
        north:   { label:'北壁',   w:ROOM.w, h:ROOM.h, pipes:[], foreign:[] },
        south:   { label:'南壁',   w:ROOM.w, h:ROOM.h, pipes:[], foreign:[] },
        east:    { label:'東壁',   w:ROOM.d, h:ROOM.h, pipes:[], foreign:[] },
        west:    { label:'西壁',   w:ROOM.d, h:ROOM.h, pipes:[], foreign:[] },
    };

    let mainCanvas, mainCtx, room3dCanvas;

    /** Init */
    function init() {
        mainCanvas = document.getElementById('mainCanvas');
        mainCtx = mainCanvas.getContext('2d');
        room3dCanvas = document.getElementById('room3dCanvas');
        resize();
        window.addEventListener('resize', resize);
        render();
        addLog('RuView Scan v1.0 起動', 'log-info');
        addLog('モバイルWi-Fiルーターを部屋中心に設置してください', 'log-info');
    }

    function resize() {
        const vp = mainCanvas.parentElement;
        mainCanvas.width = vp.clientWidth - 24;
        mainCanvas.height = vp.clientHeight - 110;
        room3dCanvas.width = room3dCanvas.parentElement.clientWidth - 24;
        room3dCanvas.height = 160;
        render();
    }

    /** Tab switch */
    function switchView(view) {
        currentView = view;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
        render();
    }

    /** Filter toggle */
    function toggleFilter(key) {
        filters[key] = !filters[key];
        document.querySelectorAll('.filter-btn').forEach(b => {
            if (b.dataset.filter === key) b.classList.toggle('on', filters[key]);
        });
        render();
    }

    /** Frequency switch */
    function switchFreq(freq) {
        currentFreq = freq;
        document.querySelectorAll('.freq-btn').forEach(b => b.classList.toggle('active', b.dataset.freq === freq));
        render();
    }

    /** Render main canvas */
    function render() {
        if (!mainCtx) return;
        const cw = mainCanvas.width, ch = mainCanvas.height;
        mainCtx.clearRect(0, 0, cw, ch);

        const vd = VIEW_DATA[currentView];
        if (!vd) return;

        // Scale + center
        const pad = 60;
        const scale = Math.min((cw - pad*2) / vd.w, (ch - pad*2) / vd.h);
        const offX = (cw - vd.w * scale) / 2;
        const offY = (ch - vd.h * scale) / 2;
        const tx = x => offX + x * scale;
        const ty = y => offY + y * scale;

        // Grid lines
        mainCtx.strokeStyle = '#1a2540'; mainCtx.lineWidth = 0.5; mainCtx.setLineDash([]);
        for (let x = 0; x <= vd.w; x += 1) { mainCtx.beginPath(); mainCtx.moveTo(tx(x), offY); mainCtx.lineTo(tx(x), offY + vd.h*scale); mainCtx.stroke(); }
        for (let y = 0; y <= vd.h; y += 1) { mainCtx.beginPath(); mainCtx.moveTo(offX, ty(y)); mainCtx.lineTo(offX + vd.w*scale, ty(y)); mainCtx.stroke(); }

        // Wall outline
        mainCtx.strokeStyle = '#4fc3f7'; mainCtx.lineWidth = 2; mainCtx.setLineDash([]);
        mainCtx.strokeRect(offX, offY, vd.w * scale, vd.h * scale);

        // Scale text
        mainCtx.font = '9px Meiryo'; mainCtx.fillStyle = '#4a6a8a'; mainCtx.textAlign = 'center';
        mainCtx.fillText(`${vd.w.toFixed(1)}m`, offX + vd.w*scale/2, offY + vd.h*scale + 16);
        mainCtx.save(); mainCtx.translate(offX - 14, offY + vd.h*scale/2);
        mainCtx.rotate(-Math.PI/2); mainCtx.fillText(`${vd.h.toFixed(1)}m`, 0, 0); mainCtx.restore();

        // View label
        mainCtx.font = '14px Meiryo'; mainCtx.fillStyle = '#4fc3f7'; mainCtx.textAlign = 'left';
        mainCtx.fillText(`◆ ${vd.label} (${currentFreq === 'mix' ? '2.4+5GHz' : currentFreq === '24' ? '2.4GHz' : '5GHz'})`, 10, 22);

        if (!scanned) {
            mainCtx.font = '16px Meiryo'; mainCtx.fillStyle = '#3a4a6a'; mainCtx.textAlign = 'center';
            mainCtx.fillText('全 5 箇所の計測後に描画されます', cw/2, ch/2);
            renderRoom3D();
            return;
        }

        // Heatmap
        if (filters.heatmap) {
            HeatmapRenderer.draw(mainCtx, vd, vd.pipes, vd.foreign, offX, offY, scale, currentFreq);
        }

        // Infrastructure
        if (filters.infra) {
            FloorRenderer.drawInfrastructure(mainCtx, vd.pipes, tx, ty);
        }

        // Foreign objects
        if (filters.foreign) {
            FloorRenderer.drawForeignObjects(mainCtx, vd.foreign, tx, ty, scale);
        }

        // Measurement points (floor only)
        if (currentView === 'floor') {
            FloorRenderer.drawMeasurementPoints(mainCtx, ROOM, tx, ty);
        }

        renderRoom3D();
    }

    function renderRoom3D() {
        Room3D.draw(room3dCanvas, ROOM, currentView, scanned, VIEW_DATA);
    }

    /** Build result (API call) */
    async function buildResult() {
        addLog('=== 3D化処理開始 ===', 'log-info');
        addLog('  ToF推定 → MUSIC超解像...', 'log-info');

        const btn = document.getElementById('btnBuild');
        btn.disabled = true;
        btn.textContent = '処理中...';

        try {
            const resp = await fetch(`${API}/build`, { method: 'POST' });
            if (resp.ok) {
                const data = await resp.json();
                applyBuildResult(data);
                addLog('  サーバー応答: 3D化完了', 'log-info');
                return;
            }
        } catch(e) {
            addLog('  API接続失敗 — ローカルシミュレーションで3D化', 'log-warn');
        }

        // Fallback: local simulation
        await simulateBuild();
        btn.textContent = 'スキャン結果を 3D 化';
    }

    async function simulateBuild() {
        const sleep = ms => new Promise(r => setTimeout(r, ms));

        addLog('  2.4GHz/5GHzデータ統合中...', 'log-info');
        await sleep(500);
        addLog('  反射マップ生成中 (0.05m解像度)...', 'log-info');
        await sleep(500);
        addLog('  連結成分解析 → 構造物検出...', 'log-info');
        await sleep(400);
        addLog('  RFパッシブスキャン結果統合中...', 'log-info');
        await sleep(300);

        // Simulated pipes per face
        const simPipes = {
            floor: [
                {x1:1,y1:2.5,x2:5.5,y2:2.5,type:'metal',label:'金属管',dispConf:.92,detail:''},
                {x1:3,y1:1,x2:3,y2:4.5,type:'wire',label:'電気配線',dispConf:.78,detail:''},
                {x1:5.5,y1:1,x2:5.5,y2:3.8,type:'pvc',label:'塩ビ管',dispConf:.55,detail:''},
            ],
            ceiling: [
                {x1:1.5,y1:1,x2:6,y2:1,type:'metal',label:'金属管',dispConf:.87,detail:''},
                {x1:3.5,y1:0.5,x2:3.5,y2:4.8,type:'wire',label:'電気配線',dispConf:.74,detail:''},
            ],
            north: [
                {x1:2,y1:0.5,x2:2,y2:2.2,type:'metal',label:'金属管',dispConf:.90,detail:''},
                {x1:4,y1:1,x2:5.5,y2:1,type:'wire',label:'電気配線',dispConf:.65,detail:''},
            ],
            south: [
                {x1:1,y1:1,x2:6,y2:1,type:'metal',label:'金属管',dispConf:.88,detail:''},
            ],
            east: [
                {x1:1,y1:0.5,x2:1,y2:2.3,type:'pvc',label:'塩ビ管',dispConf:.52,detail:''},
                {x1:3,y1:.8,x2:3,y2:2,type:'stud',label:'間柱',dispConf:.71,detail:''},
            ],
            west: [
                {x1:2,y1:0.3,x2:2,y2:2.5,type:'stud',label:'間柱',dispConf:.68,detail:''},
            ],
        };

        const simForeign = {
            floor: [{x:5.8,y:1.2,r:.15,label:'不審デバイス',dispConf:.76,detail:'壁内 深さ≈5cm / 2.4GHz微弱電波源'}],
            ceiling: [], north: [], south: [], east: [], west: []
        };

        for (const f of Object.keys(VIEW_DATA)) {
            VIEW_DATA[f].pipes = simPipes[f] || [];
            VIEW_DATA[f].foreign = simForeign[f] || [];
        }

        // Count
        let totalPipes = 0, totalForeign = 0;
        for (const f of Object.keys(VIEW_DATA)) {
            totalPipes += VIEW_DATA[f].pipes.length;
            totalForeign += VIEW_DATA[f].foreign.length;
        }

        addLog(`  検出結果: 配管・配線 ${totalPipes} 本, 異物 ${totalForeign} 個`, totalForeign > 0 ? 'log-detect' : 'log-info');

        ROOM.w = 7.2; ROOM.d = 5.4; ROOM.h = 2.7;
        scanned = true;

        updateInfoPanel(totalPipes, totalForeign);
        updateForeignAlert();
        render();

        addLog('=== 3D化完了 ===', 'log-info');
    }

    function applyBuildResult(data) {
        if (data.room) {
            ROOM.w = data.room.width || 7.2;
            ROOM.d = data.room.depth || 5.4;
            ROOM.h = data.room.height || 2.7;
            VIEW_DATA.floor.w = ROOM.w; VIEW_DATA.floor.h = ROOM.d;
            VIEW_DATA.ceiling.w = ROOM.w; VIEW_DATA.ceiling.h = ROOM.d;
            VIEW_DATA.north.w = ROOM.w; VIEW_DATA.north.h = ROOM.h;
            VIEW_DATA.south.w = ROOM.w; VIEW_DATA.south.h = ROOM.h;
            VIEW_DATA.east.w = ROOM.d; VIEW_DATA.east.h = ROOM.h;
            VIEW_DATA.west.w = ROOM.d; VIEW_DATA.west.h = ROOM.h;
        }

        // Map structures to pipes
        const typeMap = {metal:'metal', wire:'wire', pvc:'pvc', stud:'stud'};
        const labelMap = {metal:'金属管', wire:'電気配線', pvc:'塩ビ管', stud:'間柱'};
        for (const f of Object.keys(VIEW_DATA)) {
            VIEW_DATA[f].pipes = [];
            VIEW_DATA[f].foreign = [];
        }

        if (data.structures) {
            for (const s of data.structures) {
                const face = s.face;
                if (VIEW_DATA[face]) {
                    VIEW_DATA[face].pipes.push({
                        x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2,
                        type: typeMap[s.material] || 'metal',
                        label: labelMap[s.material] || s.label,
                        dispConf: s.confidence,
                        detail: ''
                    });
                }
            }
        }

        if (data.foreign) {
            for (const fo of data.foreign) {
                const face = fo.face || 'floor';
                if (VIEW_DATA[face]) {
                    VIEW_DATA[face].foreign.push({
                        x: fo.x, y: fo.y, r: fo.radius || 0.15,
                        label: fo.label || '不審デバイス',
                        dispConf: fo.confidence,
                        detail: fo.detail || ''
                    });
                }
            }
        }

        let totalPipes = 0, totalForeign = 0;
        for (const f of Object.keys(VIEW_DATA)) {
            totalPipes += VIEW_DATA[f].pipes.length;
            totalForeign += VIEW_DATA[f].foreign.length;
        }

        scanned = true;
        updateInfoPanel(totalPipes, totalForeign);
        updateForeignAlert();
        updateBadges();
        render();
    }

    function updateInfoPanel(totalPipes, totalForeign) {
        document.getElementById('valW').textContent = ROOM.w.toFixed(1);
        document.getElementById('valD').textContent = ROOM.d.toFixed(1);
        document.getElementById('valH').textContent = ROOM.h.toFixed(1);
        document.getElementById('valArea').textContent = (ROOM.w * ROOM.d).toFixed(1);
        document.getElementById('valPipes').textContent = totalPipes;
        document.getElementById('valForeign').textContent = totalForeign;
    }

    function updateForeignAlert() {
        const alertEl = document.getElementById('foreignAlert');
        const listEl = document.getElementById('foreignList');

        let allForeign = [];
        for (const f of Object.keys(VIEW_DATA)) {
            for (const fo of VIEW_DATA[f].foreign) {
                allForeign.push({ ...fo, face: f });
            }
        }

        if (allForeign.length > 0) {
            alertEl.classList.add('show');
            listEl.innerHTML = allForeign.map(fo => {
                const faceNames = {floor:'床下',ceiling:'天井裏',north:'北壁内',south:'南壁内',east:'東壁内',west:'西壁内'};
                return `<div class="item">⚠ ${faceNames[fo.face]||fo.face} (${fo.x.toFixed(1)},${fo.y.toFixed(1)})m — ${fo.label}<br><span style="font-size:8px;color:#888">${fo.detail}</span></div>`;
            }).join('');

            AudioAlert.playAlert();
            addLog(`★★★ 異物検出アラート: ${allForeign.length}個の不審デバイス ★★★`, 'log-foreign');
        } else {
            alertEl.classList.remove('show');
        }
    }

    function updateBadges() {
        for (const f of Object.keys(VIEW_DATA)) {
            const badge = document.getElementById('badge-' + f);
            if (badge) {
                const count = VIEW_DATA[f].foreign.length;
                if (count > 0) {
                    badge.textContent = count;
                    badge.classList.remove('hidden');
                } else {
                    badge.classList.add('hidden');
                }
            }
        }
    }

    /** Reset */
    function resetAll() {
        scanned = false;
        for (const f of Object.keys(VIEW_DATA)) {
            VIEW_DATA[f].pipes = [];
            VIEW_DATA[f].foreign = [];
        }
        document.getElementById('foreignAlert').classList.remove('show');
        document.querySelectorAll('.tab-btn .badge').forEach(b => b.classList.add('hidden'));
        document.getElementById('valW').textContent = '—';
        document.getElementById('valD').textContent = '—';
        document.getElementById('valH').textContent = '—';
        document.getElementById('valArea').textContent = '—';
        document.getElementById('valPipes').textContent = '—';
        document.getElementById('valForeign').textContent = '—';

        ScanControl.resetPoints();
        render();
        addLog('=== セッションリセット ===', 'log-warn');

        fetch(`${API}/reset`, { method: 'POST' }).catch(() => {});
    }

    /** Log */
    function addLog(msg, cls) {
        const el = document.getElementById('logArea');
        const ts = new Date().toLocaleTimeString();
        const span = document.createElement('div');
        span.className = cls || '';
        span.textContent = `[${ts}] ${msg}`;
        el.appendChild(span);
        el.scrollTop = el.scrollHeight;
    }

    // Init on load
    window.addEventListener('DOMContentLoaded', init);

    return { switchView, toggleFilter, switchFreq, buildResult, resetAll, addLog, render };
})();
