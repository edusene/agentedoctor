// Roda no painel. O botao "Simples Dental" avisa a pagina por postMessage; aqui
// os dados vao para o armazenamento da extensao (so neste navegador) e o
// background abre o Simples Dental.
document.documentElement.dataset.extensaoSd = chrome.runtime.getManifest().version;
window.addEventListener("message", (e) => {
  if (e.source !== window || !e.data || e.data.tipo !== "agentedoctor-simples") return;
  // Depois de atualizar a extensao, esta copia fica sem ligacao com ela: so F5 resolve.
  // Qualquer falha vira aviso no painel em vez de erro escondido na pagina de extensoes.
  const recarregar = (motivo) =>
    window.postMessage({ tipo: "agentedoctor-simples-recarregar", motivo }, location.origin);
  try {
    if (!chrome.runtime || !chrome.runtime.id) return recarregar("sem ligação com a extensão");
    chrome.storage.local.set({ pendente: { dados: e.data.dados, quando: Date.now() } }, () => {
      if (chrome.runtime.lastError) return recarregar(chrome.runtime.lastError.message);
      chrome.runtime.sendMessage({ tipo: "abrir" }, () => void chrome.runtime.lastError);
    });
  } catch (erro) {
    recarregar(String(erro && erro.message || erro));
  }
});

// Resultado do cadastro (cadastrado, ja existia...) volta ate a tela do painel.
chrome.runtime.onMessage.addListener((m) => {
  if (m.tipo === "resultado") window.postMessage({ tipo: "agentedoctor-simples-resultado", texto: m.texto, erro: m.erro }, location.origin);
});
