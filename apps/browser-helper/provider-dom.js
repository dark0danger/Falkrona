// Shared DOM checks used by the live adapter and regression fixtures.
(() => {
  const normalizePrompt = text => String(text ?? "").replace(/[\u200b\ufeff]/g, "").replace(/\s+/gu, " ").trim();
  const visible = element => Boolean(element?.getClientRects().length) && getComputedStyle(element).visibility !== "hidden";
  function findComposer(root = document) {
    return [...root.querySelectorAll('textarea,[contenteditable="true"][role="textbox"],#prompt-textarea')]
      .find(element => visible(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true");
  }
  function findSend(composer, provider) {
    const scope = composer?.closest(provider === "gemini" ? "fieldset,form" : "form") ?? composer?.parentElement;
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
  function geminiControl(pattern, root = document) {
    return [...root.querySelectorAll('button,[role="button"],[role="menuitem"],[role="menuitemradio"],[role="option"]')]
      .find(element => visible(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true"
        && [element.getAttribute("aria-label"), element.getAttribute("title"), element.textContent]
          .some(name => pattern.test(normalizePrompt(name))));
  }
  function geminiFileInput(root = document) {
    const candidates = [...root.querySelectorAll('input[type="file"]')].filter(input => {
      if (input.disabled || input.isConnected === false || input.webkitdirectory || input.hasAttribute("capture")) return false;
      const name = [input.id, input.getAttribute("aria-label")].join(" ");
      if (/camera|folder|directory|capture/i.test(name)) return false;
      const accept = normalizePrompt(input.getAttribute("accept"));
      return !accept || accept.split(",").some(type => /^(?:\*\/\*|image\/\S+|\.(?:png|jpe?g|webp|gif))$/i.test(type.trim()));
    });
    const multiple = candidates.filter(input => input.multiple);
    return multiple.length === 1 ? multiple[0] : candidates.length === 1 ? candidates[0] : null;
  }
  function geminiAttachments(root = document) {
    // Gemini's image tiles can omit the filename entirely. Each tile still
    // exposes a visible, separately labelled remove control.
    return [...root.querySelectorAll('button,[role="button"]')].filter(element => visible(element)
      && [element.getAttribute("aria-label"), element.getAttribute("title"), element.textContent].some(label =>
        /^(?:(?:close|remove) attachment|إزالة المرفق|حذف المرفق)$/iu.test(normalizePrompt(label))));
  }
  const api = {normalizePrompt, visible, findComposer, findSend, messages, promptMatches,
    geminiControl, geminiFileInput, geminiAttachments};
  globalThis.falkronaProviderDOM = api;
  if (typeof module !== "undefined") module.exports = api;
})();
