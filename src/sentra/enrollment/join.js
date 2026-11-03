"use strict";
(() => {
  const el = id => document.getElementById(id);
  let state = null;
  let busy = false;
  async function api(path, body) {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", ...(state ? {"X-CSRF-Token": state.csrf} : {})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    const result = await response.json();
    if (!response.ok) throw Object.assign(new Error(result.message || "Please try again."), {status: response.status});
    return result;
  }
  function message(text, error = false) {
    el("notice").hidden = true; el("error").hidden = true;
    const target = el(error ? "error" : "notice");
    target.textContent = text; target.hidden = false;
    if (error) target.focus();
  }
  async function action(run) {
    if (busy) return;
    busy = true;
    document.querySelectorAll("button").forEach(button => button.disabled = true);
    try { await run(); }
    catch (error) { message(error.message || "Connection unavailable. Please try again.", true); }
    finally { busy = false; document.querySelectorAll("button").forEach(button => button.disabled = false); }
  }
  function choices() {
    return {sharing: document.querySelector('input[name="sharing"]:checked').value,
      demonstration: el("demonstration").checked, accepted: el("accepted").checked};
  }
  function render() {
    const account = state.signed_in;
    document.title = account ? "Your participation · Sentra" : "Join Sentra";
    el("loading").hidden = true;
    el("form-content").hidden = false;
    el("organization").textContent = state.organization || "YOUR PARTICIPATION";
    el("recipient").textContent = state.organization || "your organization";
    el("consent-version").textContent = state.consent_version;
    el("card-heading").textContent = account ? "You’re in control" : state.joining ? "Join on your terms" : "Welcome back";
    el("choice-fields").hidden = (!state.joining && !account) || (account && !state.enrolled);
    el("account-summary").hidden = !account;
    el("account-actions").hidden = !account;
    el("save").hidden = !account || !state.enrolled;
    el("withdraw").hidden = !account || !state.enrolled;
    el("providers").hidden = account && !state.enrolled;
    el("connect-label").textContent = account ? "Connect or reconnect a wearable" : state.joining ? "Connect your wearable" : "Sign in with your connected wearable";
    if (account) {
      document.querySelector(`input[name="sharing"][value="${state.sharing}"]`).checked = true;
      el("demonstration").checked = state.demonstration;
      el("accepted").checked = false;
      el("heading").textContent = "Your data. Your decision.";
      el("subtitle").textContent = "Manage your sharing, reconnect a wearable, or stop participating at any time.";
      el("participation").textContent = state.enrolled ? "Enrolled" : "Withdrawn";
      el("connection").textContent = !state.enrolled ? "Stopped" : state.connected ? "Connected" : "Reconnect required";
      el("data-status").textContent = !state.enrolled ? "Not contributing" : state.recently_contributing ? "Contributing" : state.latest_received_at ? "No recent readings" : "Waiting for first data";
      el("data-detail").textContent = !state.enrolled
        ? "Your sharing and collection have stopped. Stored data follows the retention policy. A new invitation is needed to join again."
        : state.latest_received_at
          ? "A successful connection and received data do not guarantee recent usable coverage or a ready assessment."
          : state.collection_paused ? "Your account is connected. Data will appear after collection is enabled by the team. You don’t need to stay on this page."
          : "Your account is connected. Waiting for the first collection and usable readings. You don’t need to stay on this page.";
    } else {
      el("heading").replaceChildren(document.createTextNode("A few taps. "), document.createElement("br"), document.createTextNode("A clearer picture."));
      el("subtitle").textContent = "Connect the wearable you already use. Choose what to share. Stay in control.";
    }
    document.querySelectorAll("[data-provider]").forEach(button => {
      button.hidden = !state.providers_available.includes(button.dataset.provider);
    });
  }
  async function refresh() { state = await api("/api/status"); render(); }
  document.querySelectorAll("[data-provider]").forEach(button => button.addEventListener("click", () => action(async () => {
    const data = choices();
    if (state.joining && !data.accepted) throw new Error("Please confirm your participation choices before connecting.");
    const result = await api("/api/connect", {provider: button.dataset.provider, ...data});
    window.location.assign(result.url);
  })));
  el("sharing-form").addEventListener("submit", event => {
    event.preventDefault(); action(async () => { const result = await api("/api/choices", choices()); await refresh(); message(result.message); });
  });
  el("withdraw").addEventListener("click", () => { el("withdraw-confirm").hidden = false; el("confirm-withdraw").focus(); });
  el("cancel-withdraw").addEventListener("click", () => { el("withdraw-confirm").hidden = true; el("withdraw").focus(); });
  el("confirm-withdraw").addEventListener("click", () => action(async () => {
    const result = await api("/api/withdraw", {}); el("withdraw-confirm").hidden = true; await refresh(); message(result.message);
  }));
  el("logout").addEventListener("click", () => action(async () => { await api("/api/logout", {}); window.location.assign("/join"); }));
  async function initialize() {
    state = null;
    el("error").hidden = true; el("notice").hidden = true;
    el("form-content").hidden = true; el("loading").hidden = false;
    el("accepted").checked = false; el("demonstration").checked = false;
    document.querySelector('input[name="sharing"][value="group_only"]').checked = true;
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const invite = fragment.get("invite");
    const outcome = new URLSearchParams(window.location.search).get("connection");
    // Invitation stays in the fragment only until this page loads; never in HTTP URLs/referrers.
    history.replaceState(null, "", window.location.pathname);
    try {
      if (invite) state = await api("/api/session", {invite});
      else {
        try { state = await api("/api/status"); }
        catch (error) { if (error.status !== 401) throw error; state = await api("/api/session", {}); }
      }
      render();
      if (outcome === "cancelled") message("Connection cancelled. No changes were made by this attempt. You can try again.");
      if (outcome === "failed") message("Connection could not be completed. Please try again or ask the Sentra team for help.", true);
    } catch (error) { el("loading").hidden = true; message(error.message, true); }
  }
  window.addEventListener("hashchange", initialize);
  initialize();
})();
