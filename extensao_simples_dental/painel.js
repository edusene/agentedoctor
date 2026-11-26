// Roda no painel. O botao "Simples Dental" avisa a pagina por postMessage; aqui
// os dados vao para o armazenamento da extensao (so neste navegador) e o
// background abre o Simples Dental.
document.documentElement.dataset.extensaoSd = "1";
window.addEventListener("message", (e) => {
  if (e.source !== window || !e.data || e.data.tipo !== "agentedoctor-simples") return;
  chrome.storage.local.set({ pendente: { dados: e.data.dados, quando: Date.now() } }, () => {
    chrome.runtime.sendMessage({ tipo: "abrir" });
  });
});
