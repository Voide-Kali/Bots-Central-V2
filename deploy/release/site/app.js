// Aval, site de apresentacao: interacoes do artefato do Voide, movidas para um arquivo
// externo porque a CSP do /baixar e `default-src 'self'` (sem inline script). Roda no fim
// do body, com o DOM ja pronto. A logica e a mesma do artefato original.
(() => {
  /* 3D seal: stacked layers give the disc its thickness; the face carries the "visto". */
  const seal = document.getElementById("seal");
  for (let z = -13; z <= 13; z += 1) { const l = document.createElement("div"); l.className = "seal__layer"; l.style.setProperty("--z", z); seal.appendChild(l); }
  const face = document.createElement("div");
  face.className = "seal__face";
  face.innerHTML = '<svg viewBox="0 0 200 200"><defs><path id="ring" d="M100,100 m-84,0 a84,84 0 1,1 168,0 a84,84 0 1,1 -168,0"/></defs><g class="seal__ring"><text><textPath href="#ring">APROVADO COM PIN · NADA SEM O SEU AVAL · </textPath></text></g><path class="seal__check" d="M52 104c10 7 18 16 24 25C92 98 118 76 152 66"/></svg>';
  seal.appendChild(face);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduce) {
    addEventListener("pointermove", (e) => {
      const x = e.clientX / innerWidth - .5, y = e.clientY / innerHeight - .5;
      seal.style.setProperty("--rx", `${x * 40}deg`); seal.style.setProperty("--ry", `${-y * 30}deg`);
    }, { passive: true });
  }

  /* Entrances. */
  const io = new IntersectionObserver((entries) => entries.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); } }), { threshold: .18 });
  document.querySelectorAll(".reveal, .reveal-tilt").forEach((el) => io.observe(el));

  /* The two screens turn as they cross the viewport. */
  const scene = document.getElementById("scene");
  const turn = () => { const r = scene.getBoundingClientRect(); const t = Math.max(-1, Math.min(1, (r.top + r.height / 2 - innerHeight / 2) / innerHeight)); scene.style.transform = `rotateY(${-18 + t * -14}deg) rotateX(${8 + t * 6}deg)`; };
  if (!reduce) { addEventListener("scroll", turn, { passive: true }); turn(); }

  /* The request you can type: the same deterministic rules the bot uses. The AI never turns text into an action. */
  const devices = ["tropa", "MacMaker", "pc-sala"];
  const ask = document.getElementById("ask"), out = document.getElementById("answer");
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function parse(text) {
    const t = text.trim();
    if (t === "" || /\?\s*$/.test(t)) return null;
    const low = t.toLowerCase();
    const device = devices.find((d) => new RegExp(`(^|\\s)${d.toLowerCase().replace("-", "\\-")}(\\s|$)`).test(low)) ?? null;
    if (/(^|\s)(bloque\w*|trav\w*)/.test(low)) return { kind: "Bloquear a tela", device };
    if (/(^|\s)(foto\w*|webcam|c[aâ]mera)/.test(low)) return { kind: "Foto da webcam", device };
    const send = /(^|\s)(mand\w*|envi\w*|passa\w*|traz\w*)\s/.test(low);
    const file = t.match(/[\w.-]+\.[a-z0-9]{1,6}/i);
    if (send && file) return { kind: "Mandar arquivo", device, argument: file[0] };
    return null;
  }
  function render() {
    const intent = parse(ask.value);
    if (!intent) {
      out.innerHTML = `<div class="try__kind"><span class="try__dot try__dot--ai"></span>Vai para a IA</div><p class="try__note">A IA responde com os dados dos seus computadores${ask.value.trim() ? "" : " quando você escrever algo"}. Ela não tem como bloquear, fotografar nem mandar nada: isso só nasce de um pedido seu, reconhecido por regras fixas.</p>`;
      return;
    }
    out.innerHTML = `<div class="try__kind"><span class="try__dot"></span>Pedido reconhecido</div><dl class="try__rows"><dt>Ação</dt><dd>${intent.kind}</dd><dt>Computador</dt><dd>${intent.device ? esc(intent.device) : "o bot pergunta qual"}</dd>${intent.argument ? `<dt>Arquivo</dt><dd>${esc(intent.argument)}</dd>` : ""}<dt>Aval</dt><dd>espera o seu PIN de 6 números</dd></dl><p class="try__note">Nada acontece até você digitar o PIN. Se ninguém aprovar, o pedido expira.</p>`;
  }
  ask.addEventListener("input", render);
  document.querySelectorAll(".try__examples button").forEach((b) => b.addEventListener("click", () => { ask.value = b.textContent; render(); ask.focus(); }));
  render();

  /* Copy button on any data-copy element (install hint). */
  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => { try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copiado"; } catch { b.textContent = "Selecione e copie"; } setTimeout(() => { b.textContent = "Copiar"; }, 1800); }));

  /* The command list. */
  const cmds = [
    ["Bloquear a tela", "agora", "Trava a sessão do computador na hora. No Mac, apaga a tela."],
    ["Foto da webcam", "agora", "Uma foto pela câmera do computador, entregue no seu Telegram."],
    ["Mandar um arquivo", "agora", "Um arquivo da pasta compartilhada do agente chega no Telegram, até o limite de tamanho."],
    ["Saúde dos computadores", "agora", "CPU, memória, disco, temperatura e há quanto tempo está ligado, a cada minuto."],
    ["Alertas inteligentes", "agora", "Avisa quando o disco enche, a temperatura sobe ou um computador some, sem repetir o mesmo alerta."],
    ["Histórico", "agora", "Tudo o que foi pedido, aprovado, negado ou entregue, num registro que não se apaga."],
    ["Foto de quem errar a senha", "em breve", "Quando alguém digitar a senha errada no computador, o Aval tira uma foto e avisa você."],
    ["Desligar e reiniciar", "em breve", "Desligar, reiniciar ou suspender, também com o seu PIN."]
  ];
  const list = document.getElementById("cmds"), filter = document.getElementById("filter"), empty = document.getElementById("cmds-empty");
  list.innerHTML = cmds.map(([name, tag, more], i) => `<button type="button" class="cmd" role="option" aria-selected="${i === 0}" id="cmd-${i}"><span class="cmd__name"><span>${name}</span><span class="cmd__tag${tag === "agora" ? "" : " cmd__tag--soon"}">${tag === "agora" ? "Disponível" : "Em breve"}</span></span><span class="cmd__more">${more}</span></button>`).join("");
  const items = [...list.querySelectorAll(".cmd")];
  const select = (el) => items.forEach((it) => it.setAttribute("aria-selected", String(it === el)));
  items.forEach((it) => { it.addEventListener("mouseenter", () => matchMedia("(hover: hover)").matches && select(it)); it.addEventListener("click", () => select(it)); });
  filter.addEventListener("input", () => {
    const q = filter.value.trim().toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");
    let first = null;
    items.forEach((it) => { const hit = it.textContent.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").includes(q); it.hidden = !hit; if (hit && !first) first = it; });
    empty.hidden = first !== null; if (first) select(first);
  });
  filter.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const visible = items.filter((it) => !it.hidden); const cur = visible.findIndex((it) => it.getAttribute("aria-selected") === "true");
    const next = visible[(cur + (e.key === "ArrowDown" ? 1 : -1) + visible.length) % visible.length]; if (next) select(next);
  });
})();
