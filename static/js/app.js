/**
 * RuView Scan - メインアプリケーション
 * Phase B+: カラーマップ切替 + 透明度 + プリセット + マウスホバー値表示
 */
const RuView = (function () {
    const API = '/api';

    // --- State ---
    let currentView = 'floor';
    let currentFreq = 'mix';
    let diffCutEnabled = false;
    let currentColorMap = 'thermal';
    let heatmapOpacity = 1.0;
    let contrastEnhance = false;

    let scanned = false;
    const filters = { infra: false, foreign: true, heatmap: true };
    let roomConfirmed = false;
    const manualRoom = { w: 0, d: 0, h: 0 };

    const ROOM = { w: 7.2, d: 5.4, h: 2.7 };

    const VIEW_DATA = {
        floor: { label: '床面', w: ROOM.w, h: ROOM.d, pipes: [], foreign: [] },
        ceiling: { label: '天井', w: ROOM.w, h: ROOM.d, pipes: [], foreign: [] },
        north: { label: '北壁', w: ROOM.w, h: ROOM.h, pipes: [], foreign: [] },
        south: { label: '南壁', w: ROOM.w, h: ROOM.h, pipes: [], foreign: [] },
        east: { label: '東壁', w: ROOM.d, h: ROOM.h, pipes: [], foreign: [] },
        west: { label: '西壁', w: ROOM.d, h: ROOM.h, pipes: [], foreign: [] },
    };

    const GRID_DATA = {
        floor: null, ceiling: null, north: null,
        south: null, east: null, west: null,
    };

    const SLIDER_STATE = {
        floor: { lower: 0, upper: 1 },
        ceiling: { lower: 0, upper: 1 },
        north: { lower: 0, upper: 1 },
        south: { lower: 0, upper: 1 },
        east: { lower: 0, upper: 1 },
        west: { lower: 0, upper: 1 },
    };

    const PRESETS = {
        all: { lower: 0.00, upper: 1.00 },
        surface: { lower: 0.00, upper: 0.30 },
        shallow: { lower: 0.30, upper: 0.65 },
        deep: { lower: 0.65, upper: 1.00 },
    };

    // render()で使う描画パラメータを保存（ホバー計算用）
    let lastDrawParams = { offX: 0, offY: 0, drawW: 0, drawH: 0, scale: 1 };

    let mainCanvas, mainCtx, room3dCanvas;
    let is3DMode = false;
    let three3dInitialized = false;

    /** Init */
    function init() {
        mainCanvas = document.getElementById('mainCanvas');
        mainCtx = mainCanvas.getContext('2d');
        room3dCanvas = document.getElementById('room3dCanvas');
        _setupCanvasSize();
        window.addEventListener('resize', _setupCanvasSize);

        // マウスホバーイベント
        mainCanvas.addEventListener('mousemove', _onCanvasMouseMove);
        mainCanvas.addEventListener('mouseleave', _onCanvasMouseLeave);

        render();
        // foreignAlert クリックでモーダルを開く
        var fa = document.getElementById('foreignAlert');
        if (fa) fa.addEventListener('click', function () { openForeignModal(); });
        addLog('RuView Scan v1.1 起動', 'log-info');
        addLog('モバイルWi-Fiルーターを部屋中心に設置してください', 'log-info');

        // F-0l: システムステータス取得
        _fetchSystemStatus();
    }

    function _setupCanvasSize() {
        var container = mainCanvas.parentElement;
        mainCanvas.width = container.clientWidth;
        mainCanvas.height = container.clientHeight;
        room3dCanvas.width = room3dCanvas.parentElement.clientWidth - 24;
        room3dCanvas.height = 160;
        render();
    }

    /** Tab switch */
    function switchView(view) {
        _saveSliderState();
        currentView = view;
        document.querySelectorAll('.tab-btn').forEach(function (b) {
            b.classList.toggle('active', b.dataset.view === view);
        });

        var canvas2d = document.getElementById('mainCanvas');
        var container3d = document.getElementById('three3dContainer');

        if (view === '3d') {
            is3DMode = true;
            canvas2d.style.display = 'none';
            container3d.style.display = 'block';

            if (!three3dInitialized) {
                Room3DView.init('three3dContainer');
                Room3DView.buildRoom(ROOM);
                three3dInitialized = true;
            } else {
                Room3DView.onResize();
            }
            Room3DView.startAnimation();
            _update3DTextures();
        } else {
            is3DMode = false;
            canvas2d.style.display = 'block';
            container3d.style.display = 'none';
            Room3DView.stopAnimation();
            _restoreSliderState();
            render();
        }
    }

    /** Filter toggle */
    function toggleFilter(key) {
        filters[key] = !filters[key];
        document.querySelectorAll('.filter-btn').forEach(function (b) {
            if (b.dataset.filter === key) b.classList.toggle('on', filters[key]);
        });
        if (is3DMode) {
            _update3DTextures();
        } else {
            render();
        }
    }

    /** Frequency switch */
    function switchFreq(freq) {
        currentFreq = freq;
        document.querySelectorAll('.freq-btn').forEach(function (b) {
            b.classList.toggle('active', b.dataset.freq === freq);
        });
        if (scanned) _fetchGridForCurrentView();
        render();
    }


    /** Color map switch */
    function switchColorMap(cmapId) {
        currentColorMap = cmapId;
        document.querySelectorAll('.cmap-btn').forEach(function (b) {
            b.classList.toggle('active', b.dataset.cmap === cmapId);
        });
        if (is3DMode) { _update3DTextures(); } else { render(); }
    }

    /** 壁反射カット トグル */
    function toggleDiffCut() {
        diffCutEnabled = !diffCutEnabled;
        var btn = document.getElementById('btnDiffCut');
        if (btn) { btn.classList.toggle('on', diffCutEnabled); }
        addLog('壁反射カット: ' + (diffCutEnabled ? 'ON' : 'OFF'), 'log-info');
        if (scanned) {
            _fetchAllGrids();
        }
    }

    /** コントラスト強調 トグル */
    function toggleContrastEnhance() {
        contrastEnhance = !contrastEnhance;
        var btn = document.getElementById('btnContrastEnhance');
        if (btn) { btn.classList.toggle('on', contrastEnhance); }
        addLog('コントラスト強調: ' + (contrastEnhance ? 'ON' : 'OFF'), 'log-info');
        if (is3DMode) { _update3DTextures(); } else { render(); }
    }


    async function _fetchAllGrids() {
        var bandParam;
        if (diffCutEnabled) {
            bandParam = 'diff';
        } else {
            bandParam = currentFreq === '24' ? '24' : currentFreq === '5' ? '5' : currentFreq === '160' ? '160' : 'mix';
        }

        var faces = ['floor', 'ceiling', 'north', 'south', 'east', 'west'];
        var loaded = 0;
        for (var i = 0; i < faces.length; i++) {
            try {
                var resp = await fetch(API + '/result/map/' + faces[i] + '/' + bandParam);
                if (resp.ok) {
                    var data = await resp.json();
                    GRID_DATA[faces[i]] = data.grid;
                    loaded++;
                }
            } catch (e) { /* skip */ }
        }
        addLog('グリッド更新: ' + loaded + '/6面 (' + bandParam + ')', 'log-info');
        if (is3DMode && three3dInitialized) { _update3DTextures(); }
        render();
    }




    /** Depth slider change */
    function onSliderChange() {
        var lowerEl = document.getElementById('sliderLower');
        var upperEl = document.getElementById('sliderUpper');
        var lower = parseInt(lowerEl.value) / 100;
        var upper = parseInt(upperEl.value) / 100;

        if (lower > upper) {
            lower = upper;
            lowerEl.value = Math.floor(lower * 100);
        }

        document.getElementById('sliderLowerVal').textContent = lower.toFixed(2);
        document.getElementById('sliderUpperVal').textContent = upper.toFixed(2);
        if (SLIDER_STATE[currentView]) {
            SLIDER_STATE[currentView].lower = lower;
            SLIDER_STATE[currentView].upper = upper;
        }
        if (is3DMode) { _update3DTextures(); } else { render(); }
    }

    /** Opacity slider change */
    function onOpacityChange() {
        var val = parseInt(document.getElementById('sliderOpacity').value);
        heatmapOpacity = val / 100;
        document.getElementById('sliderOpacityVal').textContent = val + '%';
        if (is3DMode) { _update3DTextures(); } else { render(); }
    }

    /** Preset apply */
    function applyPreset(presetId) {
        if (presetId === 'auto') {
            _applyAutoPreset();
            return;
        }
        var preset = PRESETS[presetId];
        if (!preset) return;

        SLIDER_STATE[currentView].lower = preset.lower;
        SLIDER_STATE[currentView].upper = preset.upper;
        _restoreSliderState();
        render();
    }

    function _applyAutoPreset() {
        var grid = GRID_DATA[currentView];
        if (!grid || grid.length === 0) {
            applyPreset('all');
            return;
        }

        // ピーク値を検出
        var peak = 0;
        for (var r = 0; r < grid.length; r++) {
            for (var c = 0; c < grid[r].length; c++) {
                if (grid[r][c] > peak) peak = grid[r][c];
            }
        }

        // ピークの±20%を範囲に設定
        var lower = Math.max(0, peak - 0.20);
        var upper = Math.min(1, peak + 0.20);
        SLIDER_STATE[currentView].lower = lower;
        SLIDER_STATE[currentView].upper = upper;
        _restoreSliderState();
        if (is3DMode) { _update3DTextures(); }
        addLog('自動プリセット: peak=' + peak.toFixed(2) + ' → [' + lower.toFixed(2) + ', ' + upper.toFixed(2) + ']', 'log-info');
        render();
    }

    function _saveSliderState() {
        if (!SLIDER_STATE[currentView]) return;
        SLIDER_STATE[currentView].lower = parseInt(document.getElementById('sliderLower').value) / 100;
        SLIDER_STATE[currentView].upper = parseInt(document.getElementById('sliderUpper').value) / 100;
    }

    function _restoreSliderState() {
        if (!SLIDER_STATE[currentView]) return;
        var state = SLIDER_STATE[currentView];
        document.getElementById('sliderLower').value = Math.floor(state.lower * 100);
        document.getElementById('sliderUpper').value = Math.floor(state.upper * 100);
        document.getElementById('sliderLowerVal').textContent = state.lower.toFixed(2);
        document.getElementById('sliderUpperVal').textContent = state.upper.toFixed(2);
    }

    /** Mouse hover on canvas */
    function _onCanvasMouseMove(e) {
        var tooltip = document.getElementById('hoverTooltip');
        var grid = GRID_DATA[currentView];
        if (!grid || !scanned || !filters.heatmap) {
            tooltip.classList.add('hidden');
            return;
        }

        var rect = mainCanvas.getBoundingClientRect();
        var mouseX = e.clientX - rect.left;
        var mouseY = e.clientY - rect.top;

        var vd = VIEW_DATA[currentView];
        var probe = HeatmapRenderer.probeGrid(
            grid, mouseX, mouseY,
            lastDrawParams.offX, lastDrawParams.offY,
            lastDrawParams.drawW, lastDrawParams.drawH,
            vd.w, vd.h
        );

        if (!probe) {
            tooltip.classList.add('hidden');
            return;
        }

        tooltip.classList.remove('hidden');
        tooltip.innerHTML =
            '<span class="tt-coord">(' + probe.x_m + ', ' + probe.y_m + ')m</span> ' +
            '<span class="tt-val">' + probe.value.toFixed(3) + '</span>';

        // ツールチップ位置（マウスの右上に表示、画面端で折り返し）
        var tx = mouseX + 14;
        var ty = mouseY - 28;
        var container = mainCanvas.parentElement;
        if (tx + 180 > container.clientWidth) tx = mouseX - 180;
        if (ty < 0) ty = mouseY + 14;
        tooltip.style.left = tx + 'px';
        tooltip.style.top = ty + 'px';
    }

    function _onCanvasMouseLeave() {
        document.getElementById('hoverTooltip').classList.add('hidden');
    }

    /** Update 3D textures with current slider/colormap settings */
    function _update3DTextures() {
        if (!three3dInitialized || !scanned) return;
        var lower = parseInt(document.getElementById('sliderLower').value) / 100;
        var upper = parseInt(document.getElementById('sliderUpper').value) / 100;
        if (filters.heatmap) {
            Room3DView.updateAllFaces(GRID_DATA, lower, upper, currentColorMap, heatmapOpacity);
        } else {
            Room3DView.updateAllFaces(null, 0, 1, currentColorMap, 0);
        }
        console.log('3D structures update:', 'infra=' + filters.infra, 'foreign=' + filters.foreign);
        var totalP = 0, totalF = 0;
        for (var _f in VIEW_DATA) { totalP += VIEW_DATA[_f].pipes.length; totalF += VIEW_DATA[_f].foreign.length; }
        console.log('  totalPipes=' + totalP + ', totalForeign=' + totalF);
        var sl3d = { lower: parseFloat(document.getElementById('sliderLower').value), upper: parseFloat(document.getElementById('sliderUpper').value) };
        Room3DView.updateStructures(VIEW_DATA, ROOM, filters.infra, filters.foreign, sl3d.lower, sl3d.upper);
    }

    /** Render main canvas */
    function render() {
        if (!mainCtx) return;
        var cw = mainCanvas.width, ch = mainCanvas.height;
        mainCtx.clearRect(0, 0, cw, ch);

        var vd = VIEW_DATA[currentView];
        if (!vd) return;

        var padL = 18, padR = 4, padT = 30, padB = 18;
        var drawW = cw - padL - padR;
        var drawH = ch - padT - padB;
        var offX = padL;
        var offY = padT;
        var scale = drawW / vd.w;
        var scaleX = drawW / vd.w;
        var scaleY = drawH / vd.h;
        var tx = function (x) { return offX + x * scaleX; };
        var ty = function (y) { return offY + y * scaleY; };

        // ホバー計算用にパラメータ保存
        lastDrawParams.offX = offX;
        lastDrawParams.offY = offY;
        lastDrawParams.drawW = vd.w * scale;
        lastDrawParams.drawH = vd.h * scale;
        lastDrawParams.scale = scale;

        // Grid lines
        mainCtx.strokeStyle = '#1a2540'; mainCtx.lineWidth = 0.5; mainCtx.setLineDash([]);
        for (var x = 0; x <= vd.w; x += 1) { mainCtx.beginPath(); mainCtx.moveTo(tx(x), offY); mainCtx.lineTo(tx(x), offY + drawH); mainCtx.stroke(); }
        for (var y = 0; y <= vd.h; y += 1) { mainCtx.beginPath(); mainCtx.moveTo(offX, ty(y)); mainCtx.lineTo(offX + drawW, ty(y)); mainCtx.stroke(); }

        // Wall outline
        mainCtx.strokeStyle = '#4fc3f7'; mainCtx.lineWidth = 2; mainCtx.setLineDash([]);
        mainCtx.strokeRect(offX, offY, drawW, drawH);

        // Scale text
        mainCtx.font = '9px Meiryo'; mainCtx.fillStyle = '#4a6a8a'; mainCtx.textAlign = 'center';
        mainCtx.fillText(vd.w.toFixed(1) + 'm', offX + drawW / 2, offY + drawH + 14);
        mainCtx.save(); mainCtx.translate(offX - 14, offY + drawH / 2);
        mainCtx.rotate(-Math.PI / 2); mainCtx.fillText(vd.h.toFixed(1) + 'm', 0, 0); mainCtx.restore();

        // View label
        mainCtx.font = '14px Meiryo'; mainCtx.fillStyle = '#4fc3f7'; mainCtx.textAlign = 'left';
        var freqLabel = currentFreq === 'mix' ? '2.4+5+160MHz' : currentFreq === '24' ? '2.4GHz' : currentFreq === '5' ? '5GHz(80MHz)' : '5GHz(160MHz)';
        mainCtx.fillText('◆ ' + vd.label + ' (' + freqLabel + ')', 10, 22);

        // 床面は常に測定点を表示（スキャン前でもポジションを可視化）
        if (currentView === 'floor') {
            FloorRenderer.drawMeasurementPoints(mainCtx, ROOM, tx, ty);
        }

        if (!scanned) {
            mainCtx.font = '16px Meiryo'; mainCtx.fillStyle = '#3a4a6a'; mainCtx.textAlign = 'center';
            mainCtx.fillText('全 5 箇所の計測後に描画されます', cw / 2, ch / 2);
            renderRoom3D();
            return;
        }

        // Slider state (配管・異物の深度フィルタでも使用)
        var sl = SLIDER_STATE[currentView] || { lower: 0, upper: 1 };

        // Heatmap
        if (filters.heatmap) {
            var grid = GRID_DATA[currentView];
            if (grid) {
                HeatmapRenderer.drawGrid(
                    mainCtx, grid,
                    offX, offY,
                    drawW, drawH,
                    sl.lower, sl.upper,
                    currentFreq,
                    currentColorMap,
                    heatmapOpacity,
                    contrastEnhance
                );

            } else {
                HeatmapRenderer.drawLegacy(mainCtx, vd, vd.pipes, vd.foreign, offX, offY, scale, currentFreq);
            }
        }

        // Infrastructure
        if (filters.infra) {
            FloorRenderer.drawInfrastructure(mainCtx, vd.pipes, tx, ty, sl.lower, sl.upper);
        }

        // Foreign objects
        if (filters.foreign) {
            FloorRenderer.drawForeignObjects(mainCtx, vd.foreign, tx, ty, scale, sl.lower, sl.upper);
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

    /** Confirm manual room dimensions */
    function confirmRoom() {
        var w = parseFloat(document.getElementById('inputW').value);
        var d = parseFloat(document.getElementById('inputD').value);
        var h = parseFloat(document.getElementById('inputH').value);

        if (!w || !d || !h || w < 1 || d < 1 || h < 1) {
            alert('幅・奥行・天井高をすべて正の数で入力してください（1m以上）');
            return;
        }

        manualRoom.w = w; manualRoom.d = d; manualRoom.h = h;
        roomConfirmed = true;

        document.getElementById('roomInputWarn').classList.add('hidden');
        document.getElementById('roomConfirmed').classList.remove('hidden');
        document.getElementById('roomConfirmedText').textContent = w + 'm × ' + d + 'm × ' + h + 'm';
        document.getElementById('inputW').readOnly = true;
        document.getElementById('inputD').readOnly = true;
        document.getElementById('inputH').readOnly = true;
        document.getElementById('btnConfirmRoom').disabled = true;
        document.getElementById('btnConfirmRoom').textContent = '確定済み';

        ROOM.w = w; ROOM.d = d; ROOM.h = h;
        VIEW_DATA.floor.w = w; VIEW_DATA.floor.h = d;
        VIEW_DATA.ceiling.w = w; VIEW_DATA.ceiling.h = d;
        VIEW_DATA.north.w = w; VIEW_DATA.north.h = h;
        VIEW_DATA.south.w = w; VIEW_DATA.south.h = h;
        VIEW_DATA.east.w = d; VIEW_DATA.east.h = h;
        VIEW_DATA.west.w = d; VIEW_DATA.west.h = h;

        addLog('部屋寸法確定: ' + w + 'm × ' + d + 'm × ' + h + 'm', 'log-info');
        render();
    }

    function isRoomReady() { return roomConfirmed; }

    /** Build result */
    async function buildResult() {
        addLog('=== 3D化処理開始 ===', 'log-info');
        var btn = document.getElementById('btnBuild');
        btn.disabled = true;
        btn.textContent = '処理中...';

        try {
            var url = API + '/build';
            if (roomConfirmed && manualRoom.w > 0) {
                var params = new URLSearchParams({
                    manual_width: manualRoom.w,
                    manual_depth: manualRoom.d,
                    manual_height: manualRoom.h,
                });
                url = API + '/build?' + params;
            } else {
                // 部屋寸法未入力の場合、サーバーから既存の部屋寸法を取得して使用
                try {
                    var roomResp = await fetch(API + '/result/room');
                    if (roomResp.ok) {
                        var roomData = await roomResp.json();
                        if (roomData.width && roomData.depth && roomData.height) {
                            var params = new URLSearchParams({
                                manual_width: roomData.width,
                                manual_depth: roomData.depth,
                                manual_height: roomData.height,
                            });
                            url = API + '/build?' + params;
                            addLog('  サーバー既存寸法を使用: ' + roomData.width + '×' + roomData.depth + '×' + roomData.height + 'm', 'log-info');
                        }
                    }
                } catch (e) { /* 取得失敗時はパラメータなしで続行 */ }
            }


            var resp = await fetch(url, { method: 'POST' });
            if (resp.ok) {
                var data = await resp.json();
                applyBuildResult(data);
                addLog('  サーバー応答: 3D化完了', 'log-info');
                addLog('  反射マップ取得開始...', 'log-info');
                try {
                    var faces = ['floor', 'ceiling', 'north', 'south', 'east', 'west'];

                    var bandParam;
                    if (diffCutEnabled) {
                        bandParam = 'diff';
                    } else {
                        bandParam = currentFreq === '24' ? '24' : currentFreq === '5' ? '5' : currentFreq === '160' ? '160' : 'mix';
                    }

                    var loaded = 0;
                    for (var i = 0; i < faces.length; i++) {
                        var face = faces[i];
                        var mapResp = await fetch(API + '/result/map/' + face + '/' + bandParam);
                        if (mapResp.ok) {
                            var mapData = await mapResp.json();
                            GRID_DATA[face] = mapData.grid;
                            loaded++;
                        } else {
                            addLog('  Grid取得失敗: ' + face, 'log-warn');
                            GRID_DATA[face] = null;
                        }
                    }
                    addLog('  反射マップ取得: ' + loaded + '/6面', loaded === 6 ? 'log-info' : 'log-warn');
                    if (three3dInitialized) { _update3DTextures(); }
                } catch (gridErr) {
                    addLog('  Grid取得エラー: ' + gridErr.message, 'log-warn');
                }
                render();
                addLog('=== 3D化完了 ===', 'log-info');
            } else {
                var errText = await resp.text();
                addLog('  サーバーエラー (' + resp.status + '): ' + errText, 'log-warn');
                await simulateBuild();
            }
        } catch (e) {
            addLog('  API接続失敗: ' + e.message, 'log-warn');
            await simulateBuild();
        } finally {
            btn.disabled = false;
            btn.textContent = 'スキャン結果を 3D 化';
        }
    }


    async function _fetchGridForCurrentView() {
        var bandParam;
        if (diffCutEnabled) {
            bandParam = 'diff';
        } else {
            bandParam = currentFreq === '24' ? '24' : currentFreq === '5' ? '5' : currentFreq === '160' ? '160' : 'mix';
        }

        try {
            var resp = await fetch(API + '/result/map/' + currentView + '/' + bandParam);
            if (resp.ok) {
                var data = await resp.json();
                GRID_DATA[currentView] = data.grid;
                render();
            }
        } catch (e) { /* 取得失敗時は既存データを維持 */ }
    }


    async function simulateBuild() {
        var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

        addLog('  ローカルシミュレーションで3D化...', 'log-info');
        await sleep(500);

        var simPipes = {
            floor: [
                { x1: 1, y1: 2.5, x2: 5.5, y2: 2.5, type: 'metal', label: '金属管', dispConf: .92, detail: '' },
                { x1: 3, y1: 1, x2: 3, y2: 4.5, type: 'wire', label: '電気配線', dispConf: .78, detail: '' },
                { x1: 5.5, y1: 1, x2: 5.5, y2: 3.8, type: 'pvc', label: '塩ビ管', dispConf: .55, detail: '' },
            ],
            ceiling: [
                { x1: 1.5, y1: 1, x2: 6, y2: 1, type: 'metal', label: '金属管', dispConf: .87, detail: '' },
                { x1: 3.5, y1: 0.5, x2: 3.5, y2: 4.8, type: 'wire', label: '電気配線', dispConf: .74, detail: '' },
            ],
            north: [
                { x1: 2, y1: 0.5, x2: 2, y2: 2.2, type: 'metal', label: '金属管', dispConf: .90, detail: '' },
                { x1: 4, y1: 1, x2: 5.5, y2: 1, type: 'wire', label: '電気配線', dispConf: .65, detail: '' },
            ],
            south: [{ x1: 1, y1: 1, x2: 6, y2: 1, type: 'metal', label: '金属管', dispConf: .88, detail: '' }],
            east: [
                { x1: 1, y1: 0.5, x2: 1, y2: 2.3, type: 'pvc', label: '塩ビ管', dispConf: .52, detail: '' },
                { x1: 3, y1: .8, x2: 3, y2: 2, type: 'stud', label: '間柱', dispConf: .71, detail: '' },
            ],
            west: [{ x1: 2, y1: 0.3, x2: 2, y2: 2.5, type: 'stud', label: '間柱', dispConf: .68, detail: '' }],
        };

        var simForeign = {
            floor: [{ x: 5.8, y: 1.2, r: .15, label: '不審デバイス', dispConf: .76, detail: '壁内 深さ≈5cm / 2.4GHz微弱電波源' }],
            ceiling: [], north: [], south: [], east: [], west: []
        };

        var totalPipes = 0, totalForeign = 0;
        for (var f in VIEW_DATA) {
            VIEW_DATA[f].pipes = simPipes[f] || [];
            VIEW_DATA[f].foreign = simForeign[f] || [];
            totalPipes += VIEW_DATA[f].pipes.length;
            totalForeign += VIEW_DATA[f].foreign.length;
        }

        ROOM.w = 7.2; ROOM.d = 5.4; ROOM.h = 2.7;
        scanned = true;
        var _pdfBtn = document.getElementById('btnExportPDF');
        var _csvBtn = document.getElementById('btnExportCSV');
        if (_pdfBtn) _pdfBtn.disabled = false;
        if (_csvBtn) _csvBtn.disabled = false;
        updateInfoPanel(totalPipes, totalForeign);
        updateForeignAlert();
        render();
        // 3Dビュー用: ルーム構築
        if (three3dInitialized) {
            Room3DView.buildRoom(ROOM);
            _update3DTextures();
        }
        addLog('=== 3D化完了 (シミュレーション) ===', 'log-info');
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

        var typeMap = { metal: 'metal', wire: 'wire', pvc: 'pvc', stud: 'stud' };
        var labelMap = { metal: '金属管', wire: '電気配線', pvc: '塩ビ管', stud: '間柱' };
        for (var f in VIEW_DATA) { VIEW_DATA[f].pipes = []; VIEW_DATA[f].foreign = []; }

        if (data.structures) {
            for (var i = 0; i < data.structures.length; i++) {
                var s = data.structures[i];
                if (VIEW_DATA[s.face]) {
                    VIEW_DATA[s.face].pipes.push({
                        x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2,
                        type: typeMap[s.material] || 'metal',
                        label: labelMap[s.material] || s.label,
                        dispConf: s.confidence, detail: ''
                    });
                }
            }
        }

        if (data.foreign) {
            for (var j = 0; j < data.foreign.length; j++) {
                var fo = data.foreign[j];
                var face = fo.face || 'floor';
                if (VIEW_DATA[face]) {
                    VIEW_DATA[face].foreign.push({
                        x: fo.x, y: fo.y, r: fo.radius || 0.15,
                        label: fo.label || '不審デバイス',
                        dispConf: fo.confidence, detail: fo.detail || ''
                    });
                }
            }
        }

        var totalPipes = 0, totalForeign = 0;
        for (var f in VIEW_DATA) {
            totalPipes += VIEW_DATA[f].pipes.length;
            totalForeign += VIEW_DATA[f].foreign.length;
        }

        scanned = true;
        var _pdfBtn = document.getElementById('btnExportPDF');
        var _csvBtn = document.getElementById('btnExportCSV');
        if (_pdfBtn) _pdfBtn.disabled = false;
        if (_csvBtn) _csvBtn.disabled = false;
        updateInfoPanel(totalPipes, totalForeign);
        updateForeignAlert();
        updateBadges();
        render();

        // 3Dビュー用: ルーム構築
        if (three3dInitialized) {
            Room3DView.buildRoom(ROOM);
            _update3DTextures();
        }
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
        var alertEl = document.getElementById('foreignAlert');
        var listEl = document.getElementById('foreignList');
        var faceNames = { floor: '床下', ceiling: '天井裏', north: '北壁内', south: '南壁内', east: '東壁内', west: '西壁内' };
        var threatColors = { high: '#ff1744', medium: '#ff9100', low: '#ffd600', none: '#66bb6a' };
        var threatLabels = { high: '危険', medium: '警戒', low: '注意', none: '安全' };
        var methodLabels = { rf: 'RF検出', csi: 'CSI残差', both: 'RF+CSI統合', unknown: '不明' };

        var allForeign = [];
        for (var f in VIEW_DATA) {
            for (var i = 0; i < VIEW_DATA[f].foreign.length; i++) {
                var fo = VIEW_DATA[f].foreign[i];
                allForeign.push({
                    x: fo.x, y: fo.y, label: fo.label, detail: fo.detail, face: f,
                    threat_level: fo.threat_level || 'medium',
                    detection_method: fo.detection_method || 'unknown',
                    dispConf: fo.dispConf || 0
                });
            }
        }

        // 脅威レベルでソート (high → medium → low → none)
        var threatOrder = { high: 0, medium: 1, low: 2, none: 3 };
        allForeign.sort(function (a, b) {
            return (threatOrder[a.threat_level] || 2) - (threatOrder[b.threat_level] || 2);
        });

        if (allForeign.length > 0) {
            alertEl.classList.add('show');
            listEl.innerHTML = allForeign.map(function (fo) {
                var tc = threatColors[fo.threat_level] || '#ff9100';
                var tl = threatLabels[fo.threat_level] || '警戒';
                var ml = methodLabels[fo.detection_method] || '不明';
                return '<div class="foreign-item" style="border-left:3px solid ' + tc + ';padding:4px 8px;margin:3px 0;background:rgba(0,0,0,0.2);border-radius:4px">' +
                    '<div style="display:flex;justify-content:space-between;align-items:center">' +
                    '<span style="color:' + tc + ';font-weight:bold;font-size:11px">⚠ ' + tl + '</span>' +
                    '<span style="font-size:8px;color:#888;background:rgba(255,255,255,0.05);padding:1px 5px;border-radius:3px">' + ml + '</span>' +
                    '</div>' +
                    '<div style="font-size:10px;color:#ddd;margin-top:2px">' +
                    (faceNames[fo.face] || fo.face) + ' (' + fo.x.toFixed(1) + ', ' + fo.y.toFixed(1) + ')m — ' + fo.label +
                    '</div>' +
                    '<div style="font-size:8px;color:#888;margin-top:1px">' +
                    '信頼度: ' + (fo.dispConf * 100).toFixed(0) + '% | ' + fo.detail +
                    '</div>' +
                    '</div>';
            }).join('');
            AudioAlert.playAlert();

            // 脅威レベル別カウントをログに表示
            var highCount = allForeign.filter(function (f) { return f.threat_level === 'high' }).length;
            var medCount = allForeign.filter(function (f) { return f.threat_level === 'medium' }).length;
            addLog('★★★ 異物検出アラート: ' + allForeign.length + '個 (危険:' + highCount + ' / 警戒:' + medCount + ') ★★★', 'log-foreign');
        } else {
            alertEl.classList.remove('show');
        }
    }

    function updateBadges() {
        for (var f in VIEW_DATA) {
            var badge = document.getElementById('badge-' + f);
            if (badge) {
                var count = VIEW_DATA[f].foreign.length;
                if (count > 0) { badge.textContent = count; badge.classList.remove('hidden'); }
                else { badge.classList.add('hidden'); }
            }
        }
    }

    /** Foreign modal */
    function openForeignModal() {
        var modal = document.getElementById('foreignModal');
        var body = document.getElementById('foreignModalBody');
        var faceNames = { floor: '床下', ceiling: '天井裏', north: '北壁内', south: '南壁内', east: '東壁内', west: '西壁内' };
        var threatColors = { high: '#ff1744', medium: '#ff9100', low: '#ffd600' };
        var threatLabels = { high: '危険', medium: '警戒', low: '注意' };
        var methodLabels = { rf: 'RF検出', csi: 'CSI残差検出', both: 'RF+CSI統合検出', unknown: '不明' };

        var allForeign = [];
        for (var f in VIEW_DATA) {
            for (var i = 0; i < VIEW_DATA[f].foreign.length; i++) {
                var fo = VIEW_DATA[f].foreign[i];
                allForeign.push({
                    x: fo.x, y: fo.y, r: fo.r, label: fo.label, detail: fo.detail, face: f,
                    threat_level: fo.threat_level || 'medium',
                    detection_method: fo.detection_method || 'unknown',
                    dispConf: fo.dispConf || 0
                });
            }
        }

        var threatOrder = { high: 0, medium: 1, low: 2, none: 3 };
        allForeign.sort(function (a, b) { return (threatOrder[a.threat_level] || 2) - (threatOrder[b.threat_level] || 2); });

        if (allForeign.length === 0) {
            body.innerHTML = '<div style="text-align:center;color:#6a7a8a;padding:40px;font-size:14px">不審デバイスは検出されていません</div>';
            modal.classList.remove('hidden');
            return;
        }

        // サマリー
        var highC = allForeign.filter(function (f) { return f.threat_level === 'high' }).length;
        var medC = allForeign.filter(function (f) { return f.threat_level === 'medium' }).length;
        var lowC = allForeign.filter(function (f) { return f.threat_level === 'low' }).length;

        var html = '<div class="fm-summary">';
        html += '<div class="fm-summary-item"><strong style="color:#eee;font-size:14px">' + allForeign.length + ' 件検出</strong></div>';
        if (highC > 0) html += '<div class="fm-summary-item"><span class="fm-summary-dot" style="background:#ff1744"></span>危険 ' + highC + '</div>';
        if (medC > 0) html += '<div class="fm-summary-item"><span class="fm-summary-dot" style="background:#ff9100"></span>警戒 ' + medC + '</div>';
        if (lowC > 0) html += '<div class="fm-summary-item"><span class="fm-summary-dot" style="background:#ffd600"></span>注意 ' + lowC + '</div>';
        html += '</div>';

        for (var j = 0; j < allForeign.length; j++) {
            var fo = allForeign[j];
            var tl = fo.threat_level || 'medium';
            var tc = threatColors[tl] || '#ff9100';
            var tlLabel = threatLabels[tl] || '警戒';
            var ml = methodLabels[fo.detection_method] || '不明';
            var faceName = faceNames[fo.face] || fo.face;

            html += '<div class="fm-item threat-' + tl + '">';
            html += '<div class="fm-item-header">';
            html += '<span class="fm-threat-badge ' + tl + '">' + tlLabel + '</span>';
            html += '<span class="fm-method-badge">' + ml + '</span>';
            html += '</div>';
            html += '<div class="fm-label">' + fo.label + '</div>';
            html += '<div class="fm-location">📍 ' + faceName + ' (' + fo.x.toFixed(2) + ', ' + fo.y.toFixed(2) + ')m';
            if (fo.r > 0) html += ' / 推定サイズ: ' + (fo.r * 100).toFixed(0) + 'cm';
            html += '</div>';
            html += '<div class="fm-detail">' + fo.detail + '</div>';
            html += '<span class="fm-confidence">信頼度: ' + (fo.dispConf * 100).toFixed(0) + '%</span>';
            html += '</div>';
        }

        body.innerHTML = html;
        modal.classList.remove('hidden');
    }

    function closeForeignModal() {
        document.getElementById('foreignModal').classList.add('hidden');
    }

    /** Reset */
    function resetAll() {
        scanned = false;
        for (var f in VIEW_DATA) {
            VIEW_DATA[f].pipes = []; VIEW_DATA[f].foreign = [];
            GRID_DATA[f] = null;
            SLIDER_STATE[f] = { lower: 0, upper: 1 };
        }
        heatmapOpacity = 1.0;
        document.getElementById('sliderOpacity').value = 100;
        document.getElementById('sliderOpacityVal').textContent = '100%';
        _restoreSliderState();

        document.getElementById('foreignAlert').classList.remove('show');
        document.querySelectorAll('.tab-btn .badge').forEach(function (b) { b.classList.add('hidden'); });
        document.getElementById('valW').textContent = '—';
        document.getElementById('valD').textContent = '—';
        document.getElementById('valH').textContent = '—';
        document.getElementById('valArea').textContent = '—';
        document.getElementById('valPipes').textContent = '—';
        document.getElementById('valForeign').textContent = '—';

        roomConfirmed = false;
        manualRoom.w = 0; manualRoom.d = 0; manualRoom.h = 0;
        document.getElementById('roomInputWarn').classList.remove('hidden');
        document.getElementById('roomConfirmed').classList.add('hidden');
        document.getElementById('inputW').readOnly = false;
        document.getElementById('inputD').readOnly = false;
        document.getElementById('inputH').readOnly = false;
        document.getElementById('inputW').value = '';
        document.getElementById('inputD').value = '';
        document.getElementById('inputH').value = '';
        document.getElementById('btnConfirmRoom').disabled = false;
        document.getElementById('btnConfirmRoom').textContent = '寸法を確定';

        document.getElementById('hoverTooltip').classList.add('hidden');

        // 3Dリセット
        if (three3dInitialized) {
            Room3DView.buildRoom(ROOM);
        }
        is3DMode = false;
        document.getElementById('mainCanvas').style.display = 'block';
        document.getElementById('three3dContainer').style.display = 'none';
        Room3DView.stopAnimation();

        ScanControl.resetPoints();
        render();
        addLog('=== セッションリセット ===', 'log-warn');
        fetch(API + '/reset', { method: 'POST' }).catch(function () { });
    }

    /** Log */
    function addLog(msg, cls) {
        var el = document.getElementById('logArea');
        var ts = new Date().toLocaleTimeString();
        var span = document.createElement('div');
        span.className = cls || '';
        span.textContent = '[' + ts + '] ' + msg;
        el.appendChild(span);
        el.scrollTop = el.scrollHeight;
    }

    window.addEventListener('DOMContentLoaded', init);

    /** PDF export */
    function exportPDF() {
        ReportExport.exportPDF(ROOM, VIEW_DATA, GRID_DATA, scanned, {
            freq: currentFreq,
            diffCut: diffCutEnabled,
            contrastEnhance: contrastEnhance,
            colorMap: currentColorMap
        });
    }

    /** CSV export */
    function exportCSV() {
        ReportExport.exportCSV(ROOM, VIEW_DATA, GRID_DATA, scanned, {
            freq: currentFreq,
            diffCut: diffCutEnabled,
            contrastEnhance: contrastEnhance,
            colorMap: currentColorMap
        });
    }
    /** F-0l: システムステータスを取得してログに表示 */
    function _fetchSystemStatus() {
        fetch('/api/system/status')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var mode = d.simulation_mode ? 'シミュレーション' : '実機スキャン';
                var src = d.csi_source || 'unknown';
                var nic = d.nic_detected ? d.nic_name : '未検出';
                var feit = d.feitcsi_available ? '利用可能' : '未利用';
                var mon = d.monitor_active ? 'ON' : 'OFF';

                addLog('--- システムステータス ---', 'log-info');
                addLog('モード: ' + mode + ' | CSIソース: ' + src, 'log-info');
                addLog('NIC: ' + nic + ' | FeitCSI: ' + feit + ' | Monitor: ' + mon, 'log-info');
                addLog('OS: ' + (d.os_info || '-') + ' | Kernel: ' + (d.kernel || '-'), 'log-info');

                if (d.message) {
                    addLog(d.message, d.boot_success ? 'log-info' : 'log-error');
                }
                addLog('----------------------------', 'log-info');
            })
            .catch(function (e) {
                addLog('システムステータス取得失敗: ' + e, 'log-error');
            });
    }

    return {
        switchView: switchView, toggleFilter: toggleFilter, switchFreq: switchFreq,
        exportPDF: exportPDF, exportCSV: exportCSV,
        switchColorMap: switchColorMap, toggleDiffCut: toggleDiffCut, toggleContrastEnhance: toggleContrastEnhance,
        buildResult: buildResult, resetAll: resetAll,
        addLog: addLog, render: render, confirmRoom: confirmRoom, isRoomReady: isRoomReady,
        onSliderChange: onSliderChange, onOpacityChange: onOpacityChange, applyPreset: applyPreset,
        openForeignModal: openForeignModal, closeForeignModal: closeForeignModal
    };
})();











