/**
 * RuView Scan - 5箇所スキャンUI制御
 */
const ScanControl = (function() {
    const API_BASE = '/api';
    
    const SCAN_POINTS = [
        { id:'north', name:'① 北壁側 (pos.1)', desc:'ノートPCを北壁から1mの位置に配置', status:'ready', pct24:0, pct5:0 },
        { id:'east',  name:'② 東壁側 (pos.2)', desc:'ノートPCを東壁から1mの位置に配置', status:'ready', pct24:0, pct5:0 },
        { id:'south', name:'③ 南壁側 (pos.3)', desc:'ノートPCを南壁から1mの位置に配置', status:'ready', pct24:0, pct5:0 },
        { id:'west',  name:'④ 西壁側 (pos.4)', desc:'ノートPCを西壁から1mの位置に配置', status:'ready', pct24:0, pct5:0 },
        { id:'center',name:'⑤ 中心 (pos.5)',   desc:'ノートPCを部屋中央に配置',         status:'ready', pct24:0, pct5:0 },
    ];
    let scanRunning = false;

    function renderScanList() {
        const el = document.getElementById('scanList');
        el.innerHTML = SCAN_POINTS.map((sp, i) => {
            const dotClass = sp.status === 'done' ? 'done' : sp.status === 'scanning' ? 'running' : 'ready';
            const cardClass = sp.status === 'done' ? 'done' : sp.status === 'scanning' ? 'active' : '';
            const btnDisabled = sp.status === 'done' || sp.status === 'scanning' || scanRunning ? 'disabled' : '';
            const btnClass = sp.status === 'scanning' ? 'running' : '';
            const statusText = sp.status === 'ready' ? '待機中' : sp.status === 'scanning' ? '計測中...' : '完了 ✓';
            const statusClass = sp.status === 'scanning' ? 'active-status' : sp.status === 'done' ? 'done-status' : '';

            const pct24w = sp.pct24 + '%';
            const pct5w = sp.pct5 + '%';
            const f24color = sp.pct24 >= 100 ? '#4caf50' : sp.status === 'scanning' ? '#ffa726' : '#555';
            const f5color = sp.pct5 >= 100 ? '#4caf50' : (sp.status === 'scanning' && sp.pct24 >= 100) ? '#4fc3f7' : '#555';

            return `<div class="scan-point ${cardClass}">
                <div class="sp-header">
                    <div class="sp-name"><div class="sp-dot ${dotClass}"></div>${sp.name}</div>
                    <button class="sp-btn ${btnClass}" ${btnDisabled} onclick="ScanControl.startPointScan(${i})">スキャン</button>
                </div>
                <div style="font-size:9px;color:#5a6a7a">${sp.desc}</div>
                <div class="sp-freq">
                    <div class="sp-freq-item"><div class="fq-dot" style="background:${f24color}"></div>2.4GHz</div>
                    <div class="sp-freq-item"><div class="fq-dot" style="background:${f5color}"></div>5GHz</div>
                </div>
                <div class="sp-progress"><div class="sp-fill sp-fill-24" id="fill24-${i}" style="width:${pct24w}"></div></div>
                <div class="sp-progress"><div class="sp-fill sp-fill-5" id="fill5-${i}" style="width:${pct5w}"></div></div>
                <div class="sp-status ${statusClass}" id="spStatus-${i}">${statusText}</div>
            </div>`;
        }).join('');
    }

    async function startPointScan(idx) {
        if (!RuView.isRoomReady()) {
            alert('先に部屋寸法を入力・確定してください');
            return;
        }
        if (scanRunning) return;
        scanRunning = true;
        const sp = SCAN_POINTS[idx];
        sp.status = 'scanning';
        sp.pct24 = 0; sp.pct5 = 0;
        renderScanList();
        RuView.addLog(`=== ${sp.name} スキャン開始 ===`, 'log-info');

        try {
            const resp = await fetch(`${API_BASE}/scan/${sp.id}/start`, { method: 'POST' });
            if (!resp.ok) {
                throw new Error(`API error: ${resp.status}`);
            }
            RuView.addLog(`  API: スキャン開始要求送信 (${sp.id})`, 'log-info');
        } catch(e) {
            RuView.addLog(`  API接続失敗 — ローカルシミュレーションで実行`, 'log-warn');
            await simulateLocalScan(idx);
        }
    }

    async function simulateLocalScan(idx) {
        const sp = SCAN_POINTS[idx];
        const statusEl = document.getElementById('spStatus-' + idx);
        const fill24 = document.getElementById('fill24-' + idx);

        statusEl.textContent = '[SIM] 2.4 GHz 計測中... (30秒)';
        statusEl.className = 'sp-status active-status';
        RuView.addLog(`  [SIM] 2.4 GHz CSI取得開始 (ch1, 40MHz, 114 subcarriers)`, 'log-warn');

        for (let t = 0; t <= 30; t++) {
            sp.pct24 = Math.round((t / 30) * 100);
            fill24.style.width = sp.pct24 + '%';
            statusEl.textContent = `2.4 GHz 計測中... ${t}/30秒 (${sp.pct24}%)`;
            if (t % 10 === 0 && t > 0) RuView.addLog(`    2.4GHz: ${t}秒経過, ${t*100}フレーム取得`);
            await sleep(100);
        }
        RuView.addLog(`  2.4 GHz 完了: 3000フレーム`, 'log-info');

        const fill5 = document.getElementById('fill5-' + idx);
        RuView.addLog(`  5 GHz CSI取得開始 (ch36, 80MHz, 234 subcarriers)`, 'log-info');

        for (let t = 0; t <= 30; t++) {
            sp.pct5 = Math.round((t / 30) * 100);
            fill5.style.width = sp.pct5 + '%';
            statusEl.textContent = `5 GHz 計測中... ${t}/30秒 (${sp.pct5}%)`;
            if (t % 10 === 0 && t > 0) RuView.addLog(`    5GHz: ${t}秒経過, ${t*100}フレーム取得`);
            await sleep(100);
        }
        RuView.addLog(`  5 GHz 完了: 3000フレーム`, 'log-info');

        sp.status = 'done';
        scanRunning = false;
        renderScanList();
        RuView.addLog(`=== ${sp.name} 計測完了 ===`, 'log-info');
        checkAllDone();
    }

    function handleWSProgress(data) {
        if (data.type !== 'progress') return;
        
        const idx = SCAN_POINTS.findIndex(sp => sp.id === data.point_id);
        if (idx < 0) return;
        
        const sp = SCAN_POINTS[idx];
        sp.status = 'scanning';
        
        if (data.phase === '2.4GHz') {
            sp.pct24 = data.progress;
            const fill = document.getElementById('fill24-' + idx);
            if (fill) fill.style.width = data.progress + '%';
        } else {
            sp.pct5 = data.progress;
            const fill = document.getElementById('fill5-' + idx);
            if (fill) fill.style.width = data.progress + '%';
        }
        
        const statusEl = document.getElementById('spStatus-' + idx);
        if (statusEl) {
            statusEl.textContent = `${data.phase} 計測中... (${data.progress}%)`;
            statusEl.className = 'sp-status active-status';
        }
    }

    function handleWSComplete(data) {
        if (data.type !== 'scan_complete') return;
        
        const idx = SCAN_POINTS.findIndex(sp => sp.id === data.point_id);
        if (idx < 0) return;
        
        const sp = SCAN_POINTS[idx];
        sp.status = 'done';
        sp.pct24 = 100;
        sp.pct5 = 100;
        scanRunning = false;
        renderScanList();
        RuView.addLog(`=== ${sp.name} 計測完了 ===`, 'log-info');
        checkAllDone();
    }

    function checkAllDone() {
        const allDone = SCAN_POINTS.every(s => s.status === 'done');
        if (allDone) {
            document.getElementById('btnBuild').disabled = false;
            document.getElementById('globalStatus').textContent = '全5箇所の計測が完了しました。「スキャン結果を3D化」を押してください';
            document.getElementById('globalStatus').style.color = '#4caf50';
            RuView.addLog('★ 全5箇所の計測が完了 — 3D化の準備ができました', 'log-info');
        } else {
            const remaining = SCAN_POINTS.filter(s => s.status === 'ready').length;
            document.getElementById('globalStatus').textContent = `残り ${remaining} 箇所`;
        }
    }

    function resetPoints() {
        SCAN_POINTS.forEach(s => { s.status = 'ready'; s.pct24 = 0; s.pct5 = 0; });
        scanRunning = false;
        renderScanList();
        document.getElementById('btnBuild').disabled = true;
        document.getElementById('globalStatus').textContent = '全5箇所の計測を行ってください';
        document.getElementById('globalStatus').style.color = '#5a6a7a';
    }

    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    // WebSocket listeners
    if (typeof RuViewWS !== 'undefined') {
        RuViewWS.onMessage(handleWSProgress);
        RuViewWS.onMessage(handleWSComplete);
    }

    // Init
    renderScanList();

    return { startPointScan, resetPoints, renderScanList, SCAN_POINTS };
})();
