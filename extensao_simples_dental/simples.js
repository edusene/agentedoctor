// Roda no Simples Dental (ja logado pela secretaria). Se o painel deixou um
// pedido: confere se o paciente ja existe, abre "Novo paciente", preenche,
// clica em SALVAR, confere que gravou e volta para o painel. Nao guarda senha.
// Qualquer duvida (duplicado, campo nao achado, erro ao salvar) para e avisa.
(async () => {
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const { pendente } = await chrome.storage.local.get("pendente");
  if (!pendente || Date.now() - pendente.quando > 2 * 60 * 1000) return;
  await chrome.storage.local.remove("pendente");
  const d = pendente.dados;
  const norm = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

  // O WhatsApp entrega celular antigo sem o 9 (DDD + 8 digitos); o Simples Dental
  // exige o nono digito. Fixo comeca em 2 a 5 e fica como esta.
  const celularComNove = (bruto) => {
    let n = (bruto || "").replace(/\D/g, "").replace(/^55(?=\d{10,11}$)/, "");
    if (/^\d{2}[6-9]\d{7}$/.test(n)) n = n.slice(0, 2) + "9" + n.slice(2);
    return n;
  };

  const aviso = (texto, erro) => {
    const el = document.createElement("div");
    el.textContent = texto;
    el.style.cssText = "position:fixed;z-index:2147483647;top:70px;left:50%;transform:translateX(-50%);padding:12px 20px;border-radius:8px;color:#fff;font:600 14px Roboto,Arial,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3);background:" + (erro ? "#dc2626" : "#16a34a");
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 9000);
  };
  // Volta ao painel e mostra la o resultado (a aba do Simples Dental some da vista).
  const voltar = (texto, erro) => chrome.runtime.sendMessage({ tipo: "voltar", texto, erro });

  const campos = () => [...document.querySelectorAll("mat-form-field")].filter((f) => f.offsetParent);
  const achar = (rotulo) => campos().find((f) => f.innerText.trim().toLowerCase().startsWith(rotulo.toLowerCase()));
  const setar = (el, valor) => {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, valor);
    for (const ev of ["input", "change", "blur"]) el.dispatchEvent(new Event(ev, { bubbles: true }));
  };
  const preencher = (rotulo, valor) => {
    const f = achar(rotulo), el = f && f.querySelector("input,textarea");
    if (!el) return false;
    setar(el, valor);
    return true;
  };
  const botao = (texto) => [...document.querySelectorAll("button,[role=tab],.mdc-tab,.mat-mdc-tab")]
    .find((x) => x.offsetParent && x.innerText.trim().toUpperCase() === texto);
  const clicar = (texto) => { const b = botao(texto); if (b) b.click(); return !!b; };
  const formAberto = () => !!achar("Nome do paciente");

  // Nomes que a busca da lista devolve ("Ir para a ficha de <nome>").
  const buscar = async (termo) => {
    const busca = document.querySelector('input[aria-label="Buscar paciente"]');
    setar(busca, termo);
    await esperar(2200);
    const nomes = [...document.querySelectorAll("body *")]
      .filter((e) => e.children.length === 0 && e.offsetParent)
      .map((e) => /^Ir para a ficha de (.+)$/.exec(e.textContent.trim()))
      .filter(Boolean).map((m) => m[1]);
    setar(busca, "");
    return nomes;
  };

  // Espera a lista de pacientes carregar (o sistema mostra um carregamento antes).
  let pronto = false;
  for (let i = 0; i < 60 && !pronto; i++) {
    pronto = !!document.querySelector('input[aria-label="Buscar paciente"]');
    if (!pronto) await esperar(500);
  }
  if (!pronto) { aviso("Secretária IA: entre no Simples Dental e envie de novo.", true); return; }

  const jaTem = (await buscar(d.nome)).find((n) => norm(n) === norm(d.nome))
    || (d.cpf ? (await buscar(d.cpf.replace(/\D/g, "")))[0] : "");
  if (jaTem) { const msg = jaTem + " já está cadastrado no Simples Dental. Não criei de novo."; aviso("Secretária IA: " + msg, true); voltar(msg, true); return; }

  for (let i = 0; i < 20 && !formAberto(); i++) { clicar("NOVO PACIENTE"); await esperar(500); }
  if (!formAberto()) { aviso("Secretária IA: não consegui abrir Novo paciente.", true); return; }
  await esperar(500);

  const falhou = [];
  const p = (rotulo, valor) => { if (valor && !preencher(rotulo, valor)) falhou.push(rotulo); };
  p("Nome do paciente", d.nome);
  p("Data de nascimento", d.nascimento);
  p("CPF", d.cpf);
  p("RG", d.rg);
  p("Celular do paciente", celularComNove(d.celular));
  p("Observação", d.observacao);
  clicar("INFORMAÇÕES ADICIONAIS"); await esperar(400);
  p("E-mail", d.email);
  if (d.cep || d.endereco) {
    clicar("ENDEREÇO"); await esperar(500);
    p("CEP", d.cep);
    await esperar(1500); // o CEP preenche rua, bairro, cidade e estado sozinho
    const rua = achar("Rua") && achar("Rua").querySelector("input");
    if (rua && !rua.value) p("Rua", d.endereco);
  }
  if (falhou.length) { aviso("Não achei: " + falhou.join(", ") + ". Confira e clique em SALVAR.", true); return; }

  if (!clicar("SALVAR")) { aviso("Preenchi. Clique em SALVAR.", true); return; }
  for (let i = 0; i < 24 && formAberto(); i++) await esperar(500);
  if (formAberto()) { aviso("Não salvou: confira os campos e clique em SALVAR.", true); return; }
  const ok = d.nome + " cadastrado no Simples Dental.";
  aviso("Secretária IA: " + ok);
  voltar(ok, false);
})();
