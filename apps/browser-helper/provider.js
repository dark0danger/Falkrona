// Website UI adapter: no undocumented APIs, tokens, cookies or existing-chat access.
if (!globalThis.falkronaProviderV3Installed) {
  globalThis.falkronaProviderV3Installed = true;
  const {normalizePrompt, findComposer, findSend, messages, promptMatches} = globalThis.falkronaProviderDOM;
  let started = false;
  let cancelled = false;
  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    if (message.action === "cancel") { cancelled = true; respond({ok: true}); return; }
    if (!["generate", "resume"].includes(message.action) || started) return;
    started = true;
    respond({accepted: true});
    void generate(message.packet, message.action === "resume", Boolean(message.observeOnly))
      .catch(error => chrome.runtime.sendMessage({action: "provider-result", error: error.message}))
      .finally(() => { started = false; });
  });
  const visible = element => element && element.getClientRects().length && getComputedStyle(element).visibility !== "hidden";
  const buttons = () => [...document.querySelectorAll("button,[role=menuitem],[role=option]")].filter(visible);
  const label = element => element.getAttribute("aria-label") || element.textContent.trim();
  const button = expression => buttons().find(element => expression.test(label(element)));
  function uploadInput() {
    const inputs = [...document.querySelectorAll('input[type="file"]')]
      .filter(e => e.multiple && !/camera/i.test(e.id));
    // ChatGPT now mounts three inputs. The first is its video picker, even in
    // a text chat; use the ordinary attachment picker instead of DOM order.
    return inputs.find(e => /^(Attach files|إرفاق ملفات)$/i.test(e.getAttribute?.("aria-label") || ""))
      || inputs.find(e => /^(Attach photos|إرفاق صور)$/i.test(e.getAttribute?.("aria-label") || ""))
      || inputs.find(e => !/video/i.test(e.getAttribute?.("accept") || ""));
  }
  async function readyUploadInput(provider) {
    if (provider !== "chatgpt") return uploadInput();
    // The server-rendered composer/input can appear before React accepts files.
    // Verify a real interaction first; an opened upload menu proves hydration.
    const ready = await waitFor(() => {
      if (button(/Add photos.*files|Upload from computer|تحميل من الكمبيوتر/i)) return true;
      const toggle = button(/^Add files and more$/i);
      if (toggle && toggle.getAttribute("aria-expanded") !== "true") toggle.click();
      return null;
    }, 60000);
    if (!ready) pause("ChatGPT's upload controls are still loading. Continue creating designs to resume this saved request.");
    const toggle = button(/^Add files and more$/i);
    if (toggle?.getAttribute("aria-expanded") === "true") toggle.click();
    return waitFor(uploadInput);
  }
  const pause = message => { throw new Error(message); };
  async function waitFor(check, timeout = 20000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) { if (cancelled) pause("The helper was disconnected."); const result = check(); if (result) return result; await new Promise(r => setTimeout(r, 500)); }
    return null;
  }
  async function progress(stage) {
    if (cancelled) pause("The helper was disconnected.");
    const result = await chrome.runtime.sendMessage({action: "provider-progress", stage});
    if (!result?.ok) pause("The helper connection ended. Nothing will be resent.");
  }
  async function confirmAttachments(packet) {
    const attached = await waitFor(() => packet.attachments.every(attachmentNamed), 45000);
    if (!attached) pause("The image app did not confirm all attachments. Check its tab; use the saved prompt if needed.");
  }
  function attachmentNamed(asset) {
    return document.body.innerText.includes(asset.name) || [...document.querySelectorAll('[aria-label],[title]')]
      .some(e => (e.getAttribute('aria-label') || e.title || '').includes(asset.name));
  }
  async function generate(packet, resume = false, observeOnly = false) {
    if (location.origin !== (packet.provider === "gemini" ? "https://gemini.google.com" : "https://chatgpt.com")) pause("Open your image app and sign in, then use the saved prompt in Studio.");
    await waitFor(() => findComposer(), 60000);
    if (button(/^(Sign in|Log in|تسجيل الدخول)$/i)) pause("Sign in to your image app first. Your direction is saved; the helper has not sent it.");
    const responseSelector = packet.provider === "gemini" ? "model-response" : '[data-message-author-role="assistant"]';
    const userMessages = () => packet.provider === "chatgpt" ? messages("user") : [...document.querySelectorAll("user-query")];
    const responses = () => packet.provider === "chatgpt" ? messages("assistant") : [...document.querySelectorAll(responseSelector)];
    if (resume) {
      const users = userMessages();
      if (users.length === 1 && promptMatches(users[0], packet.prompt)) {
        await progress("submitted");
        return receiveImage(packet, responseSelector);
      }
      if (observeOnly || users.length || responses().length) pause("The prior submission needs review. Nothing will be resent.");
      const composer = findComposer();
      if (composer && !normalizePrompt(composer.value || composer.innerText)) {
        const hasFiles = [...document.querySelectorAll('input[type="file"]')].some(input => input.files?.length);
        if (!hasFiles && !packet.attachments.some(asset => document.body.innerText.includes(asset.name)))
          return generate(packet, false, false); // Known empty login pause, no prior message/upload.
      }
      if (!composer || normalizePrompt(composer.value || composer.innerText) !== normalizePrompt(packet.prompt))
        pause("The prepared message changed or is missing. Nothing was sent.");
      await confirmAttachments(packet);
      await submit(composer);
      return receiveImage(packet, responseSelector);
    }
    if (responses().length || userMessages().length) pause("A fresh conversation could not be verified. The helper has not sent it.");
    if (packet.provider === "gemini") {
      const picker = button(/Open mode picker.*Flash-Lite/i);
      if (picker) {
        picker.click();
        const flash = await waitFor(() => button(/^Flash$/i), 3000);
        if (!flash) pause("Choose Flash in Gemini for multiple image references, then use the saved prompt.");
        flash.click();
      }
    }
    await progress("attaching");
    let input = await readyUploadInput(packet.provider);
    if (!input) {
      const upload = button(/Upload & tools|Add files and more|إضافة ملفات|تحميل/i);
      if (!upload) pause("The upload controls changed. Download the prepared images from Studio.");
      upload.click();
      const local = await waitFor(() => button(/Upload files|Upload from computer|تحميل ملفات|تحميل من الكمبيوتر/i), 3000);
      if (local) local.click();
      input = await waitFor(uploadInput);
    }
    if (!input || (!input.multiple && packet.attachments.length > 1)) pause("Automatic attachment is unavailable. Use the prepared files in Studio.");
    const transfer = new DataTransfer();
    for (const asset of packet.attachments) {
      const raw = atob(asset.data); const bytes = Uint8Array.from(raw, character => character.charCodeAt(0));
      transfer.items.add(new File([bytes], asset.name, {type: asset.mime_type}));
    }
    if (cancelled) pause("The helper was disconnected.");
    for (let attempt = 0; attempt < 2; attempt++) {
      input.files = transfer.files; input.dispatchEvent(new Event("change", {bubbles: true}));
      // Initial hydration can replace the file input before its handler accepts files.
      await waitFor(() => packet.attachments.every(attachmentNamed) || input.isConnected === false, 45000);
      if (packet.attachments.every(attachmentNamed)) break;
      const editor = findComposer();
      const hasSelectedFiles = [...document.querySelectorAll('input[type="file"]')].some(e => e.files?.length);
      const hasAttachmentPreview = [...document.querySelectorAll('[data-composer-attachments]')]
        .some(e => visible(e) && (e.querySelector('img') || e.textContent.trim()));
      if (attempt === 0 && !hasSelectedFiles && !hasAttachmentPreview && !packet.attachments.some(attachmentNamed)
          && !userMessages().length && !responses().length && editor && !normalizePrompt(editor.value || editor.innerText)) {
        input = await waitFor(uploadInput);
        if (input) continue; // Hydration may replace OR retain/reset an inactive input.
      }
      pause("The image app did not confirm all attachments. Check its tab; use the saved prompt if needed.");
    }
    const composer = findComposer();
    if (!composer || (composer.value || composer.innerText || '').trim()) pause("The composer is not empty. Nothing was sent.");
    composer.focus();
    if (composer.tagName === "TEXTAREA") {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(composer, packet.prompt);
    } else {
      // Editing command triggers the site's normal rich-text input handling.
      document.execCommand("insertText", false, packet.prompt);
    }
    composer.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: packet.prompt}));
    // Rich editors add paragraph breaks and NBSP. Compare every word, not their spacing.
    if (normalizePrompt(composer.value || composer.innerText) !== normalizePrompt(packet.prompt)) pause("The prompt did not load correctly. Nothing was sent.");
    await submit(composer);
    return receiveImage(packet, responseSelector);
  }
  async function submit(composer) {
    await progress("ready_to_send");
    const send = await waitFor(() => findSend(composer), 45000);
    if (!send) pause("The image app is not ready to send. Check its tab.");
    // Persist intent BEFORE clicking. Interrupted/uncertain sends must never be repeated.
    await progress("submitted"); send.click();
  }
  async function receiveImage(packet, responseSelector) {
    const end = Math.min(Date.parse(packet.expires_at), Date.now() + 18 * 60000);
    const observationStarted = Date.now();
    let checkedFresh = false;
    let stableImages = "", stableSince = 0;
    while (Date.now() < end) {
      await new Promise(r => setTimeout(r, 2000));
      await progress("submitted");
      const users = packet.provider === "chatgpt" ? messages("user") : [...document.querySelectorAll("user-query")];
      // An image is accepted only after the actual request appears in the transcript.
      if (users.length > 1) pause("This chat has additional messages. Choose the correct image manually.");
      if (users.length !== 1 || !promptMatches(users[0], packet.prompt)) continue;
      const responses = packet.provider === "chatgpt" ? messages("assistant") : [...document.querySelectorAll(responseSelector)];
      if (responses.length > 1) pause("More than one response appeared. Choose the correct image manually in Studio.");
      const response = responses[0];
      if (!response) continue;
      // Streaming previews can overlap with the finished image. Decide cardinality
      // only after generation stops and the visible candidates settle.
      if (button(/^(Stop|Stop generating|Stop response|إيقاف)/i)) { stableImages = ""; continue; }
      const candidates = [...response.querySelectorAll("img")].filter(img => visible(img) && img.complete && img.naturalWidth >= 400 && img.naturalHeight >= 500 && Math.abs(img.naturalWidth / img.naturalHeight - .8) <= .015);
      const images = [...new Map(candidates.map(img => [img.currentSrc || img.src, img])).values()];
      const signature = JSON.stringify(images.map(img => img.currentSrc || img.src).sort());
      if (signature !== stableImages) { stableImages = signature; stableSince = Date.now(); }
      if (images.length && Date.now() - stableSince < 6000) continue;
      if (images.length > 1) pause("Multiple generated images appeared. Download your preferred image and import it in Studio.");
      if (!images.length && !checkedFresh && packet.provider === "chatgpt" && Date.now()-observationStarted >= 3*60000) {
        checkedFresh = true;
        const refreshed = await chrome.runtime.sendMessage({action:"provider-refresh",packet});
        if (refreshed?.ok) return; // New observer never sends; the original tab can stay stuck at 99%.
      }
      if (images.length !== 1) continue;
      // Read only the visible result URL; no hidden provider endpoints or tokens.
      const source = images[0].currentSrc || images[0].src;
      const fetched = await fetch(source, {credentials: new URL(source, location.href).origin === location.origin ? "include" : "omit"});
      if (!fetched.ok) pause("Download the image from the app and import it in Studio.");
      const blob = await fetched.blob();
      if (!/^image\/(png|jpeg|webp)$/.test(blob.type) || blob.size > 15000000) pause("Use Download in the image app, then import the image in Studio.");
      const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });
      await chrome.runtime.sendMessage({action: "provider-result", image: data});
      return;
    }
    pause("Generation is taking longer than expected. Nothing will be resent; download the result when it is ready and import it in Studio.");
  }
}
