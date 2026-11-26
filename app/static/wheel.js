document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("wheel");
  if (!el) return;

  const canvas = document.getElementById("wheel-canvas");
  const spinBtn = document.getElementById("spin-btn");
  const resultEl = document.getElementById("wheel-result");
  const ctx = canvas.getContext("2d");

  const data = JSON.parse(el.dataset.wheel || "[]");
  const spinUrl = el.dataset.spinUrl;
  const csrf = el.dataset.csrf;

  const size = 520;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  ctx.scale(dpr, dpr);

  const cx = size / 2;
  const cy = size / 2;
  const R = size / 2 - 16;

  const palette = [
    "#b5542d", "#2a6f6a", "#c9a227", "#7a4d8f", "#3a6ea5",
    "#a83a52", "#4d7c4f", "#b07c2a", "#5b5f97", "#8f4d3a",
  ];

  const candidates = data;
  const images = {};
  let rotation = 0;
  let spinning = false;

  function initials(name) {
    return name
      .split(/\s+/)
      .map((w) => w[0] || "")
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }

  function loadImages() {
    return Promise.all(
      candidates.map(
        (c) =>
          new Promise((resolve) => {
            if (!c.avatar) return resolve();
            const img = new Image();
            img.onload = () => {
              images[c.id] = img;
              resolve();
            };
            img.onerror = () => resolve();
            img.src = c.avatar;
          })
      )
    );
  }

  function draw() {
    ctx.clearRect(0, 0, size, size);
    const n = candidates.length;

    ctx.save();
    ctx.translate(cx, cy);

    if (n === 0) {
      ctx.beginPath();
      ctx.arc(0, 0, R, 0, 2 * Math.PI);
      ctx.fillStyle = "#efe7d8";
      ctx.fill();
      ctx.fillStyle = "#7a6f63";
      ctx.font = "600 18px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("Inga kandidater i hjulet", 0, 0);
    } else {
      const seg = (2 * Math.PI) / n;
      ctx.rotate(rotation);
      for (let i = 0; i < n; i++) {
        const a0 = i * seg;
        const a1 = a0 + seg;
        const mid = a0 + seg / 2;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, R, a0, a1);
        ctx.closePath();
        ctx.fillStyle = palette[i % palette.length];
        ctx.fill();
        ctx.strokeStyle = "#fffdf8";
        ctx.lineWidth = 2;
        ctx.stroke();

        const ar = R * 0.42;
        ctx.save();
        ctx.rotate(mid);
        const img = images[candidates[i].id];
        if (img) {
          ctx.beginPath();
          ctx.arc(ar, 0, 26, 0, 2 * Math.PI);
          ctx.save();
          ctx.clip();
          const s = Math.max(52 / img.width, 52 / img.height);
          ctx.drawImage(img, ar - (img.width * s) / 2, -(img.height * s) / 2, img.width * s, img.height * s);
          ctx.restore();
          ctx.beginPath();
          ctx.arc(ar, 0, 26, 0, 2 * Math.PI);
          ctx.strokeStyle = "rgba(255,255,255,0.9)";
          ctx.lineWidth = 3;
          ctx.stroke();
        } else {
          ctx.beginPath();
          ctx.arc(ar, 0, 26, 0, 2 * Math.PI);
          ctx.fillStyle = "rgba(255,253,248,0.92)";
          ctx.fill();
          ctx.fillStyle = "#2b2118";
          ctx.font = "700 18px sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(initials(candidates[i].name), ar, 1);
        }
        ctx.fillStyle = "#fff";
        ctx.font = "700 15px sans-serif";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.shadowColor = "rgba(0,0,0,0.4)";
        ctx.shadowBlur = 3;
        ctx.fillText(candidates[i].name, ar + 36, 0, R - ar - 44);
        ctx.restore();
      }
    }
    ctx.restore();

    ctx.beginPath();
    ctx.arc(cx, cy, 30, 0, 2 * Math.PI);
    ctx.fillStyle = "#fffdf8";
    ctx.fill();
    ctx.strokeStyle = "#b5542d";
    ctx.lineWidth = 4;
    ctx.stroke();
    ctx.fillStyle = "#b5542d";
    ctx.font = "700 15px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("📚", cx, cy + 1);

    ctx.beginPath();
    ctx.moveTo(cx - 15, 4);
    ctx.lineTo(cx + 15, 4);
    ctx.lineTo(cx, 34);
    ctx.closePath();
    ctx.fillStyle = "#b5542d";
    ctx.fill();
  }

  if (spinBtn && candidates.length === 0) {
    spinBtn.disabled = true;
  }

  if (spinBtn) {
    spinBtn.addEventListener("click", async () => {
      if (spinning) return;
      spinning = true;
      resultEl.textContent = "";
      try {
        const res = await fetch(spinUrl, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: "csrf_token=" + encodeURIComponent(csrf),
        });
        const j = await res.json();
        if (!j.ok) {
          resultEl.textContent = j.error || "Något gick fel.";
          spinning = false;
          return;
        }
        const n = candidates.length;
        const seg = (2 * Math.PI) / n;
        const midAngle = j.index * seg + seg / 2;
        const pointer = -Math.PI / 2;
        let target = ((pointer - midAngle) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
        const current = ((rotation % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
        let delta = target - current;
        if (delta < 0) delta += 2 * Math.PI;
        const startRot = rotation;
        const finalRot = startRot + delta + 6 * 2 * Math.PI;
        const duration = 4600;
        const start = performance.now();
        function frame(t) {
          const p = Math.min(1, (t - start) / duration);
          const ease = 1 - Math.pow(1 - p, 4);
          rotation = startRot + (finalRot - startRot) * ease;
          draw();
          if (p < 1) {
            requestAnimationFrame(frame);
          } else {
            resultEl.textContent = j.member.name + " får välja nästa böcker!";
            spinning = false;
            setTimeout(() => window.location.reload(), 1800);
          }
        }
        requestAnimationFrame(frame);
      } catch (e) {
        resultEl.textContent = "Kunde inte snurra hjulet.";
        spinning = false;
      }
    });
  }

  loadImages().then(draw);
});
