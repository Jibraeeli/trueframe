const scanId = new URLSearchParams(window.location.search).get("id");
const statusLine = document.getElementById("status");
const POLL_MS = 1500;

const STATUS_TEXT = {
  queued: "Waiting for a worker to pick this up...",
  processing: "Analysing your file...",
};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function formatTime(seconds) {
  if (seconds === null) return "Image";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `At ${minutes}:${rest}`;
}

function renderDetails(report) {
  const details = document.getElementById("details");
  const rows = [
    ["Model", report.checks.detector.model],
    ["Frames analysed", String(report.checks.detector.frames_analysed)],
    ...Object.entries(report.checks.metadata.fields).map(([key, value]) => [
      key.replaceAll("_", " "),
      value,
    ]),
  ];
  rows.forEach(([label, value]) => {
    details.append(el("dt", label), el("dd", value));
  });
}

function renderReport(scan) {
  const report = scan.report;
  document.getElementById("score").textContent = report.trust_score;
  document.getElementById("score-card").dataset.verdict = report.verdict;
  document.getElementById("verdict").textContent = report.verdict_label;
  document.getElementById("summary").textContent = report.summary;

  const evidence = document.getElementById("evidence");
  report.evidence.forEach((item) => {
    const row = el("li", undefined, item.effect);
    row.append(el("strong", item.signal), el("span", item.detail));
    evidence.append(row);
  });

  const frames = document.getElementById("frames");
  report.suspicious_frames.forEach((frame) => {
    const figure = el("figure");
    const image = el("img");
    image.src = `/api/scans/${encodeURIComponent(scanId)}/frames/${frame.index}`;
    image.alt = `Suspicious frame ${frame.index}`;
    const percent = Math.round(frame.fake_probability * 100);
    figure.append(image, el("figcaption", `${formatTime(frame.timestamp)}, ${percent}% likely fake`));
    frames.append(figure);
  });
  document.getElementById("frames-section").hidden = report.suspicious_frames.length === 0;

  renderDetails(report);
  const limitations = document.getElementById("limitations");
  report.limitations.forEach((text) => limitations.append(el("li", text)));

  statusLine.hidden = true;
  document.getElementById("report").hidden = false;
}

async function poll() {
  try {
    const response = await fetch(`/api/scans/${encodeURIComponent(scanId)}`);
    if (!response.ok) {
      statusLine.textContent = "This scan could not be found. Scans are removed after 24 hours.";
      return;
    }
    const scan = await response.json();
    document.getElementById("filename").textContent = scan.filename;

    if (scan.status === "complete") {
      renderReport(scan);
    } else if (scan.status === "failed") {
      statusLine.textContent = scan.error;
    } else {
      statusLine.textContent = STATUS_TEXT[scan.status];
      setTimeout(poll, POLL_MS);
    }
  } catch {
    statusLine.textContent = "Lost connection. Retrying...";
    setTimeout(poll, POLL_MS);
  }
}

if (scanId) {
  poll();
} else {
  statusLine.textContent = "No scan was specified.";
}
