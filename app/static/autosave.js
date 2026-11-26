function saveToast(msg, cls, sticky) {
  let el = document.getElementById("save-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "save-toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = "save-toast " + (cls || "");
  el.style.display = "block";
  clearTimeout(el._t);
  if (!sticky) {
    el._t = setTimeout(() => {
      el.style.display = "none";
    }, 2500);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form[data-autosave]").forEach((form) => {
    let timer = null;
    const submit = () => {
      const fd = new FormData(form);
      saveToast("Sparar…", "saving", true);
      fetch(form.action, {
        method: "POST",
        body: fd,
        headers: { "X-Autosave": "1" },
        credentials: "same-origin",
      })
        .then(async (r) => {
          let data = {};
          try {
            data = await r.json();
          } catch (e) {
            data = {};
          }
          if (r.ok && data.ok) {
            saveToast("Sparad ✓", "saved");
          } else if (data.errors && data.errors.length) {
            saveToast("Kunde inte spara: " + data.errors.join("; "), "error");
          } else {
            saveToast("Kunde inte spara (" + r.status + ")", "error");
          }
        })
        .catch(() => saveToast("Kunde inte spara", "error"));
    };
    form.addEventListener("change", (e) => {
      const t = e.target;
      if (!t || !t.name) return;
      if (t.matches("button, input[type=submit], input[type=hidden], input[type=button]")) return;
      if (t.matches("input[type=text], input[type=email], input[type=number], input[type=search], textarea")) {
        clearTimeout(timer);
        timer = setTimeout(submit, 900);
      } else {
        submit();
      }
    });
  });
});
