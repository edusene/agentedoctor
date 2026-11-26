const PACIENTES = "https://app.simplesdental.com/simples/pacientes";

function focar(tabId, windowId) {
  chrome.tabs.update(tabId, { active: true }, () => void chrome.runtime.lastError);
  chrome.windows.update(windowId, { focused: true }, () => void chrome.runtime.lastError);
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.tipo === "abrir") {
    // Guarda de onde veio o pedido para voltar depois de salvar.
    chrome.storage.local.set({ origem: { tabId: sender.tab.id, windowId: sender.tab.windowId } });
    chrome.tabs.query({ url: "https://app.simplesdental.com/*" }, (abas) => {
      if (abas.length) {
        // Aba da secretaria: reaproveita e nao fecha depois (pode ter outro trabalho nela).
        chrome.storage.local.remove("criada");
        // Recarrega em Pacientes: o simples.js le o pedido guardado ao carregar.
        chrome.tabs.update(abas[0].id, { url: PACIENTES, active: true });
        chrome.windows.update(abas[0].windowId, { focused: true });
      } else {
        chrome.tabs.create({ url: PACIENTES }, (aba) => chrome.storage.local.set({ criada: aba.id }));
      }
    });
  } else if (msg.tipo === "voltar") {
    chrome.storage.local.get(["origem", "criada"], ({ origem, criada }) => {
      if (origem) {
        focar(origem.tabId, origem.windowId);
        chrome.tabs.sendMessage(origem.tabId, { tipo: "resultado", texto: msg.texto, erro: msg.erro }, () => void chrome.runtime.lastError);
      }
      // So fecha a aba que a propria extensao abriu.
      if (criada && sender.tab && sender.tab.id === criada) {
        chrome.tabs.remove(criada, () => void chrome.runtime.lastError);
        chrome.storage.local.remove("criada");
      }
    });
  }
});
