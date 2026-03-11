/**
 * RuView Scan - 9箇所スキャンUI制御 (Phase D: 4隅追加 + 160MHz対応)
 */
const ScanControl = (function() {
    const API_BASE = '/api';

    const SCAN_POINTS = [
        { id:'north', name:'① 北壁側 (pos.1)', desc:'ノートPCを北壁から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:false },
        { id:'east',  name:'② 東壁側 (pos.2)', desc:'ノートPCを東壁から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:false },
        { id:'south', name:'③ 南壁側 (pos.3)', desc:'ノートPCを南壁から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:false },
        { id:'west',  name:'④ 西壁側 (pos.4)', desc:'ノートPCを西壁から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:false },
        { id:'center',name:'⑤ 中心 (pos.5)',   desc:'ノートPCを部屋中央に配置',         status:'ready', pct24:0, pct5:0, pct160:0, optional:false },
        { id:'northeast', name:'⑥ 北東角 (pos.6)', desc:'ノートPCを北東角から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:true },
        { id:'southeast', name:'⑦ 南東角 (pos.7)', desc:'ノートPCを南東角から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:true },
        { id:'southwest', name:'⑧ 南西角 (pos.8)', desc:'ノートPCを南西角から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:true },
        { id:'northwest', name:'⑨ 北西角 (pos.9)', desc:'ノートPCを北西角から1mの位置に配置', status:'ready', pct24:0, pct5:0, pct160:0, optional:true },
    ];
    let scanRunning = false;

    function renderScanList() {
        const el = document.getElementById('scanList');
        var requiredHtml = '';
        var optionalHtml = '';

        SCAN_POINTS.forEach(function(sp, i) {
            var html = _renderPointCard(sp, i);
            if (sp.optional) { optionalHtml += html; }
            else { requiredHtml += html; }
        });

        el.innerHTML = requiredHtml;
        if (optionalHtml) {
            el.innerHTML += '<div style="font-size:9px;color:#4fc3f7;margin:6px 0 2px;padding:2px 6px;border-top:1px solid #1a2a3a">▼ 追加ポイント (任意 - 精度向上)</div>' + optionalHtml;
        }
    }

    function _renderPointCard(sp, i) {
        var dotClass = sp.status === 'done' ? 'done' : sp.status === 'scanning' ? 'running' : 'ready';
        var cardClass = sp.status === 'done' ? 'done' : sp.status === 'scanning' ? 'active' : '';
        var btnDisabled = sp.status === 'done' || sp.status === 'scanning' || scanRunning ? 'disabled' : '';
        var btnClass = sp.status === 'scanning' ? 'running' : '';
        var statusText = sp.status === 'ready' ? '待機中' : sp.status === 'scanning' ? '計測中...' : '完了 ✓';
        var statusClass = sp.status === 'scanning' ? 'active-status' : sp.status === 'done' ? 'done-status' : '';
        var optLabel = sp.optional ? ' <span style="font-size:8px;color:#4fc3f7">[任意]</span>' : '';

        var pct24w = sp.pct24 + '%';
        var pct5w = sp.pct5 + '%';
        var pct160w = sp.pct160 + '%';
        var f24color = sp.pct24 >= 100 ? '#4caf50' : sp.status === 'scanning' ? '#ffa726' : '#555';
        var f5color = sp.pct5 >= 100 ? '#4caf50' : (sp.status === 'scanning' && sp.pct24 >= 100) ? '#4fc3f7' : '#555';
        var f160color = sp.pct160 >= 100 ? '#4caf50' : (sp.status === 'scanning' && sp.pct5 >= 100) ? '#ce93d8' : '#555';

        return '<div class="scan-point ' + cardClass + '">' +
            '<div class="sp-header">' +
            '<div class="sp-name"><div class="sp-dot ' + dotClass + '"></div>' + sp.name + optLabel + '</div>' +
            '<button class="sp-btn ' + btnClass + '" ' + btnDisabled + ' onclick="ScanControl.startPointScan(' + i + ')">スキャン</button>' +
            '</div>' +
            '<div style="font-size:9px;color:#5a6a7a">' + sp.desc + '</div>' +
            '<div class="sp-freq">' +
            '<div class="sp-freq-item"><div class="fq-dot" style="background:' + f24color + '"></div>2.4GHz</div>' +
            '<div class="sp-freq-item"><div class="fq-dot" style="background:' + f5color + '"></div>5GHz</div>' +
            '<div class="sp-freq-item"><div class="fq-dot" style="background:' + f160color + '"></div>160MHz</div>' +
            '</div>' +
            '<div class="sp-progress"><div class="sp-fill sp-fill-24" id="fill24-' + i + '" style="width:' + pct24w + '"></div></div>' +
            '<div class="sp-progress"><div class="sp-fill sp-fill-5" id="fill5-' + i + '" style="width:' + pct5w + '"></div></div>' +
            '<div class="sp-progress"><div class="sp-fill sp-fill-160" id="fill160-' + i + '" style="width:' + pct160w + '"></div></div>' +
            '<div class="sp-status ' + statusClass + '" id="spStatus-' + i + '">' + statusText + '</div>' +
            '</div>';
    }

    async function startPointScan(idx) {
        if (!RuView.isRoomReady()) {
            alert('先に部屋寸法を入力・確定してください');
            return;
        }
        if (scanRunning) return;
        scanRunning = true;
        var sp = SCAN_POINTS[idx];
        sp.status = 'scanning';
        sp.pct24 = 0; sp.pct5 = 0; sp.pct160 = 0;
        renderScanList();
        RuView.addLog('=== ' + sp.name + ' スキャン開始 ===', 'log-info');

        try {
            var resp = await fetch(API_BASE + '/scan/' + sp.id + '/start', { method: 'POST' });
            if (!resp.ok) { throw new Error('API error: ' + resp.status); }
            RuView.addLog('  API: スキャン開始要求送信 (' + sp.id + ')', 'log-info');
        } catch(e) {
            RuView.addLog('  API接続失敗 — ローカルシミュレーションで実行', 'log-warn');
            await simulateLocalScan(idx);
        }
    }

    async function simulateLocalScan(idx) {
        var sp = SCAN_POINTS[idx];
        var statusEl = document.getElementById('spStatus-' + idx);

        // 2.4GHz
        var fill24 = document.getElementById('fill24-' + idx);
        statusEl.textContent = '[SIM] 2.4 GHz 計測中... (30秒)';
        statusEl.className = 'sp-status active-status';
        RuView.addLog('  [SIM] 2.4 GHz CSI取得開始 (ch1, 40MHz, 114 subcarriers)', 'log-warn');
        for (var t = 0; t <= 30; t++) {
            sp.pct24 = Math.round((t / 30) * 100);
            fill24.style.width = sp.pct24 + '%';
            statusEl.textContent = '2.4 GHz 計測中... ' + t + '/30秒 (' + sp.pct24 + '%)';
            if (t % 10 === 0 && t > 0) RuView.addLog('    2.4GHz: ' + t + '秒経過, ' + (t*100) + 'フレーム取得');
            await sleep(100);
        }
        RuView.addLog('  2.4 GHz 完了: 3000フレーム', 'log-info');

        // 5GHz 80MHz
        var fill5 = document.getElementById('fill5-' + idx);
        RuView.addLog('  [SIM] 5 GHz CSI取得開始 (ch36, 80MHz, 234 subcarriers)', 'log-info');
        for (var t = 0; t <= 30; t++) {
            sp.pct5 = Math.round((t / 30) * 100);
            fill5.style.width = sp.pct5 + '%';
            statusEl.textContent = '5 GHz (80MHz) 計測中... ' + t + '/30秒 (' + sp.pct5 + '%)';
            if (t % 10 === 0 && t > 0) RuView.addLog('    5GHz: ' + t + '秒経過, ' + (t*100) + 'フレーム取得');
            await sleep(100);
        }
        RuView.addLog('  5 GHz (80MHz) 完了: 3000フレーム', 'log-info');

        // 5GHz 160MHz
        var fill160 = document.getElementById('fill160-' + idx);
        RuView.addLog('  [SIM] 5 GHz 160MHz CSI取得開始 (ch36, 160MHz, 468 subcarriers)', 'log-info');
        for (var t = 0; t <= 30; t++) {
            sp.pct160 = Math.round((t / 30) * 100);
            fill160.style.width = sp.pct160 + '%';
            statusEl.textContent = '5 GHz (160MHz) 計測中... ' + t + '/30秒 (' + sp.pct160 + '%)';
            if (t % 10 === 0 && t > 0) RuView.addLog('    160MHz: ' + t + '秒経過, ' + (t*100) + 'フレーム取得');
            await sleep(100);
        }
        RuView.addLog('  5 GHz (160MHz) 完了: 3000フレーム', 'log-info');

        sp.status = 'done';
        scanRunning = false;
        renderScanList();
        RuView.addLog('=== ' + sp.name + ' 計測完了 ===', 'log-info');
        checkAllDone();
    }

    function handleWSProgress(data) {
        if (data.type !== 'progress') return;
        var idx = SCAN_POINTS.findIndex(function(sp) { return sp.id === data.point_id; });
        if (idx < 0) return;
        var sp = SCAN_POINTS[idx];
        sp.status = 'scanning';

        if (data.phase === '2.4GHz') {
            sp.pct24 = data.progress;
            var fill = document.getElementById('fill24-' + idx);
            if (fill) fill.style.width = data.progress + '%';
        } else if (data.phase === '5GHz_160') {
            sp.pct160 = data.progress;
            var fill = document.getElementById('fill160-' + idx);
            if (fill) fill.style.width = data.progress + '%';
        } else {
            sp.pct5 = data.progress;
            var fill = document.getElementById('fill5-' + idx);
            if (fill) fill.style.width = data.progress + '%';
        }

        var statusEl = document.getElementById('spStatus-' + idx);
        if (statusEl) {
            statusEl.textContent = data.phase + ' 計測中... (' + data.progress + '%)';
            statusEl.className = 'sp-status active-status';
        }
    }

    function handleWSComplete(data) {
        if (data.type !== 'scan_complete') return;
        var idx = SCAN_POINTS.findIndex(function(sp) { return sp.id === data.point_id; });
        if (idx < 0) return;
        var sp = SCAN_POINTS[idx];
        sp.status = 'done';
        sp.pct24 = 100; sp.pct5 = 100; sp.pct160 = 100;
        scanRunning = false;
        renderScanList();
        RuView.addLog('=== ' + sp.name + ' 計測完了 ===', 'log-info');
        checkAllDone();
    }

    function checkAllDone() {
        var requiredDone = SCAN_POINTS.filter(function(s) { return !s.optional; }).every(function(s) { return s.status === 'done'; });
        var allDone = SCAN_POINTS.every(function(s) { return s.status === 'done'; });
        var optionalDone = SCAN_POINTS.filter(function(s) { return s.optional && s.status === 'done'; }).length;
        var optionalTotal = SCAN_POINTS.filter(function(s) { return s.optional; }).length;

        if (requiredDone) {
            document.getElementById('btnBuild').disabled = false;
            var msg = '必須5箇所の計測が完了';
            if (optionalDone < optionalTotal) {
                msg += ' (追加ポイント: ' + optionalDone + '/' + optionalTotal + ' — スキップ可能)';
            } else if (allDone) {
                msg = '全9箇所の計測が完了';
            }
            msg += '。「スキャン結果を3D化」を押してください';
            document.getElementById('globalStatus').textContent = msg;
            document.getElementById('globalStatus').style.color = '#4caf50';
            RuView.addLog('★ ' + msg, 'log-info');
        } else {
            var remaining = SCAN_POINTS.filter(function(s) { return !s.optional && s.status === 'ready'; }).length;
            document.getElementById('globalStatus').textContent = '必須ポイント 残り ' + remaining + ' 箇所';
        }
    }

    function resetPoints() {
        SCAN_POINTS.forEach(function(s) { s.status = 'ready'; s.pct24 = 0; s.pct5 = 0; s.pct160 = 0; });
        scanRunning = false;
        renderScanList();
        document.getElementById('btnBuild').disabled = true;
        document.getElementById('globalStatus').textContent = '全5箇所(必須) + 4箇所(任意)の計測を行ってください';
        document.getElementById('globalStatus').style.color = '#5a6a7a';
    }

    function sleep(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }

    if (typeof RuViewWS !== 'undefined') {
        RuViewWS.onMessage(handleWSProgress);
        RuViewWS.onMessage(handleWSComplete);
    }

    renderScanList();

    return { startPointScan: startPointScan, resetPoints: resetPoints, renderScanList: renderScanList, SCAN_POINTS: SCAN_POINTS };
})();