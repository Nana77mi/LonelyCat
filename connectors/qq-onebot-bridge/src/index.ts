import http from "node:http";

import { defaultConfig } from "./config";

export const createServer = () => {
  const server = http.createServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, { "Content-Type": "text/plain" });
      res.end("ok");
      return;
    }

    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("not found");
  });

  return server;
};

export const start = () => {
  const server = createServer();
  server.listen(defaultConfig.port, () => {
    console.log(`QQ OneBot bridge listening on ${defaultConfig.port}`);
  });
};

if (process.env.NODE_ENV !== "test") {
  start();
}
