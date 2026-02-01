import request from "supertest";

import { createServer } from "../src/index";

describe("health endpoint", () => {
  it("returns ok", async () => {
    const server = createServer();
    const response = await request(server).get("/health");
    expect(response.status).toBe(200);
    expect(response.text).toContain("ok");
    server.close();
  });
});
