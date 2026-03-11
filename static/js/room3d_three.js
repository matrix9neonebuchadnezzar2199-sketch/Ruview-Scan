/**
 * RuView Scan - Three.js 3Dルームビューア (Phase E)
 * 6面ヒートマップをBOX内面にテクスチャとして貼付
 * スライダー・カラーマップ・不透明度と連動
 */
const Room3DView = (function() {
    let scene, camera, renderer, controls;
    let roomGroup = null;
    let faceMeshes = {};
    let faceTextures = {};
    let containerEl = null;
    let animFrameId = null;
    let isActive = false;
    let currentRoom = { w: 7.2, d: 5.4, h: 2.7 };

    // カラーマップ定義 (heatmap_renderer.js と同じ)
    const COLORMAPS = {
        thermal: [
            [0.0, 0,0,40], [0.2, 30,0,120], [0.4, 120,0,180],
            [0.6, 200,0,100], [0.8, 255,80,0], [1.0, 255,200,50]
        ],
        heat: [
            [0.0, 0,0,0], [0.25, 150,0,0], [0.5, 255,80,0],
            [0.75, 255,220,50], [1.0, 255,255,255]
        ],
        cool: [
            [0.0, 0,0,0], [0.25, 0,0,150], [0.5, 0,100,220],
            [0.75, 0,220,255], [1.0, 255,255,255]
        ],
        grayscale: [
            [0.0, 0,0,0], [0.5, 128,128,128], [1.0, 255,255,255]
        ],
        rainbow: [
            [0.0, 0,0,128], [0.17, 0,0,255], [0.33, 0,255,255],
            [0.5, 0,255,0], [0.67, 255,255,0], [0.83, 255,128,0], [1.0, 255,0,0]
        ]
    };

    function init(containerId) {
        containerEl = document.getElementById(containerId);
        if (!containerEl) return;

        var w = containerEl.clientWidth;
        var h = containerEl.clientHeight;

        // シーン
        scene = new THREE.Scene();
        scene.background = new THREE.Color(0x060c18);

        // カメラ
        camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 100);
        camera.position.set(10, 8, 10);
        camera.lookAt(0, 0, 0);

        // レンダラー
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        renderer.setSize(w, h);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        containerEl.appendChild(renderer.domElement);

        // OrbitControls
        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.minDistance = 3;
        controls.maxDistance = 30;
        controls.target.set(0, 0, 0);

        // ライティング
        var ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        scene.add(ambientLight);
        var dirLight = new THREE.DirectionalLight(0xffffff, 0.4);
        dirLight.position.set(5, 10, 5);
        scene.add(dirLight);

        // グリッドヘルパー
        var gridHelper = new THREE.GridHelper(20, 20, 0x1a2a3a, 0x0a1520);
        gridHelper.position.y = -0.01;
        scene.add(gridHelper);

        // リサイズ対応
        window.addEventListener("resize", onResize);
    }

    function onResize() {
        if (!containerEl || !camera || !renderer) return;
        var w = containerEl.clientWidth;
        var h = containerEl.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
    }

    function buildRoom(room) {
        currentRoom = { w: room.w || 7.2, d: room.d || 5.4, h: room.h || 2.7 };

        // 既存のルームグループを削除
        if (roomGroup) {
            scene.remove(roomGroup);
            roomGroup = null;
            faceMeshes = {};
            faceTextures = {};
        }

        roomGroup = new THREE.Group();
        var w = currentRoom.w;
        var d = currentRoom.d;
        var h = currentRoom.h;

        // 各面を個別のPlaneで構築 (内側向き)
        var faces = {
            floor:   { size: [w, d], pos: [0, 0, 0],       rot: [-Math.PI/2, 0, 0] },
            ceiling: { size: [w, d], pos: [0, h, 0],       rot: [Math.PI/2, 0, 0] },
            north:   { size: [w, h], pos: [0, h/2, -d/2],  rot: [0, 0, 0] },
            south:   { size: [w, h], pos: [0, h/2, d/2],   rot: [0, Math.PI, 0] },
            east:    { size: [d, h], pos: [w/2, h/2, 0],   rot: [0, -Math.PI/2, 0] },
            west:    { size: [d, h], pos: [-w/2, h/2, 0],  rot: [0, Math.PI/2, 0] }
        };

        for (var faceName in faces) {
            var f = faces[faceName];
            var geo = new THREE.PlaneGeometry(f.size[0], f.size[1]);
            var mat = new THREE.MeshBasicMaterial({
                color: 0x0a1a2a,
                side: THREE.DoubleSide,
                transparent: true,
                opacity: 0.3
            });
            var mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(f.pos[0], f.pos[1], f.pos[2]);
            mesh.rotation.set(f.rot[0], f.rot[1], f.rot[2]);
            mesh.name = faceName;
            faceMeshes[faceName] = mesh;
            roomGroup.add(mesh);
        }

        // ワイヤーフレームのエッジ
        var edgeGeo = new THREE.BoxGeometry(w, h, d);
        var edgeMat = new THREE.LineBasicMaterial({ color: 0x4fc3f7, linewidth: 1 });
        var edges = new THREE.LineSegments(new THREE.EdgesGeometry(edgeGeo), edgeMat);
        edges.position.set(0, h/2, 0);
        roomGroup.add(edges);

        // 方角ラベル (スプライト)
        var directions = [
            { label: '北 (N)', pos: [0, h/2, -d/2 - 0.8] },
            { label: '南 (S)', pos: [0, h/2, d/2 + 0.8] },
            { label: '東 (E)', pos: [w/2 + 0.8, h/2, 0] },
            { label: '西 (W)', pos: [-w/2 - 0.8, h/2, 0] }
        ];
        for (var di = 0; di < directions.length; di++) {
            var dir = directions[di];
            var sprite = _createTextSprite(dir.label, '#4fc3f7', 64);
            sprite.position.set(dir.pos[0], dir.pos[1], dir.pos[2]);
            sprite.scale.set(1.5, 0.75, 1);
            roomGroup.add(sprite);
        }

        // 床面の測定ポイント表示
        var measurePoints = [
            { label: 'TX', x: 0, z: 0, color: 0xffa726, size: 0.15 },
            { label: 'pos.1', x: 0, z: -d/2 + 1.0, color: 0x66bb6a, size: 0.08 },
            { label: 'pos.2', x: w/2 - 1.0, z: 0, color: 0x66bb6a, size: 0.08 },
            { label: 'pos.3', x: 0, z: d/2 - 1.0, color: 0x66bb6a, size: 0.08 },
            { label: 'pos.4', x: -w/2 + 1.0, z: 0, color: 0x66bb6a, size: 0.08 },
            { label: 'pos.5', x: 0, z: 0, color: 0x66bb6a, size: 0.08 },
            { label: 'pos.6', x: w/2 - 1.0, z: -d/2 + 1.0, color: 0x4fc3f7, size: 0.08 },
            { label: 'pos.7', x: w/2 - 1.0, z: d/2 - 1.0, color: 0x4fc3f7, size: 0.08 },
            { label: 'pos.8', x: -w/2 + 1.0, z: d/2 - 1.0, color: 0x4fc3f7, size: 0.08 },
            { label: 'pos.9', x: -w/2 + 1.0, z: -d/2 + 1.0, color: 0x4fc3f7, size: 0.08 }
        ];
        for (var pi = 0; pi < measurePoints.length; pi++) {
            var mp = measurePoints[pi];
            var sphereGeo = new THREE.SphereGeometry(mp.size, 12, 12);
            var sphereMat = new THREE.MeshBasicMaterial({ color: mp.color });
            var sphere = new THREE.Mesh(sphereGeo, sphereMat);
            sphere.position.set(mp.x, 0.05, mp.z);
            roomGroup.add(sphere);
            var ptSprite = _createTextSprite(mp.label, mp.label === 'TX' ? '#ffa726' : '#aabbcc', 48);
            ptSprite.position.set(mp.x, 0.35, mp.z);
            ptSprite.scale.set(0.8, 0.4, 1);
            roomGroup.add(ptSprite);
        }

        scene.add(roomGroup);

        // カメラ位置をリセット
        var maxDim = Math.max(w, d, h);
        camera.position.set(maxDim * 1.2, maxDim * 0.9, maxDim * 1.2);
        controls.target.set(0, h/2, 0);
        controls.update();
    }

    function updateFaceTexture(faceName, gridData, lower, upper, colorMapId, opacity) {
        if (!gridData || !faceMeshes[faceName]) return;

        var rows = gridData.length;
        var cols = gridData[0].length;

        // オフスクリーンCanvasでテクスチャ生成
        var texCanvas = document.createElement("canvas");
        texCanvas.width = cols;
        texCanvas.height = rows;
        var ctx = texCanvas.getContext("2d");
        var imgData = ctx.createImageData(cols, rows);

        var cmap = COLORMAPS[colorMapId] || COLORMAPS.thermal;

        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var val = gridData[r][c];
                var idx = (r * cols + c) * 4;

                if (val < lower || val > upper) {
                    imgData.data[idx] = 0;
                    imgData.data[idx+1] = 0;
                    imgData.data[idx+2] = 0;
                    imgData.data[idx+3] = 0;
                } else {
                    var norm = (upper > lower) ? (val - lower) / (upper - lower) : 0;
                    var rgb = interpolateColor(cmap, norm);
                    imgData.data[idx] = rgb[0];
                    imgData.data[idx+1] = rgb[1];
                    imgData.data[idx+2] = rgb[2];
                    imgData.data[idx+3] = Math.floor(opacity * 255);
                }
            }
        }

        ctx.putImageData(imgData, 0, 0);

        // テクスチャ更新
        if (faceTextures[faceName]) {
            faceTextures[faceName].dispose();
        }
        var texture = new THREE.CanvasTexture(texCanvas);
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        faceTextures[faceName] = texture;

        var mesh = faceMeshes[faceName];
        mesh.material.dispose();
        mesh.material = new THREE.MeshBasicMaterial({
            map: texture,
            side: THREE.DoubleSide,
            transparent: true,
            opacity: opacity
        });
        mesh.material.needsUpdate = true;
    }

    function interpolateColor(cmap, t) {
        t = Math.max(0, Math.min(1, t));
        for (var i = 0; i < cmap.length - 1; i++) {
            if (t >= cmap[i][0] && t <= cmap[i+1][0]) {
                var range = cmap[i+1][0] - cmap[i][0];
                var local = (range > 0) ? (t - cmap[i][0]) / range : 0;
                return [
                    Math.round(cmap[i][1] + (cmap[i+1][1] - cmap[i][1]) * local),
                    Math.round(cmap[i][2] + (cmap[i+1][2] - cmap[i][2]) * local),
                    Math.round(cmap[i][3] + (cmap[i+1][3] - cmap[i][3]) * local)
                ];
            }
        }
        var last = cmap[cmap.length - 1];
        return [last[1], last[2], last[3]];
    }

    function updateAllFaces(gridDataMap, lower, upper, colorMapId, opacity) {
        var faces = ["floor", "ceiling", "north", "south", "east", "west"];
        for (var i = 0; i < faces.length; i++) {
            var face = faces[i];
            if (gridDataMap[face]) {
                updateFaceTexture(face, gridDataMap[face], lower, upper, colorMapId, opacity);
            }
        }
    }

    function startAnimation() {
        if (isActive) return;
        isActive = true;
        animate();
    }

    function stopAnimation() {
        isActive = false;
        if (animFrameId) {
            cancelAnimationFrame(animFrameId);
            animFrameId = null;
        }
    }

    function animate() {
        if (!isActive) return;
        animFrameId = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
    }

    function resetCamera() {
        var maxDim = Math.max(currentRoom.w, currentRoom.d, currentRoom.h);
        camera.position.set(maxDim * 1.2, maxDim * 0.9, maxDim * 1.2);
        controls.target.set(0, currentRoom.h / 2, 0);
        controls.update();
    }

    function dispose() {
        stopAnimation();
        if (renderer && containerEl) {
            containerEl.removeChild(renderer.domElement);
        }
        for (var f in faceTextures) {
            if (faceTextures[f]) faceTextures[f].dispose();
        }
        if (renderer) renderer.dispose();
        window.removeEventListener("resize", onResize);
    }

    function _createTextSprite(text, color, fontSize) {
        var canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 128;
        var ctx = canvas.getContext('2d');
        ctx.font = 'bold ' + fontSize + 'px Arial';
        ctx.fillStyle = color;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, 128, 64);
        var texture = new THREE.CanvasTexture(canvas);
        texture.minFilter = THREE.LinearFilter;
        var material = new THREE.SpriteMaterial({ map: texture, transparent: true });
        return new THREE.Sprite(material);
    }

    return {
        init: init,
        buildRoom: buildRoom,
        updateFaceTexture: updateFaceTexture,
        updateAllFaces: updateAllFaces,
        startAnimation: startAnimation,
        stopAnimation: stopAnimation,
        resetCamera: resetCamera,
        onResize: onResize,
        dispose: dispose
    };
})();