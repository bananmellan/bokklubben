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
  if (sessionStorage.getItem("autosave_state") === "saving") {
    sessionStorage.removeItem("autosave_state");
    saveToast("Sparad ✓", "saved");
  }

  const forms = document.querySelectorAll("form[data-autosave]");
  forms.forEach((form) => {
    let timer = null;
    const submit = () => {
      const active = document.activeElement;
      if (active && active.name) {
        sessionStorage.setItem("autosave_focus", active.name);
      }
      sessionStorage.setItem("autosave_scroll", String(window.scrollY));
      sessionStorage.setItem("autosave_state", "saving");
      saveToast("Sparar…", "saving", true);
      form.requestSubmit();
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

  const y = sessionStorage.getItem("autosave_scroll");
  if (y !== null) {
    sessionStorage.removeItem("autosave_scroll");
    window.scrollTo(0, parseInt(y, 10) || 0);
  }
  const focusName = sessionStorage.getItem("autosave_focus");
  if (focusName) {
    sessionStorage.removeItem("autosave_focus");
    const el = document.querySelector(`[name="${CSS.escape(focusName)}"]`);
    if (el) el.focus();
  }
});
