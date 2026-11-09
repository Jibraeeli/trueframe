const form = document.getElementById("upload-form");
const input = document.getElementById("file-input");
const zone = document.getElementById("drop-zone");
const dropText = document.getElementById("drop-text");
const button = document.getElementById("submit");
const message = document.getElementById("message");

function showChosenFile() {
  const file = input.files[0];
  dropText.textContent = file ? file.name : "Choose a file, or drop it here";
  button.disabled = !file;
  message.textContent = "";
}

input.addEventListener("change", showChosenFile);

["dragenter", "dragover"].forEach((name) =>
  zone.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.add("active");
  })
);
["dragleave", "drop"].forEach((name) =>
  zone.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.remove("active");
  })
);
zone.addEventListener("drop", (event) => {
  if (event.dataTransfer.files.length) {
    input.files = event.dataTransfer.files;
    showChosenFile();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  message.textContent = "Uploading...";

  try {
    const response = await fetch("/api/scans", {
      method: "POST",
      body: new FormData(form),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof body.detail === "string" ? body.detail : "The upload failed.");
    }
    window.location.href = `report.html?id=${encodeURIComponent(body.scan_id)}`;
  } catch (error) {
    message.textContent = error.message;
    button.disabled = false;
  }
});
