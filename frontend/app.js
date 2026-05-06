const API_BASE = "/api";

document.getElementById("search-btn").addEventListener("click", runSearch);
document.getElementById("search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});

async function runSearch() {
  const q = document.getElementById("search-input").value.trim();
  if (!q) return;
  const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(q)}`);
  const data = await res.json();
  renderResults(data.results);
}

function renderResults(results) {
  const container = document.getElementById("results");
  if (!results.length) {
    container.innerHTML = "<p>No results found.</p>";
    return;
  }
  container.innerHTML = results
    .map(
      (r) => `<article>
        <h2>${r.title}</h2>
        <p>${r.author ?? ""} · ${r.year ?? ""}</p>
      </article>`
    )
    .join("");
}
