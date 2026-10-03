// Shared DOM checks used by the live adapter and regression fixtures.
(() => {
  const normalizePrompt = text => String(text ?? "").replace(/[\u200b\ufeff]/g, "").replace(/\s+/gu, " ").trim();
  const visible = element => Boolean(element?.getClientRects().length) && getComputedStyle(element).visibility !== "hidden";
  function findComposer(root = document) {
    return [...root.querySelectorAll('textarea,[contenteditable="true"][role="textbox"],#prompt-textarea')]
      .find(element => visible(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true");
  }
  function findSend(composer) {
    const scope = composer?.closest("form") ?? composer?.parentElement;
    if (!scope) return null;
    const candidates = [...scope.querySelectorAll("button")].filter(element => {
      const name = (element.getAttribute("aria-label") || element.textContent || "").trim();
      return visible(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true"
        && element.getAttribute("aria-busy") !== "true"
        && /^(Send message|Send prompt|Send|Submit|إرسال|إرسال الرسالة)$/iu.test(name);
    });
    return candidates.length === 1 ? candidates[0] : null;
  }
  function messages(kind, root = document) {
    const legacy = [...root.querySelectorAll(`[data-message-author-role="${kind}"]`)];
    if (legacy.length) return legacy;
    // Current ChatGPT Chat layout exposes message headings instead of author attributes.
    const heading = kind === "user" ? "You said:" : "ChatGPT said:";
    return [...root.querySelectorAll("main h4")].filter(element => element.textContent.trim() === heading)
      .map(element => element.parentElement);
  }
  function promptMatches(message, prompt) {
    return normalizePrompt(message?.innerText).includes(normalizePrompt(prompt));
  }
  const api = {normalizePrompt, visible, findComposer, findSend, messages, promptMatches};
  globalThis.falkronaProviderDOM = api;
  if (typeof module !== "undefined") module.exports = api;
})();
