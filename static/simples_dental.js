// Atalho (bookmarklet) do Simples Dental: preenche "Novo paciente" com os dados
// copiados do painel (botao "Copiar para o Simples Dental"). Nao salva: a
// secretaria confere e clica em SALVAR. Nao guarda senha nem chama servidor.
(async () => {
    const esperar = ms => new Promise(r => setTimeout(r, ms));
    let d;
    try {
        d = JSON.parse(await navigator.clipboard.readText());
    } catch (e) { d = null; }
    if (!d || d.agentedoctor !== 1) { alert('Copie os dados no painel primeiro (botão "Copiar para o Simples Dental").'); return; }

    const campos = () => [...document.querySelectorAll('mat-form-field')].filter(f => f.offsetParent);
    const achar = rotulo => campos().find(f => f.innerText.trim().toLowerCase().startsWith(rotulo.toLowerCase()));
    const preencher = (rotulo, valor) => {
        if (!valor) return false;
        const f = achar(rotulo), el = f && f.querySelector('input,textarea');
        if (!el) return false;
        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
        Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, valor);
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.dispatchEvent(new Event('blur', {bubbles: true}));
        return true;
    };
    const clicar = texto => {
        const b = [...document.querySelectorAll('button,[role=tab],.mdc-tab,.mat-mdc-tab')]
            .find(x => x.offsetParent && x.innerText.trim().toUpperCase() === texto);
        if (b) b.click();
        return !!b;
    };

    if (!achar('Nome do paciente')) { clicar('NOVO PACIENTE'); await esperar(1500); }
    if (!achar('Nome do paciente')) { alert('Abra Pacientes e tente de novo.'); return; }

    const falhou = [];
    const p = (rotulo, valor) => { if (valor && !preencher(rotulo, valor)) falhou.push(rotulo); };
    p('Nome do paciente', d.nome);
    p('Data de nascimento', d.nascimento);
    p('CPF', d.cpf);
    p('RG', d.rg);
    p('Celular do paciente', (d.celular || '').replace(/\D/g, '').replace(/^55(?=\d{10,11}$)/, ''));
    p('Observação', d.observacao);
    clicar('INFORMAÇÕES ADICIONAIS'); await esperar(400);
    p('E-mail', d.email);
    clicar('ENDEREÇO'); await esperar(500);
    p('CEP', d.cep);
    await esperar(1500); // o CEP pode preencher rua, bairro e cidade sozinho
    const rua = achar('Rua') && achar('Rua').querySelector('input');
    if (rua && !rua.value) p('Rua', d.endereco);
    alert('Dados colocados no formulário. Confira e clique em SALVAR.' +
        (falhou.length ? '\nNão achei: ' + falhou.join(', ') : ''));
})();
