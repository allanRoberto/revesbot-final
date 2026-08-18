const LABELS = { connecting: "Conectando", online: "Ao vivo", offline: "Reconectando", paused: "Pausado" };

export function setLiveStatus(element, textElement, state) {
  element.dataset.state = state;
  textElement.textContent = LABELS[state] || state;
}
