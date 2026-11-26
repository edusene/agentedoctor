// Roda no painel. O botao "Simples Dental" avisa a pagina por postMessage; aqui
// os dados vao para o armazenamento da extensao (so neste navegador) e o
// background abre o Simples Dental.
document.documentElement.dataset.extensaoSd = "1";
window.addEventListener("message", (e) => {
  if (e.source !== window || !e.data || e.data.tipo !== "agentedoctor-simples") return;
  // Depois de atualizar a extensao, esta copia fica sem ligacao com ela: so F5 resolve.
  if (!chrome.runtime || !chrome.runtime.id) {
    window.postMessage({ tipo: "agentedoctor-simples-recarregar" }, location.origin);
    return;
  }
  chrome.storage.local.set({ pendente: { dados: e.data.dados, quando: Date.now() } }, () => {
    chrome.runtime.sendMessage({ tipo: "abrir" });
  });
});

// Resultado do cadastro (cadastrado, ja existia...) volta ate a tela do painel.
chrome.runtime.onMessage.addListener((m) => {
  if (m.tipo === "resultado") window.postMessage({ tipo: "agentedoctor-simples-resultado", texto: m.texto, erro: m.erro }, location.origin);
});
