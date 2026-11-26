const PACIENTES = "https://app.simplesdental.com/simples/pacientes";

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.tipo !== "abrir") return;
  chrome.tabs.query({ url: "https://app.simplesdental.com/*" }, (abas) => {
    if (abas.length) {
      // Recarrega em Pacientes: o simples.js le o pedido guardado ao carregar.
      chrome.tabs.update(abas[0].id, { url: PACIENTES, active: true });
      chrome.windows.update(abas[0].windowId, { focused: true });
    } else {
      chrome.tabs.create({ url: PACIENTES });
    }
  });
});
