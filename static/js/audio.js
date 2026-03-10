/**
 * RuView Scan - 異物検出アラート音 (Web Audio API)
 */
const AudioAlert = (function() {
    let audioCtx = null;

    function init() {
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        } catch(e) {
            console.warn('Web Audio API not available');
        }
    }

    function playAlert() {
        if (!audioCtx) init();
        if (!audioCtx) return;

        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);

        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, audioCtx.currentTime);
        osc.frequency.setValueAtTime(660, audioCtx.currentTime + 0.1);
        osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.2);

        gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.4);

        osc.start(audioCtx.currentTime);
        osc.stop(audioCtx.currentTime + 0.4);
    }

    return { init, playAlert };
})();
