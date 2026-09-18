(() => {
  const form = document.querySelector("#evaluate-form");
  const result = document.querySelector("#evaluate-result");
  const submit = document.querySelector("#evaluate-submit");
  if (!form) return;

  const token = () => localStorage.getItem("stataxis_access_token") || "";
  const set = (id, value) => { const node = document.querySelector(id); if (node) node.textContent = value; };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const accessToken = token();
    if (!accessToken) {
      set("#evaluate-error", "Please sign in before evaluation.");
      return;
    }
    const url = form.elements.url.value.trim();
    const displayName = form.elements.display_name.value.trim();
    submit.disabled = true;
    set("#evaluate-error", "");
    set("#evaluate-status", "Fetching live YouTube measurement…");
    try {
      const response = await fetch("/api/v1/evaluate/youtube", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ url, display_name: displayName }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `Evaluation failed (${response.status})`);
      result.hidden = false;
      set("#evaluate-status", payload.observation_count < 2 ? "Observation captured · baseline building" : "Evaluation complete");
      set("#result-name", payload.display_name);
      set("#result-channel", payload.channel_name);
      set("#result-score", payload.stx_index == null ? "—" : Number(payload.stx_index).toFixed(1));
      set("#result-confidence", `${Math.round(Number(payload.confidence))}%`);
      set("#result-count", String(payload.observation_count));
      set("#result-data", (payload.data || []).join(" "));
      set("#result-analysis", (payload.analysis || []).join(" "));
      set("#result-view", payload.view || "");
    } catch (error) {
      set("#evaluate-error", error.message || "Evaluation failed");
      set("#evaluate-status", "Evaluation stopped");
    } finally {
      submit.disabled = false;
    }
  });
})();
