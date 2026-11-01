// Marks the document as JS-enabled before first paint so the entrance animations
// can start from their hidden state (kept in an external file because the /baixar
// CSP is default-src 'self' and forbids inline scripts). Loaded blocking in <head>.
document.documentElement.classList.add("js");
