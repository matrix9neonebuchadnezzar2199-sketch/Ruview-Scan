/**
 * RuView Scan - WebSocket クライアント
 */
const RuViewWS = (function() {
    let ws = null;
    let reconnectTimer = null;
    const listeners = [];

    function connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/ws/scan`;
        
        try {
            ws = new WebSocket(url);
        } catch(e) {
            console.warn('WebSocket接続失敗:', e);
            scheduleReconnect();
            return;
        }

        ws.onopen = function() {
            console.log('WebSocket connected');
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                listeners.forEach(fn => fn(data));
            } catch(e) {
                console.error('WS parse error:', e);
            }
        };

        ws.onclose = function() {
            console.log('WebSocket disconnected');
            scheduleReconnect();
        };

        ws.onerror = function(err) {
            console.warn('WebSocket error:', err);
        };
    }

    function scheduleReconnect() {
        if (!reconnectTimer) {
            reconnectTimer = setTimeout(connect, 3000);
        }
    }

    function send(data) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(data));
        }
    }

    function onMessage(fn) {
        listeners.push(fn);
    }

    // Auto-connect
    connect();

    return { connect, send, onMessage };
})();
