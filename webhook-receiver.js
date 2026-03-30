const http = require("http");

const PORT = 3001;
let requestCount = 0;

const server = http.createServer((req, res) => {
  if (req.method === "POST") {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      requestCount++;
      const timestamp = new Date().toISOString();
      console.log(`\n--- Webhook #${requestCount} received at ${timestamp} ---`);
      console.log(`Path: ${req.url}`);
      console.log(`Body: ${body}`);
      console.log("---");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, received: requestCount }));
    });
  } else {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "webhook receiver running", received: requestCount }));
  }
});

server.listen(PORT, () => {
  console.log(`Webhook receiver listening on http://localhost:${PORT}`);
});
