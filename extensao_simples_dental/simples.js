// Roda no Simples Dental (ja logado pela secretaria). Se o painel deixou um
// pedido, abre "Novo paciente" e preenche. Nunca clica em SALVAR e nao guarda
// senha: a secretaria confere e salva.
(async () => {
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const { pendente } = await chrome.storage.local.get("pendente");
  if (!pendente || Date.now() - pendente.quando > 2 * 60 * 1000) return;
  await chrome.storage.local.remove("pendente");
  const d = pendente.dados;

  const aviso = (texto, erro) => {
    const el = document.createElement("div");
    el.textContent = texto;
    el.style.cssText = "position:fixed;z-index:2147483647;top:70px;left:50%;transform:translateX(-50%);padding:12px 20px;border-radius:8px;color:#fff;font:600 14px Roboto,Arial,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3);background:" + (erro ? "#dc2626" : "#16a34a");
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 9000);
  };

  const campos = () => [...document.querySelectorAll("mat-form-field")].filter((f) => f.offsetParent);
  const achar = (rotulo) => campos().find((f) => f.innerText.trim().toLowerCase().startsWith(rotulo.toLowerCase()));
  const preencher = (rotulo, valor) => {
    const f = achar(rotulo), el = f && f.querySelector("input,textarea");
    if (!el) return false;
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, valor);
    for (const ev of ["input", "change", "blur"]) el.dispatchEvent(new Event(ev, { bubbles: true }));
    return true;
  };
  const clicar = (texto) => {
    const b = [...document.querySelectorAll("button,[role=tab],.mdc-tab,.mat-mdc-tab")]
      .find((x) => x.offsetParent && x.innerText.trim().toUpperCase() === texto);
    if (b) b.click();
    return !!b;
  };

  // O sistema mostra um carregamento antes de abrir; sem login a tela de entrada aparece.
  let aberto = false;
  for (let i = 0; i < 60 && !aberto; i++) {
    if (achar("Nome do paciente")) { aberto = true; break; }
    clicar("NOVO PACIENTE");
    await esperar(500);
  }
  if (!aberto) { aviso("Secretária IA: entre no Simples Dental e envie de novo.", true); return; }
  await esperar(500);

  const falhou = [];
  const p = (rotulo, valor) => { if (valor && !preencher(rotulo, valor)) falhou.push(rotulo); };
  p("Nome do paciente", d.nome);
  p("Data de nascimento", d.nascimento);
  p("CPF", d.cpf);
  p("RG", d.rg);
  p("Celular do paciente", (d.celular || "").replace(/\D/g, "").replace(/^55(?=\d{10,11}$)/, ""));
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
  aviso(falhou.length ? "Preenchi, mas não achei: " + falhou.join(", ") : "Secretária IA: dados preenchidos. Confira e clique em SALVAR.", falhou.length > 0);
})();
