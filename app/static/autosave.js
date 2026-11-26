document.addEventListener("DOMContentLoaded", () => {
  const forms = document.querySelectorAll("form[data-autosave]");
  forms.forEach((form) => {
    let timer = null;
    const submit = () => {
      const active = document.activeElement;
      if (active && active.name) {
        sessionStorage.setItem("autosave_focus", active.name);
      }
      sessionStorage.setItem("autosave_scroll", String(window.scrollY));
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
