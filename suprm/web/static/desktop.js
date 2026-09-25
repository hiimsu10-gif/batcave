/* Suprm OS desktop: draggable windows, Suprm FM (a tiny in-browser synth), split calculator. */
(function () {
  // ---- draggable windows (wide screens only) ----
  var wide = window.matchMedia("(min-width: 900px)");
  var z = 10;
  document.querySelectorAll("[data-drag]").forEach(function (win) {
    var bar = win.querySelector(".titlebar");
    win.addEventListener("pointerdown", function () { win.style.zIndex = ++z; });
    bar.addEventListener("pointerdown", function (e) {
      if (!wide.matches || e.target.closest("button")) return;
      var startX = e.clientX, startY = e.clientY;
      var left = win.offsetLeft, top = win.offsetTop;
      bar.setPointerCapture(e.pointerId);
      function move(ev) {
        win.style.left = Math.max(0, left + ev.clientX - startX) + "px";
        win.style.top = Math.max(0, top + ev.clientY - startY) + "px";
      }
      function up() { bar.removeEventListener("pointermove", move); bar.removeEventListener("pointerup", up); }
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
    });
  });

  // ---- split calculator ----
  var calc = document.getElementById("split-calc");
  if (calc) {
    var fmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
    function render() {
      var gross = parseFloat(calc.querySelector("#calc-gross").value) || 0;
      var rows = calc.querySelectorAll("[data-split]");
      var total = 0;
      rows.forEach(function (r) {
        var pct = parseFloat(r.querySelector("input").value) || 0;
        total += pct;
        r.querySelector("output").textContent = fmt.format(gross * pct / 100);
      });
      var t = calc.querySelector("#calc-total");
      t.textContent = total.toFixed(2).replace(/\.00$/, "") + "%";
      t.className = Math.abs(total - 100) < 0.001 ? "ok" : "bad";
    }
    calc.addEventListener("input", render);
    render();
  }

  // ---- Suprm FM ----
  var fm = document.getElementById("suprm-fm");
  if (!fm) return;
  var stations = [
    { name: "Pool Party FM", bpm: 96, root: 53, chords: [[0, 4, 7, 11], [-3, 0, 4, 7], [2, 5, 9, 12], [-5, -1, 2, 5]] },
    { name: "Night Swim", bpm: 78, root: 50, chords: [[0, 3, 7, 10], [-4, 0, 3, 7], [-2, 2, 5, 9], [-5, -2, 2, 5]] },
    { name: "Studio Session", bpm: 108, root: 55, chords: [[0, 4, 7, 9], [5, 9, 12, 16], [2, 5, 9, 12], [7, 11, 14, 17]] }
  ];
  var ctx = null, master = null, timer = null, step = 0, current = 0, playing = false;
  var label = fm.querySelector("[data-station]"), playBtn = fm.querySelector("[data-play]");
  var bars = fm.querySelectorAll(".eq i");
  function hz(m) { return 440 * Math.pow(2, (m - 69) / 12); }
  function voice(freq, t, len, type, gain, cutoff) {
    var o = ctx.createOscillator(), g = ctx.createGain(), f = ctx.createBiquadFilter();
    o.type = type; o.frequency.value = freq; f.type = "lowpass"; f.frequency.value = cutoff;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.04);
    g.gain.exponentialRampToValueAtTime(0.0001, t + len);
    o.connect(f); f.connect(g); g.connect(master); o.start(t); o.stop(t + len + 0.05);
  }
  function hat(t) {
    var len = 0.05, buf = ctx.createBuffer(1, ctx.sampleRate * len, ctx.sampleRate), d = buf.getChannelData(0);
    for (var i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    var s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = buf; f.type = "highpass"; f.frequency.value = 7000; g.gain.value = 0.05;
    s.connect(f); f.connect(g); g.connect(master); s.start(t);
  }
  function kick(t) {
    var o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.setValueAtTime(120, t); o.frequency.exponentialRampToValueAtTime(40, t + 0.18);
    g.gain.setValueAtTime(0.5, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(g); g.connect(master); o.start(t); o.stop(t + 0.3);
  }
  function tick() {
    var st = stations[current], beat = 60 / st.bpm / 2, t = ctx.currentTime + 0.05;
    var chord = st.chords[Math.floor(step / 8) % st.chords.length];
    if (step % 8 === 0) chord.forEach(function (n) { voice(hz(st.root + n), t, beat * 8, "triangle", 0.06, 1800); });
    if (step % 4 === 0) kick(t);
    if (step % 2 === 1) hat(t);
    if (step % 2 === 0) voice(hz(st.root - 12 + chord[step % 4 === 0 ? 0 : 2]), t, beat * 1.6, "sine", 0.18, 600);
    if (Math.random() < 0.35) voice(hz(st.root + 12 + chord[Math.floor(Math.random() * 4)]), t, beat * 1.2, "square", 0.025, 2600);
    bars.forEach(function (b) { b.style.height = (20 + Math.random() * 80) + "%"; });
    step++;
  }
  function start() {
    if (!ctx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) { label.textContent = "No audio in this browser"; return; }
      ctx = new AC(); master = ctx.createGain(); master.gain.value = 0.7; master.connect(ctx.destination);
    }
    ctx.resume();
    clearInterval(timer);
    timer = setInterval(tick, 60000 / stations[current].bpm / 2);
    playing = true; fm.classList.add("on"); playBtn.textContent = "Pause"; playBtn.setAttribute("aria-pressed", "true");
  }
  function stop() {
    clearInterval(timer); playing = false; fm.classList.remove("on");
    playBtn.textContent = "Play"; playBtn.setAttribute("aria-pressed", "false");
  }
  function tune(dir) {
    current = (current + dir + stations.length) % stations.length; step = 0;
    label.textContent = stations[current].name + " · " + stations[current].bpm + " BPM";
    if (playing) start();
  }
  playBtn.addEventListener("click", function () { playing ? stop() : start(); });
  fm.querySelector("[data-next]").addEventListener("click", function () { tune(1); });
  fm.querySelector("[data-prev]").addEventListener("click", function () { tune(-1); });
  tune(0);
})();
